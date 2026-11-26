// Entirely fictional offline fixtures. No CLI, credentials, network or files.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {newYorkTime, normalizeHistoricalPages, parseCollectionOptions,
  requireDeclaredBarStart} from '../scripts/collect-moomoo-intraday.mjs';

const options = {symbol: 'SPY', observedAt: '2026-11-26T12:00:00Z'};
const row = (time = '2026-11-24 09:30:00', epoch = '2026-11-24T14:30:00Z') => ({
  time, timestamp: Date.parse(epoch) / 1000, is_blank: false,
  open_price: 100, high_price: 101, low_price: 99, close_price: 100.5, volume: 1000});
const page = rows => ({ret_type: 0, s2c: {kl_list: rows}});
const normalize = rows => normalizeHistoricalPages([page(rows)], options);

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
  assert.throws(() => parseCollectionOptions(['--timestamp-label', 'bar-end']), /INVALID_TIMESTAMP_LABEL/);
});
