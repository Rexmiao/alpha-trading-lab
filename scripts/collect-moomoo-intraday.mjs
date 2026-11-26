// Read-only desktop Host history adapter. No account, order or trading methods.
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {existsSync, mkdirSync, writeFileSync} from 'node:fs';
import {createConnection} from 'node:net';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const NY = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York',
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit',
  minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');

export function newYorkTime(epochMs) {
  const p = Object.fromEntries(NY.formatToParts(new Date(epochMs)).map(x => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}

function fromNewYorkTime(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/.exec(value);
  if (!match) throw Error('INVALID_BAR_TIME');
  const wall = Date.UTC(...match.slice(1).map((x, i) => Number(x) - (i === 1 ? 1 : 0)));
  let epoch = wall;
  for (let i = 0; i < 3; i++) {
    const displayed = newYorkTime(epoch);
    const parts = /^(\d+)-(\d+)-(\d+) (\d+):(\d+):(\d+)$/.exec(displayed);
    const displayedWall = Date.UTC(...parts.slice(1).map((x, j) => Number(x) - (j === 1 ? 1 : 0)));
    epoch += wall - displayedWall;
  }
  if (newYorkTime(epoch) !== value) throw Error('INVALID_OR_AMBIGUOUS_BAR_TIME');
  return epoch;
}

export function normalizeHistoricalPages(pages, {symbol, observedAt}) {
  if (!/^[A-Z][A-Z0-9.]{0,9}$/.test(symbol)) throw Error('INVALID_SYMBOL');
  const observed = Date.parse(observedAt);
  if (!Number.isFinite(observed)) throw Error('INVALID_OBSERVED_AT');
  const observedNYDate = newYorkTime(observed).slice(0, 10);
  const rows = [], seen = new Set(), blankRecords = [];
  for (const [pageIndex, page] of pages.entries()) {
    if (!Array.isArray(page?.s2c?.kl_list) || page.ret_type !== 0) throw Error('INVALID_HISTORY_RESPONSE');
    for (const [rowIndex, item] of page.s2c.kl_list.entries()) {
      if (item.is_blank === true) {
        blankRecords.push({page: pageIndex + 1, row: rowIndex, reason: 'provider_blank_bar'});
        continue;
      }
      const local = String(item.time || item.time_key || '');
      const fallbackEpoch = fromNewYorkTime(local);
      let epoch = fallbackEpoch;
      if (item.timestamp !== undefined && item.timestamp !== null) {
        const numeric = Number(item.timestamp);
        if (!Number.isFinite(numeric) || numeric <= 0) throw Error('INVALID_PROVIDER_TIMESTAMP');
        epoch = numeric < 1e11 ? numeric * 1000 : numeric;
        if (newYorkTime(epoch) !== local || Math.abs(epoch - fallbackEpoch) > 1)
          throw Error('PROVIDER_TIME_EPOCH_MISMATCH');
      }
      if (local.slice(0, 10) >= observedNYDate) throw Error('ONLY_PRIOR_COMPLETE_NY_DATES');
      const clock = local.slice(11);
      // Preserve the supplied timestamp. 16:00 is allowed here to detect a
      // possible end-label convention rather than silently shift timestamps.
      if (clock < '09:30:00' || clock > '16:00:00' || Number(clock.slice(3, 5)) % 5 || clock.slice(6) !== '00')
        throw Error('NON_RTH_OR_OFF_GRID_BAR');
      const row = {timestamp: new Date(epoch).toISOString().replace('.000Z', 'Z'), symbol};
      for (const column of ['open', 'high', 'low', 'close', 'volume']) {
        const value = item[column + '_price'] ?? item[column];
        if (value === null || value === undefined || value === '' || typeof value === 'boolean') throw Error('INVALID_OHLCV');
        row[column] = Number(value);
        if (!Number.isFinite(row[column]) || row[column] < 0 || (column !== 'volume' && row[column] === 0)) throw Error('INVALID_OHLCV');
      }
      if (row.high < Math.max(row.open, row.low, row.close) || row.low > Math.min(row.open, row.high, row.close)) throw Error('INVALID_OHLC');
      const key = row.timestamp + ':' + symbol;
      if (seen.has(key)) throw Error('DUPLICATE_BAR');
      seen.add(key);
      rows.push(row);
    }
  }
  rows.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  const sessions = {};
  for (const row of rows) {
    const local = newYorkTime(Date.parse(row.timestamp));
    const day = local.slice(0, 10);
    (sessions[day] ??= []).push(local.slice(11));
  }
  return {rows, audit: {provider_blank_records: blankRecords, sessions: Object.fromEntries(
    Object.entries(sessions).map(([day, clocks]) => [day, {bars: clocks.length, first: clocks[0], last: clocks.at(-1)}])),
    first: rows[0]?.timestamp ?? null, last: rows.at(-1)?.timestamp ?? null,
    timestamp_policy: 'provider timestamp converted to UTC without shifting; original NY time/epoch retained in raw response',
    bar_label: {status: 'provider-unverified', convention: null,
      observed_1600_label: Object.values(sessions).some(clocks => clocks.includes('16:00:00')),
      every_observed_session_starts_0930: Object.values(sessions).length > 0 &&
        Object.values(sessions).every(clocks => clocks[0] === '09:30:00')}}};
}

export function requireDeclaredBarStart(coverage, {declaredBarStart = false} = {}) {
  // Observed clock edges alone do not establish the provider's time convention.
  // Export additionally requires an explicit operator declaration and a source
  // reference. It is recorded as declared, never independently verified here.
  // Ambiguous labels are never shifted automatically, even after declaration.
  if (!declaredBarStart || !coverage.length || coverage.some(item =>
    item.bar_label?.observed_1600_label || !item.bar_label?.every_observed_session_starts_0930))
    throw Error('BAR_LABEL_UNVERIFIED');
  return true;
}

export function parseCollectionOptions(argv) {
  const result = {symbols: ['SPY', 'NVDA'], start: '2026-11-24', end: '2026-11-25', pageSize: 100, maxPages: 50, rehabType: 0,
    timestampLabel: 'unverified', verificationSource: null};
  for (let i = 0; i < argv.length; i += 2) {
    const flag = argv[i], value = argv[i + 1];
    if (!value) throw Error('INVALID_ARGUMENTS');
    if (flag === '--symbols') result.symbols = [...new Set(value.split(',').map(s => s.trim().toUpperCase()))];
    else if (flag === '--start') result.start = value;
    else if (flag === '--end') result.end = value;
    else if (flag === '--page-size') result.pageSize = Number(value);
    else if (flag === '--max-pages') result.maxPages = Number(value);
    else if (flag === '--rehab-type') result.rehabType = Number(value);
    else if (flag === '--timestamp-label') result.timestampLabel = value;
    else if (flag === '--verification-source') result.verificationSource = value;
    else throw Error('INVALID_ARGUMENTS');
  }
  if (!result.symbols.length || result.symbols.length > 12 || result.symbols.some(s => !/^[A-Z][A-Z0-9.]{0,9}$/.test(s))) throw Error('INVALID_SYMBOLS');
  if (![result.start, result.end].every(d => /^\d{4}-\d{2}-\d{2}$/.test(d) && !Number.isNaN(Date.parse(d)) &&
      new Date(d).toISOString().slice(0, 10) === d) || result.start > result.end) throw Error('INVALID_DATE_RANGE');
  if (result.end >= newYorkTime(Date.now()).slice(0, 10)) throw Error('END_MUST_BE_PRIOR_NY_DATE');
  if (!Number.isInteger(result.pageSize) || result.pageSize < 1 || result.pageSize > 1000 ||
      !Number.isInteger(result.maxPages) || result.maxPages < 1 || result.maxPages > 200 || ![0, 1, 2].includes(result.rehabType)) throw Error('INVALID_ARGUMENTS');
  if (!['unverified', 'bar-start'].includes(result.timestampLabel)) throw Error('INVALID_TIMESTAMP_LABEL');
  if (result.verificationSource !== null && (typeof result.verificationSource !== 'string' ||
      !result.verificationSource.trim() || result.verificationSource.length > 500 || /[\r\n\x00]/.test(result.verificationSource))) throw Error('INVALID_VERIFICATION_SOURCE');
  if (result.timestampLabel === 'bar-start' && !result.verificationSource) throw Error('BAR_LABEL_SOURCE_REQUIRED');
  return result;
}

function child(executable, args, env = process.env, timeout = 30000) {
  return new Promise((accept, reject) => {
    const processChild = spawn(executable, args, {env, windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe']});
    let output = '', bytes = 0, done = false;
    const finish = (error, result) => {if (done) return; done = true; clearTimeout(timer); error ? reject(error) : accept(result);};
    const timer = setTimeout(() => {processChild.kill(); finish(Error('LOCAL_REQUEST_TIMEOUT'));}, timeout);
    processChild.stdout.on('data', chunk => {bytes += chunk.length; if (bytes > 8000000) {processChild.kill(); finish(Error('RESPONSE_TOO_LARGE'));} else output += chunk.toString('utf8');});
    processChild.stderr.resume(); // Provider/credential stderr must never reach logs.
    processChild.on('error', () => finish(Error('CLI_UNAVAILABLE')));
    processChild.on('close', code => finish(null, {code, output}));
  });
}

function checkLocalListener(hostname, port) {
  return new Promise((accept, reject) => {
    const connection = createConnection({host: hostname.replace(/^\[|\]$/g, ''), port});
    let finished = false;
    const done = error => {if (finished) return; finished = true; connection.destroy(); error ? reject(Error('LOCAL_HOST_NOT_LISTENING')) : accept();};
    connection.setTimeout(1500, () => done(true));
    connection.on('connect', () => done(false));
    connection.on('error', () => done(true));
  });
}

async function localKey() {
  if (process.env.OPENAPI_HOST_APPKEY) return process.env.OPENAPI_HOST_APPKEY.trim();
  if (process.platform !== 'win32' || !process.env.LOCALAPPDATA) return '';
  const protectedPath = join(process.env.LOCALAPPDATA, 'PcrMarketWatch', 'moomoo-appkey.dpapi');
  if (!existsSync(protectedPath)) return '';
  const command = '$ErrorActionPreference="Stop"; $encoded=Get-Content -LiteralPath $env:ALPHA_PROTECTED_KEY_PATH -Raw; $value=ConvertTo-SecureString $encoded; $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($value); try { [Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }';
  const result = await child('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', command],
    {...process.env, ALPHA_PROTECTED_KEY_PATH: protectedPath,
      PSModulePath: join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'Modules')}, 10000);
  if (result.code !== 0) throw Error('PROTECTED_CREDENTIAL_UNAVAILABLE');
  return result.output.trim();
}

export async function collectIntraday(argv = process.argv.slice(2)) {
  const requested = parseCollectionOptions(argv);
  const started = new Date().toISOString();
  const folder = join(ROOT, 'data', 'intraday', `moomoo-5m-rth-${started.replace(/[:.]/g, '-')}-${process.pid}`);
  mkdirSync(folder, {recursive: true});
  const manifest = {source: 'moomoo', route: 'installed_desktop_cli_local_http_host', read_only: true,
    observed_at_start: started, observed_at_end: null, interval: '5m', kl_type: 6,
    session: 'RTH', extended_time: false, rehab_type: requested.rehabType,
    requested, pages: [], coverage: [], errors: [], csv: null, stage: 'configuration',
    bar_label: {status: 'provider-unverified', convention: null, csv_export_allowed: false,
      operator_declaration: requested.timestampLabel, verification_source: requested.verificationSource,
      independently_verified: false,
      reason: 'Default capture is probe/raw only. Export requires explicit --timestamp-label bar-start plus --verification-source after confirming provider semantics; this collector does not independently verify that declaration.'},
    historical_quota: {method: 'request-history-kl consumes historical-symbol quota; no quote subscription required', remaining: null,
      remaining_status: 'not queried; no quota method was exposed by the installed CLI help'},
    warnings: ['Raw prices stay local; no account, holding, cash, order or trade methods are present.',
      'Observed API data are not independently verified against another market data source.',
      'Prior NY calendar dates only; no market holiday completeness or historical universe reconstruction is claimed.',
      requested.rehabType === 0 ? 'Unadjusted OHLC requested (rehab_type=0); no corporate-action adjustment is reconstructed.' :
        'Adjusted OHLC requested; research approximation, not a claim of historical executable prices.',
      'CSV export requires an explicit bar-start declaration and its source reference, plus compatible observed RTH edges; the declaration is not independent verification. Raw timestamps are never guessed or shifted.']};
  try {
    const cli = process.env.ALPHA_MOOMOO_CLI || join(process.env.APPDATA || '', 'moomoo', '2.0', 'OpenAPI', 'moomooapp-cli.exe');
    const host = process.env.OPENAPI_HOST_URL || 'http://127.0.0.1:22222';
    const parsedHost = new URL(host);
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(parsedHost.hostname) || !['http:', 'https:'].includes(parsedHost.protocol) ||
        parsedHost.username || parsedHost.password || parsedHost.search || parsedHost.hash || !['', '/'].includes(parsedHost.pathname)) throw Error('ONLY_LOCAL_HOST_ALLOWED');
    manifest.host = parsedHost.origin;
    if (!existsSync(cli)) throw Error('CLI_UNAVAILABLE');
    const version = await child(cli, ['--version']);
    manifest.cli_version = version.code === 0 && /^openapi-cli [\d.]+\s*$/.test(version.output)
      ? version.output.trim() : 'unknown';
    manifest.stage = 'local_tcp_preflight';
    if (parsedHost.port) {
      await checkLocalListener(parsedHost.hostname, Number(parsedHost.port));
      manifest.tcp_preflight = {status: 'connected', checked_at: new Date().toISOString()};
    } else manifest.tcp_preflight = {status: 'not_run', reason: 'CLI port autodetection, no explicit port supplied'};
    manifest.stage = 'credential_loading';
    const key = await localKey();
    if (!key) throw Error('NOT_CONFIGURED');
    manifest.host_scope = 'loopback';
    manifest.cli_sha256 = null; // Do not read machine binaries or machine settings.
    const allRows = [];
    let lastRequest = 0;
    for (const symbol of requested.symbols) {
      const pages = [], seenCursors = new Set();
      let cursor = null, complete = false;
      for (let page = 1; page <= requested.maxPages; page++) {
        const wait = Math.max(0, 700 - (Date.now() - lastRequest));
        if (wait) await new Promise(accept => setTimeout(accept, wait));
        lastRequest = Date.now();
        const args = ['--raw', 'request-history-kl', '--rehab-type', String(requested.rehabType),
          '--kl-type', '6', '--begin-time', requested.start, '--end-time', requested.end,
          '--max-ack-kl-num', String(requested.pageSize), '--session', 'rth', '--no-extended-time'];
        if (cursor) args.push('--next-req-key', cursor);
        args.push('--symbol', 'US.' + symbol);
        manifest.stage = 'history_request';
        manifest.active_request = {symbol, page, started_at: new Date().toISOString(), has_cursor: Boolean(cursor)};
        const result = await child(cli, args, {...process.env, OPENAPI_HOST_URL: host, OPENAPI_HOST_APPKEY: key});
        const observedAt = new Date().toISOString();
        let payload;
        try {payload = JSON.parse(result.output.replace(/^\uFEFF/, ''));} catch {throw Error('LOCAL_SERVICE_UNAVAILABLE');}
        if (result.code !== 0 || payload.ret_type !== 0 || !Array.isArray(payload.s2c?.kl_list)) {
          const message = String(payload.ret_msg || '');
          throw Error(/key|auth|permission|权限|认证|鉴权/i.test(message) ? 'AUTH_OR_PERMISSION' : 'PROVIDER_REJECTED');
        }
        if (payload.s2c.security?.code && payload.s2c.security.code !== symbol) throw Error('PROVIDER_SYMBOL_MISMATCH');
        const rawName = `raw-${symbol}-${String(page).padStart(3, '0')}.json`;
        writeFileSync(join(folder, rawName), result.output, {encoding: 'utf8', flag: 'wx'});
        const nextCursor = payload.s2c.next_req_key || null;
        manifest.pages.push({symbol, page, observed_at: observedAt, path: rawName,
          bytes: Buffer.byteLength(result.output), sha256: sha256(result.output), bars: payload.s2c.kl_list.length,
          requested_page_size: requested.pageSize, has_next_req_key: Boolean(nextCursor)});
        pages.push(payload);
        manifest.active_request = null;
        if (!nextCursor) {complete = true; break;}
        if (typeof nextCursor !== 'string' || seenCursors.has(nextCursor)) throw Error('INVALID_OR_REPEATED_CURSOR');
        seenCursors.add(nextCursor);
        cursor = nextCursor;
      }
      if (!complete) throw Error('PAGINATION_LIMIT_REACHED');
      manifest.stage = 'normalization';
      const normalized = normalizeHistoricalPages(pages, {symbol, observedAt: new Date().toISOString()});
      if (!normalized.rows.length) throw Error('NO_OBSERVED_BARS');
      if (normalized.rows.some(row => {const day = newYorkTime(Date.parse(row.timestamp)).slice(0, 10);
        return day < requested.start || day > requested.end;})) throw Error('OUTSIDE_REQUESTED_DATE_RANGE');
      allRows.push(...normalized.rows);
      manifest.coverage.push({symbol, bars: normalized.rows.length, complete_pagination: complete, ...normalized.audit});
      process.stdout.write(JSON.stringify({symbol, bars: normalized.rows.length, pages: pages.length, status: 'saved_locally'}) + '\n');
    }
    manifest.raw_capture_status = 'complete';
    manifest.stage = 'bar_label_verification';
    requireDeclaredBarStart(manifest.coverage, {declaredBarStart: requested.timestampLabel === 'bar-start'});
    manifest.bar_label.status = 'operator-declared-not-independently-verified';
    manifest.bar_label.convention = 'bar-start';
    manifest.bar_label.csv_export_allowed = true;
    allRows.sort((a, b) => a.timestamp.localeCompare(b.timestamp) || a.symbol.localeCompare(b.symbol));
    const columns = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume'];
    const csv = columns.join(',') + '\n' + allRows.map(row => columns.map(column => row[column]).join(',')).join('\n') + '\n';
    const csvName = 'moomoo-5m-rth.csv';
    writeFileSync(join(folder, csvName), csv, {encoding: 'utf8', flag: 'wx'});
    manifest.csv = {path: csvName, rows: allRows.length, bytes: Buffer.byteLength(csv), sha256: sha256(csv), columns,
      timestamp_timezone: 'UTC', original_timestamp_timezone: 'America/New_York',
      timestamp_label: 'bar-start', timestamp_label_basis: 'explicit operator declaration; not independently verified by collector'};
    manifest.status = 'success';
    manifest.stage = 'complete';
  } catch (error) {
    const safe = /^[A-Z][A-Z0-9_]{2,80}$/.test(error?.message || '') ? error.message : 'LOCAL_COLLECTION_FAILED';
    manifest.errors.push({code: safe, stage: manifest.stage});
    manifest.status = 'failed';
  }
  manifest.observed_at_end = new Date().toISOString();
  const path = join(folder, 'manifest.json');
  writeFileSync(path, JSON.stringify(manifest, null, 2), {encoding: 'utf8', flag: 'wx'});
  process.stdout.write(JSON.stringify({status: manifest.status, manifest: path, csv: manifest.csv?.path ?? null,
    errors: manifest.errors, symbols_saved: manifest.coverage.length}) + '\n');
  return manifest;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {const result = await collectIntraday(); if (result.status !== 'success') process.exitCode = 2;}
  catch {process.stderr.write('INVALID_COLLECTION_CONFIGURATION\n'); process.exitCode = 2;}
}
