// Entirely fictional offline fixtures. No CLI, credentials, network or files.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {newYorkTime, normalizeHistoricalPages, parseCollectionOptions,
  requireDeclaredBarStart, requireDeclaredBarLabel, classifyCliFailure, compareOneMinuteToFiveMinute} from '../scripts/collect-moomoo-intraday.mjs';

const options = {symbol: 'SPY', observedAt: '2026-11-26T12:00:00Z'};
const row = (time = '2026-11-24 09:30:00', epoch = '2026-11-24T14:30:00Z') => ({
  time, timestamp: Date.parse(epoch) / 1000, is_blank: false,
  open_price: 100, high_price: 101, low_price: 99, close_price: 100.5, volume: 1000});
const page = rows => ({ret_type: 0, s2c: {kl_list: rows}});
const normalize = rows => normalizeHistoricalPages([page(rows)], options);

test('allows twelve stocks plus a benchmark but rejects a fourteenth symbol', () => {
  const names = ['SPY', ...Array.from({length:12}, (_, index) => 'TEST'+index)];
  assert.equal(parseCollectionOptions(['--symbols', names.join(','), '--start','2020-01-02','--end','2020-01-03']).symbols.length, 13);
  assert.throws(() => parseCollectionOptions(['--symbols', [...names,'EXTRA'].join(','), '--start','2020-01-02','--end','2020-01-03']), /INVALID_SYMBOLS/);
});

test('default route requests raw 5m research data, only SPY/NVDA, finite paging', () => {
  const settings = parseCollectionOptions(['--start', '2020-01-02', '--end', '2020-01-03']);
  assert.equal(settings.rehabType, 0);
  assert.equal(settings.timestampLabel, 'unverified');
  assert.equal(settings.verificationSource, null);
  assert.deepEqual(settings.symbols, ['SPY', 'NVDA']);
  assert.equal(settings.pageSize, 100);
  assert.equal(settings.maxPages, 50);
});

test('converts supplied NY winter time and epoch to UTC without shifting label', () => {
  const result = normalize([row()]);
  assert.equal(result.rows[0].timestamp, '2026-11-24T14:30:00Z');
  assert.equal(result.audit.sessions['2026-11-24'].first, '09:30:00');
  assert.equal(result.audit.bar_label.status, 'provider-unverified');
  assert.equal(result.audit.bar_label.convention, null);
});

test('uses IANA daylight-saving conversion, never fixed minus-five-hour offset', () => {
  const summer = normalize([row('2026-06-11 09:30:00', '2026-06-11T13:30:00Z')]);
  assert.equal(summer.rows[0].timestamp, '2026-06-11T13:30:00Z');
  assert.equal(newYorkTime(Date.parse('2026-11-24T14:30:00Z')), '2026-11-24 09:30:00');
});

test('missing provider epoch can be derived from explicit NY wall time', () => {
  const item = row();
  delete item.timestamp;
  assert.equal(normalize([item]).rows[0].timestamp, '2026-11-24T14:30:00Z');
});

test('disagreeing wall time and epoch are rejected instead of silently choosing one', () => {
  assert.throws(() => normalize([{...row(), timestamp: row().timestamp + 300}]), /PROVIDER_TIME_EPOCH_MISMATCH/);
});

test('duplicate bars across pagination are rejected', () => {
  assert.throws(() => normalizeHistoricalPages([page([row()]), page([row()])], options), /DUPLICATE_BAR/);
});

test('missing bars are not filled and sparse observed timestamps stay unchanged', () => {
  const result = normalize([row(), row('2026-11-24 09:40:00', '2026-11-24T14:40:00Z')]);
  assert.equal(result.rows.length, 2);
  assert.deepEqual(result.rows.map(value => value.timestamp), ['2026-11-24T14:30:00Z', '2026-11-24T14:40:00Z']);
});

test('current/future NY dates are excluded conservatively before any guessed bar completion', () => {
  assert.throws(() => normalize([row('2026-11-26 09:30:00', '2026-11-26T14:30:00Z')]), /ONLY_PRIOR_COMPLETE_NY_DATES/);
});

test('extended session and off-grid times do not become RTH five-minute data', () => {
  assert.throws(() => normalize([row('2026-11-24 08:30:00', '2026-11-24T13:30:00Z')]), /NON_RTH_OR_OFF_GRID_BAR/);
  assert.throws(() => normalize([row('2026-11-24 09:31:00', '2026-11-24T14:31:00Z')]), /NON_RTH_OR_OFF_GRID_BAR/);
});

test('invalid OHLC, missing values and infinities fail rather than fill or repair', () => {
  assert.throws(() => normalize([{...row(), high_price: 99}]), /INVALID_OHLC/);
  assert.throws(() => normalize([{...row(), close_price: null}]), /INVALID_OHLCV/);
  assert.throws(() => normalize([{...row(), volume: Infinity}]), /INVALID_OHLCV/);
});

test('provider blank bars have explicit audit records and do not become prices', () => {
  const result = normalize([{...row(), is_blank: true}]);
  assert.equal(result.rows.length, 0);
  assert.equal(result.audit.provider_blank_records.length, 1);
});

test('even a 09:30 observed edge does not independently verify provider bar-start semantics', () => {
  const audit = normalize([row()]).audit;
  assert.equal(audit.bar_label.every_observed_session_starts_0930, true);
  assert.throws(() => requireDeclaredBarStart([audit]), /BAR_LABEL_UNVERIFIED/);
});

test('16:00 labels block upload-ready CSV and are never shifted back five minutes', () => {
  const result = normalize([row(), row('2026-11-24 16:00:00', '2026-11-24T21:00:00Z')]);
  assert.equal(result.rows[1].timestamp, '2026-11-24T21:00:00Z');
  assert.equal(result.audit.bar_label.observed_1600_label, true);
  assert.throws(() => requireDeclaredBarStart([result.audit], {declaredBarStart: true}), /BAR_LABEL_UNVERIFIED/);
});

test('lack of observed 09:30 edge remains unverified even with a putative provider contract', () => {
  const audit = normalize([row('2026-11-24 09:35:00', '2026-11-24T14:35:00Z')]).audit;
  assert.throws(() => requireDeclaredBarStart([audit], {declaredBarStart: true}), /BAR_LABEL_UNVERIFIED/);
});

test('a separate verified fixture contract plus compatible observed edges can pass the pure gate', () => {
  assert.equal(requireDeclaredBarStart([normalize([row()]).audit], {declaredBarStart: true}), true);
});

test('CLI inputs reject invalid calendar dates, unbounded pages and unsupported arbitrary flags', () => {
  assert.throws(() => parseCollectionOptions(['--start', '2020-02-30']), /INVALID_DATE_RANGE/);
  assert.throws(() => parseCollectionOptions(['--page-size', '1001']), /INVALID_ARGUMENTS/);
  assert.throws(() => parseCollectionOptions(['--max-pages', '0']), /INVALID_ARGUMENTS/);
  assert.throws(() => parseCollectionOptions(['--symbols', 'SPY;OTHER']), /INVALID_SYMBOLS/);
  assert.throws(() => parseCollectionOptions(['--account', 'FORBIDDEN']), /INVALID_ARGUMENTS/);
});


test('explicit bar-start export declaration requires a source and does not claim independent verification', () => {
  assert.throws(() => parseCollectionOptions(['--timestamp-label', 'bar-start']), /BAR_LABEL_SOURCE_REQUIRED/);
  const settings = parseCollectionOptions(['--timestamp-label', 'bar-start', '--verification-source', 'offline fixture reviewed by operator']);
  assert.equal(settings.timestampLabel, 'bar-start');
  assert.equal(settings.verificationSource, 'offline fixture reviewed by operator');
  assert.throws(() => parseCollectionOptions(['--timestamp-label', 'bar-midpoint']), /INVALID_TIMESTAMP_LABEL/);
});

test('CLI stderr business envelope exposes only protocol codes and a safe reason', () => {
  const diagnostic = classifyCliFailure('{"error":"business error ret_type=-1 err_code=-1002: 请求获取实时K线接口前，请先订阅KL_Day数据"}');
  assert.deepEqual(diagnostic, {code:'PROVIDER_SUBSCRIPTION_REQUIRED', ret_type:-1, err_code:-1002});
});

test('CLI error classification never returns supplied credential or URL values', () => {
  const diagnostic = classifyCliFailure('authorization failed: appkey=FICTIONAL_SECRET_VALUE url=https://example.invalid/?token=FICTIONAL_TOKEN');
  assert.equal(diagnostic.code, 'AUTH_OR_PERMISSION');
  assert.equal(JSON.stringify(diagnostic).includes('FICTIONAL'), false);
  assert.equal(classifyCliFailure('historical quota exhausted').code, 'HISTORY_QUOTA_OR_PERMISSION');
  assert.equal(classifyCliFailure('unknown option --made-up').code, 'CLI_ARGUMENT_ERROR');
});


test('declared bar-end conversion preserves original labels, UTC start and availability', () => {
 const source=page([row('2026-11-24 09:35:00','2026-11-24T14:35:00Z'),row('2026-11-24 16:00:00','2026-11-24T21:00:00Z')]);
 const result=normalizeHistoricalPages([source],{...options,timestampLabel:'bar-end'});
 assert.deepEqual(result.rows.map(x=>x.timestamp),['2026-11-24T14:30:00Z','2026-11-24T20:55:00Z']);
 assert.equal(result.audit.timestamp_transformations[0].provider_time_new_york,'2026-11-24 09:35:00');
 assert.equal(result.audit.timestamp_transformations[0].available_at,'2026-11-24T14:35:00Z');
 assert.equal(result.audit.as_of,'2026-11-24T21:00:00Z');
 assert.equal(requireDeclaredBarLabel([result.audit],{timestampLabel:'bar-end'}),true);
 assert.throws(()=>requireDeclaredBarLabel([result.audit],{timestampLabel:'bar-start'}),/BAR_LABEL_UNVERIFIED/);
});

test('native five-minute volume survives explicit end-label normalization unchanged', () => {
 const item={...row('2026-11-24 09:35:00','2026-11-24T14:35:00Z'),volume:1234,hp_volume:1234.25};
 const result=normalizeHistoricalPages([page([item])],{...options,timestampLabel:'bar-end'});
 assert.equal(result.rows[0].volume,1234);
 assert.equal(item.time,'2026-11-24 09:35:00');
});

test('bar-end declaration still rejects an incompatible opening clock and needs source metadata', () => {
 assert.throws(()=>normalizeHistoricalPages([page([row()])],{...options,timestampLabel:'bar-end'}),/NON_RTH_DECLARED_LABEL/);
 assert.throws(()=>parseCollectionOptions(['--timestamp-label','bar-end']),/BAR_LABEL_SOURCE_REQUIRED/);
 const cfg=parseCollectionOptions(['--timestamp-label','bar-end','--verification-source','fictional reviewed test contract']);
 assert.equal(cfg.timestampLabel,'bar-end');
});

test('same-provider aggregation distinguishes OHLC timing support from native-volume differences', () => {
 const one=Array.from({length:5},(_,i)=>({time:'2026-11-24 09:'+String(31+i)+':00',timestamp:Date.parse('2026-11-24T14:'+String(31+i)+':00Z')/1000,open_price:100+i,high_price:101+i,low_price:99+i,close_price:100.5+i,volume:100,hp_volume:100.2}));
 const five=[{time:'2026-11-24 09:35:00',timestamp:Date.parse('2026-11-24T14:35:00Z')/1000,open_price:100,high_price:105,low_price:99,close_price:104.5,volume:501,hp_volume:501}];
 const check=compareOneMinuteToFiveMinute(one,five);
 assert.equal(check.timestamp_alignment_supported,true);
 assert.equal(check.price_matched_bars,1);
 assert.equal(check.all_match,false);
 assert.equal(check.volume_comparison.mismatch_count,1);
 assert.equal(check.volume_comparison.max_abs,1);
 assert.equal(check.volume_comparison.totals_match,false);
 assert.equal(check.volume_comparison.hp_volume_mismatch_count,0);
 const wrong=compareOneMinuteToFiveMinute(one,[{...five[0],close_price:200}]);
 assert.equal(wrong.timestamp_alignment_supported,false);
 assert.equal(compareOneMinuteToFiveMinute(one.slice(1),five).timestamp_alignment_supported,false);
});

test('exclusive end boundary may be today while future boundaries are rejected', () => {
 const today=newYorkTime(Date.now()).slice(0,10);
 const cfg=parseCollectionOptions(['--start','2020-01-02','--end',today]);
 assert.equal(cfg.end,today);
 assert.throws(()=>parseCollectionOptions(['--start','2020-01-02','--end','2099-01-02']),/END_EXCLUSIVE_AFTER_NY_TODAY/);
 assert.throws(()=>parseCollectionOptions(['--start','2020-01-02','--end','2020-01-02']),/INVALID_DATE_RANGE/);
});

test('declared end labels convert in summer UTC without changing volume or availability', () => {
 const item=row('2026-06-11 09:35:00','2026-06-11T13:35:00Z');
 const result=normalizeHistoricalPages([page([item])],{...options,timestampLabel:'bar-end'});
 assert.equal(result.rows[0].timestamp,'2026-06-11T13:30:00Z');
 assert.equal(result.audit.timestamp_transformations[0].available_at,'2026-06-11T13:35:00Z');
 assert.equal(result.rows[0].volume,item.volume);
});
