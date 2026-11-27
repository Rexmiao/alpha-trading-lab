"""Offline QQQ/SPY/DIA opening-downside study with adjustable gain thresholds.

Reads a completed local capture; never contacts moomoo, HF, or another service.
All market-data artifacts are written beneath the ignored state/premarket-365/.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from html import escape
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.premarket_events import analyze_symbol, analyze_symbol_thresholds
from scripts.collect_premarket_history import load_capture_manifest

SYMBOLS = ("QQQ", "SPY")
ALLOWED_SYMBOLS = ("QQQ", "SPY", "DIA")
DEFAULT_GRID_PCT = "0.5,1,1.5,2,2.5,3"
START = "2025-11-27"
END = "2026-11-27"
OUTPUT_ROOT = ROOT / "state" / "premarket-365"
DEFAULT_CAPTURE = ROOT / "data" / "premarket-history" / "20261127T194111274054Z"
DEFINITIONS = {
    "fixed_0925": ("09:25 completed-minute close", "09:25 已完成分钟收盘价"),
    "fixed_0929": ("09:29 completed-minute close", "09:29 已完成分钟收盘价"),
    "ever_before_0925": ("Any premarket high through 09:25", "04:00 至 09:25 期间最高价"),
    "ever_before_open": ("Any premarket high through 09:30 · exploratory", "04:00 至 09:30 期间最高价 · 探索性"),
}


class ReportError(ValueError):
    """The capture or report contract is not satisfied."""


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def threshold_pct(value) -> Decimal:
    """Percent input, strictly positive through 10%, at most six decimals."""
    if isinstance(value, bool):
        raise ReportError("invalid_premarket_threshold_pct")
    try:
        value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ReportError("invalid_premarket_threshold_pct") from None
    if not value.is_finite() or value <= 0 or value > 10 or value.as_tuple().exponent < -6:
        raise ReportError("premarket_threshold_pct_must_be_positive_up_to_10_with_6_decimals")
    return value


def threshold_grid_pct(value) -> tuple[Decimal, ...]:
    parts = value.split(",") if isinstance(value, str) else tuple(value)
    if not 1 <= len(parts) <= 20:
        raise ReportError("threshold_grid_requires_1_to_20_values")
    values = tuple(threshold_pct(v) for v in parts)
    if len(set(values)) != len(values):
        raise ReportError("duplicate_threshold_grid_value")
    return tuple(sorted(values))


def _local_file(folder: Path, name: str) -> Path:
    if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
        raise ReportError("capture_file_must_be_a_leaf_name")
    path = (folder / name).resolve()
    if path.parent != folder:
        raise ReportError("capture_file_outside_folder")
    return path


def validate_capture(folder: Path) -> tuple[dict, dict, dict]:
    """Validate all pages before yielding any rows to the study engine."""
    folder = folder.resolve()
    manifest = load_capture_manifest(folder)
    expected = {"source": "moomoo_desktop_history", "target_start": START,
                "target_end_exclusive": END, "end_exclusive": END, "interval": "1m",
                "session": "ALL", "rehab_type": 0, "read_only": True,
                "account_requests": 0, "orders": 0, "today_excluded": True,
                "target_calendar_days": 365}
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise ReportError("capture_scope_mismatch")
    symbols = manifest.get("symbols")
    if (not isinstance(symbols, list) or not symbols or len(set(symbols)) != len(symbols)
            or any(s not in ALLOWED_SYMBOLS for s in symbols)
            or set(manifest.get("streams", {})) != set(symbols)):
        raise ReportError("capture_symbols_must_be_unique_QQQ_SPY_DIA_subset")
    if manifest.get("complete") is not True:
        raise ReportError("capture_pagination_not_complete")
    if not manifest.get("finished_at"):
        raise ReportError("capture_finished_at_missing")
    # A retry can preserve historical errors. Completion and every page are
    # independently rechecked; errors remain visible in the run provenance.
    proofs = {"pages": [], "collectors": []}
    seen_files = set()
    for symbol in symbols:
        stream = manifest["streams"][symbol]
        pages = stream.get("pages", [])
        if stream.get("complete_pagination") is not True or not pages:
            raise ReportError("symbol_pagination_not_complete")
        total = 0
        cursors = set()
        for ordinal, record in enumerate(pages, 1):
            filename = record.get("file", "")
            if filename != f"{symbol}-{ordinal:04d}.json" or record.get("page") != ordinal or filename in seen_files:
                raise ReportError("capture_page_order_or_filename")
            seen_files.add(filename)
            raw = _local_file(folder, filename).read_bytes()
            fingerprint = sha256(raw)
            if fingerprint != record.get("sha256") or len(raw) != record.get("bytes"):
                raise ReportError("capture_page_hash_or_length_mismatch")
            envelope = json.loads(raw)
            payload = envelope.get("s2c", {})
            security = payload.get("security", {})
            rows = payload.get("kl_list")
            if envelope.get("ret_type") != 0 or security.get("code") != symbol or security.get("market") != "US":
                raise ReportError("capture_page_symbol_or_status")
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ReportError("capture_page_rows_invalid")
            if len(rows) != record.get("rows"):
                raise ReportError("capture_page_row_count_mismatch")
            for row in rows:
                for key in ("code", "symbol"):
                    if key in row and str(row[key]).removeprefix("US.") != symbol:
                        raise ReportError("capture_mixed_symbol_row")
            cursor = payload.get("next_req_key")
            if cursor != record.get("next_req_key"):
                raise ReportError("capture_page_cursor_mismatch")
            if ordinal < len(pages) and (not isinstance(cursor, str) or not cursor or cursor in cursors):
                raise ReportError("capture_pagination_not_progressing")
            if ordinal == len(pages) and cursor:
                raise ReportError("capture_terminal_page_has_cursor")
            if cursor:
                cursors.add(cursor)
            total += len(rows)
            proofs["pages"].append({"symbol": symbol, "file": filename, "sha256": fingerprint,
                                    "bytes": len(raw), "rows": len(rows)})
        if total != stream.get("rows"):
            raise ReportError("capture_stream_row_count_mismatch")
    for record in manifest.get("collector_runs", []):
        raw = _local_file(folder, record["source"]).read_bytes()
        if sha256(raw) != record.get("sha256"):
            raise ReportError("capture_collector_hash_mismatch")
        proofs["collectors"].append({"file": record["source"], "sha256": sha256(raw)})
    calendar_raw = (folder / "calendar.json").read_bytes()
    calendar = json.loads(calendar_raw)
    if calendar.get("calendar") != "XNYS" or calendar.get("target_start") != START or calendar.get("target_end_exclusive") != END:
        raise ReportError("calendar_scope_mismatch")
    sessions = calendar.get("sessions", {})
    target_dates = sorted(d for d in sessions if START <= d < END)
    if len(target_dates) != 250 or target_dates[0] != "2025-11-28" or target_dates[-1] != "2026-11-25":
        raise ReportError("calendar_target_sessions_mismatch")
    if "2025-11-26" not in sessions or any(d >= END for d in sessions):
        raise ReportError("calendar_warmup_or_end_mismatch")
    proofs["calendar"] = {"file": "calendar.json", "sha256": sha256(calendar_raw),
                          "calendar": calendar["calendar"], "library_version": calendar.get("library_version"),
                          "target_sessions": len(target_dates), "total_sessions_with_warmup": len(sessions)}
    return manifest, calendar, proofs


def iter_symbol_rows(folder: Path, manifest: dict, symbol: str):
    """Yield original bars without repair or filling; recheck the read hash."""
    for record in manifest["streams"][symbol]["pages"]:
        raw = _local_file(folder, record["file"]).read_bytes()
        if sha256(raw) != record["sha256"]:
            raise ReportError("capture_page_changed_after_validation")
        yield from json.loads(raw)["s2c"]["kl_list"]


def _csv(rows: list[dict]) -> str:
    if not rows:
        return "symbol,date,definition\n"
    fields = list(dict.fromkeys(key for row in rows for key in row))
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def flatten_daily(results: dict) -> tuple[list[dict], list[dict]]:
    daily_rows, event_rows = [], []
    for symbol, result in results.items():
        for day in result["daily"]:
            outcome = day["outcome"] or {}
            base = {"symbol": symbol, "date": day["date"], "previous_session_date": day["previous_session_date"],
                    "previous_rth_close": day["previous_rth_close"], "base_eligible": day["base_eligible"],
                    "first30_complete": day["quality"]["first30"]["complete"],
                    "full_rth_complete": day["quality"]["full_rth"]["complete"],
                    "exclusion_reasons": "|".join(day["exclusion_reasons"])}
            base.update({k: v for k, v in outcome.items() if k != "windows"})
            for window in outcome.get("windows", []):
                base[f"max_drop_{window['minutes']}m"] = window["max_drop_from_open"]
            for name, definition in day["definitions"].items():
                for key in ("condition_known", "analysis_eligible", "triggered", "premarket_return", "observed_hit_in_incomplete_window"):
                    base[f"{name}_{key}"] = definition[key]
                base[f"{name}_exclusion_reasons"] = "|".join(definition["exclusion_reasons"])
                if definition["analysis_eligible"] and definition["triggered"]:
                    event_rows.append({"symbol": symbol, "date": day["date"], "definition": name,
                                       "premarket_return": definition["premarket_return"],
                                       "previous_rth_close": day["previous_rth_close"],
                                       **{k: v for k, v in outcome.items() if k != "windows"}})
            daily_rows.append(base)
    return daily_rows, event_rows


def tr(en: str, zh: str) -> str:
    return f'<span class="en">{escape(en)}</span><span class="zh">{escape(zh)}</span>'


def pct(value, digits=2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def num(value, digits=2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def _svg_distribution(events: list[dict], baseline: list[dict]) -> str:
    if not baseline:
        return '<p class="muted">' + tr("No eligible days for a distribution.", "没有符合条件的交易日，无法绘制分布。") + '</p>'
    edges = (0, .0025, .005, .01, .015, .02, .03)
    groups = [[sum(low <= d["outcome"]["max_drop_from_open"] < high for d in group) for low, high in zip(edges, (*edges[1:], float("inf")))] for group in (baseline, events)]
    rates = [[count / len(group) if group else 0 for count in counts] for counts, group in zip(groups, (baseline, events))]
    ceiling = max(.01, *(v for group in rates for v in group))
    parts = ['<svg viewBox="0 0 640 245" role="img" aria-label="Maximum first-30-minute downside distribution">', '<path d="M48 18V200H625" fill="none" stroke="#9aa7b3"/>']
    for n in range(5):
        y = 200 - n * 42
        parts.append(f'<path d="M48 {y}H625" stroke="#e6ebef"/><text x="41" y="{y+4}" text-anchor="end">{ceiling*n/4:.0%}</text>')
    labels = ("0–0.25", "0.25–0.5", "0.5–1", "1–1.5", "1.5–2", "2–3", "≥3")
    for i, label in enumerate(labels):
        x = 65 + i * 80
        for j, color in ((0, "#94a3b8"), (1, "#ce6d20")):
            height = rates[j][i] / ceiling * 168
            parts.append(f'<rect x="{x+j*25}" y="{200-height:.2f}" width="23" height="{height:.2f}" fill="{color}"><title>{escape(label)}%: {groups[j][i]}/{len((baseline,events)[j])}</title></rect>')
        parts.append(f'<text x="{x+24}" y="220" text-anchor="middle">{label}%</text>')
    parts.append('</svg>')
    return ''.join(parts)


def _svg_dates(events: list[dict]) -> str:
    if not events:
        return '<p class="muted">' + tr("No qualifying events; no event-date plot.", "没有符合条件的事件，因此不绘制事件日期图。") + '</p>'
    maximum = max(.005, max(d["outcome"]["max_drop_from_open"] for d in events)) * 1.12
    origin = date.fromisoformat(START).toordinal()
    parts = ['<svg viewBox="0 0 640 245" role="img" aria-label="Qualifying event dates and maximum downside">', '<path d="M48 18V200H625" fill="none" stroke="#9aa7b3"/>']
    for n in range(5):
        y = 200 - n * 42
        parts.append(f'<path d="M48 {y}H625" stroke="#e6ebef"/><text x="41" y="{y+4}" text-anchor="end">{maximum*n/4:.1%}</text>')
    for d in sorted(events, key=lambda d: d["date"]):
        x = 55 + (date.fromisoformat(d["date"]).toordinal() - origin) / 365 * 560
        y = 200 - d["outcome"]["max_drop_from_open"] / maximum * 168
        parts.append(f'<path d="M{x:.2f} 200V{y:.2f}" stroke="#e6c6ad"/><circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="#ce6d20"><title>{d["date"]}: {pct(d["outcome"]["max_drop_from_open"])}; premarket {pct(d["definitions"][d["_definition"]]["premarket_return"])}</title></circle>')
    parts.extend(['<text x="55" y="223">2025-11-27</text>', '<text x="620" y="223" text-anchor="end">2026-11-26</text>', '</svg>'])
    return ''.join(parts)


def _probability_table(summary: dict) -> str:
    head = [tr("Opening downside", "开盘后最大下跌"), tr("Event days", "事件日"), tr("Historical proportion · 95% Wilson interval", "历史比例 · 95% Wilson 区间"), tr("Same-eligible-day baseline", "相同可用日的基线"), tr("Baseline interval", "基线区间")]
    rows = []
    for event, baseline in zip(summary["events"]["thresholds"], summary["baseline_same_eligible_days"]["thresholds"]):
        interval = "—" if event["n"] == 0 else f'{pct(event["proportion"])} [{pct(event["lower"])}, {pct(event["upper"])}]'
        base_interval = "—" if baseline["n"] == 0 else f'[{pct(baseline["lower"])}, {pct(baseline["upper"])}]'
        rows.append(["≥ " + pct(event["drop_threshold"]), f'{event["k"]}/{event["n"]}', interval,
                     f'{baseline["k"]}/{baseline["n"]} · {pct(baseline["proportion"])}', base_interval])
    negative = summary["events"]["negative_30m_close"]
    baseline = summary["baseline_same_eligible_days"]["negative_30m_close"]
    interval = "—" if not negative["n"] else f'{pct(negative["proportion"])} [{pct(negative["lower"])}, {pct(negative["upper"])}]'
    rows.append([tr("10:00 close below 09:30 open", "10:00 收盘价低于 09:30 开盘价"), f'{negative["k"]}/{negative["n"]}', interval,
                 f'{baseline["k"]}/{baseline["n"]} · {pct(baseline["proportion"])}', "—" if not baseline["n"] else f'[{pct(baseline["lower"])}, {pct(baseline["upper"])}]'])
    return table(head, rows)


def table(head: list[str], rows: list[list[str]]) -> str:
    return '<div class="table-wrap"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in head) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def _render_reference_html(report: dict) -> str:
    sections = []
    for symbol, result in report["results"].items():
        coverage = result["coverage"]
        crows = [
            [tr("Exchange sessions in the 365-calendar-day window", "365 个自然日内交易日"), str(coverage["calendar_sessions"])],
            [tr("Complete 30-minute opening window", "完整开盘 30 分钟"), str(coverage["first30_complete_days"])],
            [tr("Previous actual session close available", "上一真实交易日收盘价可用"), str(coverage["previous_close_valid_days"])],
            [tr("Valid opening baseline days", "开盘基线有效日"), str(coverage["valid_opening_days"])],
            [tr("Full regular session complete · diagnostic only", "整个常规交易时段完整 · 仅诊断"), str(coverage["full_rth_complete_days"])],
            [tr("Archived source rows · includes extended hours and warm-up", "归档原始行 · 含延长时段及预热"), str(report["source"]["streams"][symbol]["rows"])],
        ]
        content = '<section id="' + symbol + '"><h2>' + symbol + '</h2>' + table([tr("Coverage", "数据覆盖"), tr("Days / rows", "天数／行数")], crows)
        for index, (name, titles) in enumerate(DEFINITIONS.items()):
            summary = result["summary"][name]
            events = [{**day, "_definition": name} for day in result["daily"] if day["definitions"][name]["analysis_eligible"] and day["definitions"][name]["triggered"]]
            baseline = [day for day in result["daily"] if day["definitions"][name]["analysis_eligible"]]
            dist = summary["events"]["drop_distribution"]
            bdist = summary["baseline_same_eligible_days"]["drop_distribution"]
            content += f'<details class="definition" {"open" if index == 0 else ""}><summary>{tr(*titles)} · n={dist["n"]}</summary>'
            content += '<p>' + tr(f'Condition: premarket gain strictly >2.50%. Eligible days: {summary["eligible_days"]}/{summary["calendar_sessions"]}; qualifying events: {dist["n"]}.', f'条件：盘前涨幅严格大于 2.50%。可用日：{summary["eligible_days"]}/{summary["calendar_sessions"]}；符合条件事件：{dist["n"]}。') + '</p>'
            if not dist["n"]:
                content += '<p class="notice">' + tr("No eligible events in this definition. Its conditional probability and drop quantiles are unavailable, not 0%.", "此定义没有符合条件的可用事件。条件概率与下跌分位数不可估计，不是 0%。") + '</p>'
            content += _probability_table(summary)
            content += table([tr("First-30-minute maximum downside", "开盘半小时最大下跌"), tr("Event days", "事件日"), tr("Same-eligible-day baseline", "相同可用日基线")],
                             [[tr(en, zh), pct(dist[key]), pct(bdist[key])] for key, en, zh in (("mean", "Mean", "均值"), ("median", "Median", "中位数"), ("p90", "90th percentile", "第 90 百分位"), ("max", "Worst observed", "观察到的最大值"))])
            content += '<div class="charts"><figure>' + _svg_distribution(events, baseline) + '<figcaption>' + tr("Frequency by downside bin. Gray: eligible baseline; orange: >2.5% event days. Each group sums to 100% when n>0.", "最大下跌的频率分布。灰：可用日基线；橙：盘前 >2.5% 的事件日。n>0 时各组频率总和为 100%。") + '</figcaption></figure><figure>' + _svg_dates(events) + '<figcaption>' + tr("Event dates, ordered by calendar date; vertical axis is downside from the 09:30 open proxy.", "按日期排序的事件；纵轴为相对 09:30 开盘代理价的最大下跌。") + '</figcaption></figure></div>'
            event_rows = [[d["date"], pct(d["definitions"][name]["premarket_return"]), num(d["outcome"]["open_proxy"]), num(d["outcome"]["low_30m"]), pct(d["outcome"]["max_drop_from_open"]), d["outcome"]["low_bar_start_et"][11:16] + "–" + d["outcome"]["low_bar_end_et"][11:16], pct(d["outcome"]["return_30m"])] for d in events]
            if event_rows:
                content += '<h3>' + tr("Every qualifying event · no selected success cases", "全部符合条件事件 · 不筛选有效案例") + '</h3>' + table([tr("Date", "日期"), tr("Premarket gain", "盘前涨幅"), tr("Open proxy", "开盘代理价"), tr("30m low", "30 分钟最低"), tr("Maximum downside", "最大下跌"), tr("Low minute ET", "低点所在分钟 ET"), tr("30m return", "30 分钟收益")], event_rows)
            content += '<details><summary>' + tr("Eligibility and excluded observations", "可用性与被排除样本") + '</summary>'
            counts = summary["excluded_reason_counts"]
            content += table([tr("Reason (machine-readable audit code)", "原因（审计代码）"), tr("Excluded days · reasons may overlap", "被排除天数 · 原因可重叠")], [[escape(k), str(v)] for k, v in counts.items()])
            status_rows = []
            for status, en, zh in (("valid", "Valid positive-volume minute", "有效正成交量分钟"),
                                   ("zero_volume", "Present bar, zero volume", "K 线存在但成交量为零"),
                                   ("blank", "Provider blank bar", "供应商空白 K 线"),
                                   ("missing", "Minute absent from archived response", "归档响应未包含该分钟"),
                                   ("invalid", "Invalid timestamp / OHLCV", "时间戳／OHLCV 无效"),
                                   ("duplicate", "Duplicate source minute", "原始分钟重复"),
                                   ("future", "Not completed when captured", "采集时尚未完成")):
                quality_counts = [day["definitions"][name]["quality"]["counts"].get(status, 0) for day in result["daily"]]
                status_rows.append([tr(en, zh), str(sum(quality_counts)), str(sum(count > 0 for count in quality_counts))])
            content += table([tr("Premarket minute status", "盘前分钟状态"), tr("Minutes", "分钟数"), tr("Affected days", "涉及天数")], status_rows)
            content += '<p class="muted">' + tr("A zero-volume bar is present data, not a missing response. This conservative study requires positive-volume minutes to verify a full-window high; it does not fill zero-volume minutes with assumed trades. The quality exclusions and the primary denominator must therefore be read together.", "零成交量 K 线是已收到的数据，不是响应缺失。本研究保守要求正成交量分钟来核验完整窗口最高价，不以假定成交填补零成交量分钟。因此应同时查看质量排除原因与主样本分母。") + '</p>'
            hits = summary["incomplete_window_observed_hit_dates"]
            content += '<p>' + tr(f'Incomplete premarket windows with an observed >2.5% hit: {len(hits)}. These are not treated as complete-window probability trials.', f'盘前窗口不完整但已观察到 >2.5% 触发：{len(hits)} 天。这些天没有作为完整窗口条件概率的试验样本。') + '</p><p class="dates">' + (', '.join(hits) or '—') + '</p>'
            excluded_triggers = summary["triggered_but_outcome_excluded_dates"]
            content += '<p>' + tr("Known triggers excluded for outcome quality: ", "条件已知但因结果质量被排除：") + (', '.join(excluded_triggers) or '—') + '</p></details></details>'
        content += '</section>'
        sections.append(content)
    created = escape(report["created_at"])
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>QQQ / SPY · Premarket gains and opening downside</title><style>
    :root{font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;color:#172e42;background:#f3f6f9}body{max-width:1320px;margin:auto;padding:28px}.zh{display:none}body[data-language="zh"] .en{display:none}body[data-language="zh"] .zh{display:initial}header,section{background:white;border:1px solid #d9e2e9;border-radius:14px;padding:28px;margin:20px 0}h1{font-size:30px;line-height:1.25}h2{font-size:29px}h3{font-size:19px}.top{display:flex;justify-content:space-between;gap:20px;align-items:center}button{padding:9px 15px;border:1px solid #176779;background:#fff;border-radius:8px;color:#114758;cursor:pointer}button[aria-pressed="true"]{background:#176779;color:#fff}.muted,figcaption{color:#596f80;font-size:14px}.notice{background:#fff5df;border-left:4px solid #b97019;padding:14px}.table-wrap{overflow-x:auto;margin:16px 0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px 12px;border-bottom:1px solid #dce4ea;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}th{background:#f1f5f8;white-space:normal}.definition{border:1px solid #dce4ea;border-radius:10px;padding:16px;margin:16px 0}.definition>summary{font-weight:700;font-size:19px;cursor:pointer}.charts{display:grid;grid-template-columns:1fr 1fr;gap:20px}figure{margin:0;min-width:0}svg{width:100%;font:11px system-ui;fill:#506577}summary{cursor:pointer}.dates{font-size:13px;overflow-wrap:anywhere}a{color:#176779}code{font-size:12px;overflow-wrap:anywhere}.formula{font:18px/1.8 ui-monospace,monospace;background:#f1f5f8;padding:16px;border-radius:8px}@media(max-width:850px){body{padding:10px}header,section{padding:16px}.charts{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}h1{font-size:25px}}
    </style></head><body data-language="en"><header><div class="top"><b>Alpha Trading Lab · local historical research</b><div aria-label="Language"><button id="en" aria-pressed="true" onclick="setLanguage('en')">English</button> <button id="zh" aria-pressed="false" onclick="setLanguage('zh')">中文</button></div></div><h1>''' + tr("After a >2.5% premarket gain, how far did QQQ / SPY fall in the first 30 minutes?", "盘前涨幅超过 2.5% 后，QQQ／SPY 在开盘半小时内最大跌了多少？") + '</h1><p>' + tr("2025-11-27 ≤ exchange date < 2026-11-27 · 365 calendar days · 250 trading sessions · today excluded", "2025-11-27 ≤ 交易日期 < 2026-11-27 · 365 个自然日 · 250 个交易日 · 不含今天") + '</p><p class="notice">' + tr("Historical descriptive frequencies, not a calibrated future probability or a trading recommendation. QQQ and SPY are analyzed separately. Missing observations are excluded and disclosed; no synthetic filling.", "这是历史描述性频率，不是经校准的未来概率或交易建议。QQQ 与 SPY 分别分析。缺失观测被排除并披露，不使用合成填充。") + '</p><p>' + tr("Source: complete, hash-verified moomoo desktop 1-minute pagination, raw unadjusted prices. A 1-minute bar is end-labelled in America/New_York. The 09:30 opening price is the first regular-minute OHLC open, not an independently verified auction print.", "来源：分页完整且哈希校验通过的 moomoo 桌面端 1 分钟历史行情，原始未复权价格。K 线为美东时间结束标签。09:30 开盘价使用首根常规分钟 K 线的 open，不是独立核验的开盘竞价成交。") + '</p><div class="formula">D₃₀ = max(0, 1 − min Low[09:30,10:00) / Open₀₉:₃₀)</div><p>' + tr("Fixed-time definitions use completed-minute closes, not a day’s highest premarket print. Ever-high definitions require every positive-volume minute from 04:00 to the cutoff for the primary denominator. A partly observed hit is disclosed separately. The exploratory 09:30 peak is known only at the open and is not a validated executable entry signal.", "固定时点定义使用已完成分钟的收盘价，不是整段盘前最高价。曾触发定义的主样本要求从 04:00 至截止时点每一分钟都有有效正成交量行情。窗口不完整但观察到的触发单列披露。09:30 最高价仅在开盘时已知，属于探索性定义，不是已验证可成交信号。") + '</p><p>' + tr("The baseline uses the same eligible days for each definition, including event days. It is descriptive, not a causal control. The first 30 minutes must be complete; missing afternoon bars do not automatically discard an otherwise valid opening window. Actual exchange calendars account for DST and half days.", "每个定义的基线使用同一组可用日，包含事件日。这是描述性比较，不是因果对照。要求开盘 30 分钟完整；下午行情缺失不会自动排除已完整的开盘窗口。真实交易日历处理夏令时和提前收盘。") + '</p><nav><a href="#QQQ">QQQ</a> · <a href="#SPY">SPY</a> · <a href="#audit">' + tr("Limitations / reproducibility", "限制／复现") + '</a></nav></header>' + ''.join(sections) + '<section id="audit"><h2>' + tr("What this study can and cannot establish", "本研究能说明什么与有哪些限制") + '</h2><ul><li>' + tr("Wilson 95% intervals quantify finite event-count uncertainty under approximately independent dates. They do not correct serial dependence, regime shifts, multiple definitions, or the rare-event selection process. Zero events means unavailable.", "95% Wilson 区间反映近似日期独立假设下的有限样本不确定性；没有修正序列相关、市场状态变化、多定义或稀有事件筛选。没有事件时结果不可估计。") + '</li><li>' + tr("Bars were retrieved now. Historical publication/receipt clocks and vendor revisions were not reconstructed. This is not a point-in-time delivery audit or an out-of-sample strategy backtest.", "行情为本次取得；没有重建历史发布时间、实际接收时间或供应商修订。不是历史时点交付审计，也不是策略样本外回测。") + '</li><li>' + tr("Prices are raw unadjusted. Corporate actions and distributions have not been independently reconstructed; they may affect the prior-close gap. No audited corporate-action exclusions were supplied.", "价格为原始未复权。公司行为及分红没有独立重建，可能影响相对前收盘价的跳空；没有提供已审计的公司行为排除清单。") + '</li><li>' + tr("A low-price touch is not a realizable profit. No fees, bid/ask spread, slippage, position sizing, order placement, or brokerage account is part of this report.", "触及最低价不等于可实现利润。本报告不包含手续费、买卖价差、滑点、仓位或委托，也不接入券商账户。") + '</li><li>' + tr("All qualifying events and coverage failures remain in the JSON/daily CSV. Incomplete premarket windows are not silently called non-events. ETFs are not pooled into one probability.", "全部符合条件事件与覆盖失败保留在 JSON／逐日 CSV。盘前窗口不完整不会被默认为未触发事件；两只 ETF 不合并估计概率。") + '</li></ul><p>' + tr("Local artifacts: report.json, daily.csv, events.csv; all CSV returns and downside values use fractions (0.01 = 1%). Sources remain private/local and no raw OHLCV download is embedded in this page.", "本地文件：report.json、daily.csv、events.csv；CSV 内收益和下跌值采用小数（0.01 = 1%）。来源保留在私有本机，本页不嵌入原始 OHLCV 下载。") + '</p><p class="muted">' + tr("Run created at UTC: ", "运行创建时间 UTC：") + created + '</p><p class="muted">Engine SHA256: <code>' + report["code"]["engine_sha256"] + '</code><br>Runner SHA256: <code>' + report["code"]["runner_sha256"] + '</code><br>Calendar SHA256: <code>' + report["source"]["verification"]["calendar"]["sha256"] + '</code></p></section><script>function setLanguage(lang){document.body.dataset.language=lang;document.documentElement.lang=lang;document.getElementById("en").setAttribute("aria-pressed",lang==="en");document.getElementById("zh").setAttribute("aria-pressed",lang==="zh");}</script></body></html>'


def _explorer_payload(report: dict) -> dict:
    """Derived daily ratios/outcomes only; no minute OHLCV table in browser."""
    return {"default_pct": report["config"]["premarket_threshold_pct"],
            "grid_pct": report["config"]["threshold_grid_pct"],
            "fingerprints": {"code": report["code"], "captures": [
                {k: c[k] for k in ("symbols", "manifest_checkpoint", "manifest_sha256")}
                for c in report["source"]["captures"]]},
            "definitions": {name: list(titles) for name, titles in DEFINITIONS.items()},
            "symbols": {symbol: [{"date": day["date"],
                "definitions": {name: {"eligible": d["analysis_eligible"],
                    "known": d["condition_known"], "complete": d["quality"]["complete"],
                    "ratio": d.get("exact_premarket_return")} for name, d in day["definitions"].items()},
                "outcome": None if not day["outcome"] else {
                    "drop": day["outcome"]["max_drop_from_open"],
                    "exact_drop": day["outcome"].get("exact_max_drop"),
                    "return_30m": day["outcome"]["return_30m"],
                    "exact_return_30m": day["outcome"].get("exact_return_30m")}}
                for day in result["daily"]] for symbol, result in report["results"].items()}}


EXPLORER_JS = r'''
const STUDY=JSON.parse(document.getElementById('study-data').textContent);
let shownThreshold=STUDY.default_pct;
function esc(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function msg(en,zh){return document.documentElement.lang==='zh'?zh:en;}
function percent(v){return v===null||v===undefined?'—':(v*100).toFixed(2)+'%';}
function decimalRatio(text){
 const m=String(text).match(/^(\d+)(?:\.(\d{1,6}))?$/);
 if(!m)throw Error(msg('Enter a decimal percentage above 0 and at most 10 (up to 6 decimal places).','请输入大于0且不超过10的百分数，最多6位小数。'));
 const digits=m[2]||'', den=10n**BigInt(digits.length), num=BigInt(m[1]+digits);
 if(num<=0n||num>10n*den)throw Error(msg('Percentage must be above 0 and at most 10.','百分数必须大于0且不超过10。'));
 return {numerator:num.toString(),denominator:(den*100n).toString()};
}
function compare(a,b){if(!a||!b)throw Error('Exact ratio unavailable');const x=BigInt(a.numerator)*BigInt(b.denominator),y=BigInt(b.numerator)*BigInt(a.denominator);return x<y?-1:x>y?1:0;}
function interval(k,n){if(!n)return {k,n,p:null,lower:null,upper:null};const z=1.959963984540054,p=k/n,z2=z*z,c=(p+z2/(2*n))/(1+z2/n),h=z*Math.sqrt(p*(1-p)/n+z2/(4*n*n))/(1+z2/n);return {k,n,p,lower:Math.max(0,c-h),upper:Math.min(1,c+h)};}
function quantile(a,q){if(!a.length)return null;const pos=(a.length-1)*q,l=Math.floor(pos),u=Math.ceil(pos);return a[l]+(a[u]-a[l])*(pos-l);}
function describe(rows){
 const a=rows.map(d=>d.outcome.drop).sort((x,y)=>x-y),n=a.length;
 return {n,dates:rows.map(d=>d.date),mean:n?a.reduce((x,y)=>x+y,0)/n:null,median:quantile(a,.5),p90:quantile(a,.9),max:n?a[n-1]:null,
  thresholds:[['0.5',{numerator:'1',denominator:'200'}],['1',{numerator:'1',denominator:'100'}],['2',{numerator:'1',denominator:'50'}]].map(([pct,r])=>({pct,...interval(rows.filter(d=>compare(d.outcome.exact_drop,r)>=0).length,n)})),
  negative_30m_close:interval(rows.filter(d=>BigInt(d.outcome.exact_return_30m.numerator)<0n).length,n)};
}
function getExplorerSummary(pct,definition){
 const threshold=decimalRatio(pct),out={};
 for(const [symbol,days] of Object.entries(STUDY.symbols)){
  const baseline=days.filter(d=>d.definitions[definition].eligible),events=baseline.filter(d=>compare(d.definitions[definition].ratio,threshold)>0);
  out[symbol]={events:describe(events),baseline:describe(baseline),eligible:baseline.length,total:days.length,
    partial_observed_hit_dates:days.filter(d=>!d.definitions[definition].complete&&d.definitions[definition].ratio&&compare(d.definitions[definition].ratio,threshold)>0).map(d=>d.date)};
 }
 return out;
}
window.getExplorerSummary=getExplorerSummary;
function htmlTable(headers,rows){return '<div class="table-wrap"><table><thead><tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
function frequency(x){return x.k+'/'+x.n+' · '+percent(x.p)+(x.n?' ['+percent(x.lower)+', '+percent(x.upper)+']':'');}
function miniChart(stats){
 const max=Math.max(.005,...Object.values(stats).map(s=>s.events.max||0))*1.2;
 let svg='<svg viewBox="0 0 660 190" role="img" aria-label="'+msg('Largest observed opening downside by ETF','各ETF观察到的最大开盘下跌')+'">';
 Object.entries(stats).forEach(([symbol,s],i)=>{const y=22+i*54,w=(s.events.max||0)/max*460;svg+='<text x="5" y="'+(y+18)+'">'+symbol+'</text><rect x="55" y="'+y+'" width="'+w+'" height="24" fill="#176779"/><text x="'+(65+w)+'" y="'+(y+18)+'">'+percent(s.events.max)+' · n='+s.events.n+'</text>';});
 return svg+'</svg>';
}
function renderExplorer(){
 for(const option of document.getElementById('definition').options)option.textContent=STUDY.definitions[option.value][document.documentElement.lang==='zh'?1:0];
 const def=document.getElementById('definition').value,stats=getExplorerSummary(shownThreshold,def);
 document.getElementById('displayed-threshold').textContent=msg('Displayed: strictly >','当前显示：严格大于')+shownThreshold+'%';
 document.getElementById('explorer-heading').textContent=msg('Live local comparison','本地即时对照');
 let html=htmlTable([msg('ETF','ETF'),msg('Eligible days','合格日'),msg('Event n','事件n'),msg('Downside ≥0.5% · 95% interval','下探≥0.5% · 95%区间'),msg('Downside ≥1% · 95% interval','下探≥1% · 95%区间'),msg('Downside ≥2% · 95% interval','下探≥2% · 95%区间'),msg('Mean / median downside','平均／中位下探'),msg('Worst observed','最大下探')],Object.entries(stats).map(([s,x])=>[s,x.eligible+'/'+x.total,x.events.n,...x.events.thresholds.map(frequency),percent(x.events.mean)+' / '+percent(x.events.median),percent(x.events.max)]));
 html+=miniChart(stats);
 for(const [s,x] of Object.entries(stats)){
  html+='<h3>'+s+'</h3><p>'+msg('Event dates: ','事件日期：')+(x.events.dates.join(', ')||'—')+'</p>';
  if(!x.eligible)html+='<p class="notice">'+msg('No eligible days for this definition: the premarket window cannot be verified under the positive-volume rule. Conditional probabilities are unavailable; this does not mean the ETF never had a large premarket gain.','此定义没有合格日：按正成交量规则无法核验盘前窗口。条件概率不可估计；这不代表该ETF从未盘前大涨。')+'</p>';
  else if(!x.events.n)html+='<p class="notice">'+msg('No qualifying events among eligible days at this threshold. Conditional probabilities are unavailable, not zero.','此阈值下合格日中没有触发事件。条件概率不可估计，不是零。')+'</p>';
  html+=htmlTable([msg('Measure','指标'),msg('Event days','事件日'),msg('Same eligible baseline','相同合格日基线')],x.events.thresholds.map((v,i)=>[msg('Downside ≥','下探≥')+v.pct+'%',frequency(v),frequency(x.baseline.thresholds[i])]).concat([[msg('10:00 below open','10:00低于开盘'),frequency(x.events.negative_30m_close),frequency(x.baseline.negative_30m_close)],[msg('Mean / median / P90','平均／中位／P90'),[x.events.mean,x.events.median,x.events.p90].map(percent).join(' / '),[x.baseline.mean,x.baseline.median,x.baseline.p90].map(percent).join(' / ')]]));
  html+='<p class="muted">'+msg('Observed hits in incomplete premarket windows (excluded from primary denominator): ','盘前不完整窗口中的已知触发（不计入主分母）：')+(x.partial_observed_hit_dates.join(', ')||'—')+'</p>';
 }
 document.getElementById('explorer-results').innerHTML=html;
 const grid=[];
 for(const pct of STUDY.grid_pct){for(const [s,x] of Object.entries(getExplorerSummary(pct,def))){grid.push([pct+'%',s,x.events.n,x.eligible+'/'+x.total,...x.events.thresholds.map(v=>v.k+'/'+v.n+' · '+percent(v.p)),percent(x.events.mean),percent(x.events.max)]);}}
 document.getElementById('grid-heading').textContent=msg('Preset thresholds · exploratory sensitivity, not a ranked optimizer','预设阈值 · 探索性敏感度，不排序挑最优');
 document.getElementById('grid-results').innerHTML=htmlTable([msg('Gain >','涨幅>'),'ETF','n',msg('Eligible days','合格日'),'≥0.5%','≥1%','≥2%',msg('Mean downside','平均下探'),msg('Worst downside','最大下探')],grid);
}
function applyThreshold(){try{decimalRatio(document.getElementById('threshold').value);shownThreshold=document.getElementById('threshold').value;document.getElementById('threshold-error').textContent='';renderExplorer();}catch(e){document.getElementById('threshold-error').textContent=e.message;}}
window.applyThreshold=applyThreshold;
document.getElementById('download-custom').addEventListener('click',()=>{
 const definition=document.getElementById('definition').value,body={schema:'premarket-custom-derived/1',gain_threshold_pct:shownThreshold,comparison:'>',definition,window:'09:30–10:00 America/New_York',range:['2025-11-27','2026-11-27 exclusive'],exploratory:true,execution_eligible:false,fingerprints:STUDY.fingerprints,results:getExplorerSummary(shownThreshold,definition)};
 const link=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(body,null,2)],{type:'application/json'}));link.href=url;link.download='premarket-custom-'+shownThreshold+'pct-'+definition+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
document.getElementById('apply-threshold').addEventListener('click',applyThreshold);
document.getElementById('definition').addEventListener('change',renderExplorer);
for(const button of document.querySelectorAll('[data-threshold]'))button.addEventListener('click',()=>{document.getElementById('threshold').value=button.dataset.threshold;applyThreshold();});
const previousSetLanguage=window.setLanguage;
window.setLanguage=function(lang){previousSetLanguage(lang);renderExplorer();};
renderExplorer();
'''


def render_html(report: dict) -> str:
    """Keep a frozen Python reference and add an exact, offline threshold explorer."""
    html = _render_reference_html(report)
    threshold = report["config"]["premarket_threshold_pct"]
    symbols = list(report["results"])
    # The reference always identifies the Python-selected threshold separately.
    html = html.replace("QQQ / SPY", " / ".join(symbols)).replace("QQQ／SPY", "／".join(symbols))
    html = html.replace("QQQ and SPY", ", ".join(symbols)).replace("QQQ 与 SPY", "、".join(symbols))
    html = html.replace("2.50%", threshold + "%").replace("2.5%", threshold + "%")
    html = html.replace('<a href="#SPY">SPY</a>', '<a href="#SPY">SPY</a>' + (' · <a href="#DIA">DIA</a>' if "DIA" in symbols else ''))
    title_start, title_end = html.index('<title>') + len('<title>'), html.index('</title>')
    html = html[:title_start] + 'Premarket gains and opening 30-minute downside' + html[title_end:]
    header_start, header_end = html.index('<header>'), html.index('</header>') + len('</header>')
    compact_header = '<header><div class="top"><b>Alpha Trading Lab</b><div aria-label="Language"><button id="en" aria-pressed="true" onclick="setLanguage(\'en\')">English</button> <button id="zh" aria-pressed="false" onclick="setLanguage(\'zh\')">中文</button></div></div><h1>'
    compact_header += tr("Premarket gains and opening 30-minute downside", "盘前涨幅与开盘半小时下探") + '</h1><p>'
    compact_header += tr(" · ".join(symbols) + " | 2025-11-27–2026-11-26 | 250 trading sessions | today excluded", " · ".join(symbols) + " | 2025-11-27至2026-11-26 | 250个交易日 | 不含今天") + '</p><p>'
    compact_header += tr("Actual moomoo 1-minute history, raw unadjusted prices. Downside is measured from the first regular-minute open proxy to the lowest price during 09:30–10:00 ET. ETFs are analyzed separately; this is descriptive research, not an executable strategy backtest.", "使用moomoo真实1分钟历史、不复权价格。下探从首根常规分钟开盘代理价量至美东09:30—10:00最低价。各ETF分别统计；这是描述性研究，不是可执行策略回测。") + '</p></header>'
    html = html[:header_start] + compact_header + html[header_end:]
    controls = '<section id="threshold-explorer"><h2>' + tr("Adjust the premarket gain threshold", "调整盘前涨幅阈值") + '</h2><p>' + tr("QQQ tracks Nasdaq-100; SPY tracks S&P 500; DIA is the Dow Jones Industrial Average ETF. Each ETF is a separate sample.", "QQQ跟踪纳斯达克100，SPY跟踪标普500，DIA是道琼斯工业平均指数ETF。每只ETF分别统计。") + '</p>'
    controls += '<div class="control-row"><label for="threshold">' + tr("Premarket gain strictly greater than (%)", "盘前涨幅严格大于（%）") + '</label> <input id="threshold" type="number" min="0.000001" max="10" step="any" value="' + threshold + '"> <button id="apply-threshold">' + tr("Recalculate locally", "本地重新统计") + '</button> <button id="download-custom">' + tr("Download current results JSON", "下载当前结果JSON") + '</button></div><p id="threshold-error" role="alert" style="color:#a42323"></p><p id="displayed-threshold" aria-live="polite"></p>'
    controls += '<label for="definition">' + tr("Premarket observation", "盘前观察口径") + '</label> <select id="definition">' + ''.join('<option value="' + name + '">' + escape(titles[0]) + '</option>' for name, titles in DEFINITIONS.items()) + '</select>'
    controls += '<p class="muted">' + tr("Fixed times use completed-minute closes. Ever-high definitions require every positive-volume minute from 04:00 to the cutoff; incomplete windows remain unknown and observed partial hits are listed separately. The gain cutoff is independent of the 0.5% / 1% / 2% opening-downside levels.", "固定时点使用已完成分钟收盘价。曾触发口径要求04:00至截止时点每分钟均有效且正成交量；不完整窗口保留未知，已观察触发单列。盘前涨幅阈值与开盘下探0.5%／1%／2%三档相互独立。") + '</p>'
    controls += '<p>' + ''.join('<button data-threshold="' + pct + '">' + pct + '%</button> ' for pct in report["config"]["threshold_grid_pct"]) + '</p><p class="notice">' + tr("Changing thresholds is exploratory. These overlapping samples do not validate a best threshold. The 2.5% original reference is preserved; new findings require an untouched test period. Custom values use the same frozen data, no network request or training.", "调整阈值属于探索研究；这些相互重叠的样本不能验证哪个阈值最优。原2.5%对照保留，新发现需独立测试期验证。自定义数值复用同一冻结数据，不联网取数或训练。") + '</p><h3 id="explorer-heading"></h3><div id="explorer-results"></div><h3 id="grid-heading"></h3><div id="grid-results"></div></section>'
    first = html.index('</header>') + len('</header>')
    audit = html.index('<section id="audit">')
    html = html[:first] + controls + '<details id="frozen-reference"><summary>' + tr("Frozen Python reference · gain > " + threshold + "%", "冻结的Python结果 · 涨幅>" + threshold + "%") + '</summary>' + html[first:audit] + '</details>' + html[audit:]
    payload = json.dumps(_explorer_payload(report), ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace('<', '\\u003c')
    extra = '<script type="application/json" id="study-data">' + payload + '</script><script>' + EXPLORER_JS + '</script>'
    html = html.replace('</body>', extra + '</body>')
    html = html.replace('</style>', 'input,select{font:inherit;padding:8px;border:1px solid #9aafbd;border-radius:7px;max-width:100%;box-sizing:border-box}input{width:130px}.control-row{display:flex;align-items:center;flex-wrap:wrap;gap:9px}#frozen-reference{background:white;padding:20px;border-radius:12px}#frozen-reference>summary{font-weight:bold}#threshold-explorer{overflow:hidden}</style>')
    return html


def validate_captures(captures) -> tuple[list, dict, dict]:
    folders = [captures] if isinstance(captures, Path) else list(captures)
    if not folders or len(folders) > 3:
        raise ReportError("one_to_three_capture_folders_required")
    records, sources, reference = [], {}, None
    for folder in folders:
        folder = Path(folder).resolve()
        manifest, calendar, proofs = validate_capture(folder)
        if reference is not None and calendar != reference:
            raise ReportError("capture_calendars_do_not_match")
        reference = calendar
        for symbol in manifest["symbols"]:
            if symbol in sources:
                raise ReportError("duplicate_symbol_across_captures")
            sources[symbol] = (folder, manifest)
        records.append((folder, manifest, proofs))
    return records, sources, reference


def run(capture: Path | list[Path], *, premarket_threshold_pct="2.5",
        threshold_grid="0.5,1,1.5,2,2.5,3") -> tuple[Path, dict]:
    chosen_pct = threshold_pct(premarket_threshold_pct)
    grid_pct = threshold_grid_pct(threshold_grid)
    # The original 2.5% research reference is retained even for a custom grid.
    all_thresholds = tuple(sorted(set((*grid_pct, chosen_pct, Decimal("2.5")))))
    records, sources, calendar = validate_captures(capture)
    symbols = [s for s in ALLOWED_SYMBOLS if s in sources]
    engine_path = ROOT / "research" / "premarket_events.py"
    engine_raw, runner_raw = engine_path.read_bytes(), Path(__file__).read_bytes()
    sweeps = {}
    for symbol in symbols:
        folder, manifest = sources[symbol]
        sweeps[symbol] = analyze_symbol_thresholds(iter_symbol_rows(folder, manifest, symbol), symbol=symbol,
            sessions=calendar["sessions"], start=START, end_exclusive=END, bar_label="end",
            observed_at=manifest["finished_at"], require_full_rth=False, corporate_action_dates=(),
            premarket_thresholds=tuple(v / 100 for v in all_thresholds))
    chosen_key = decimal_text(chosen_pct / 100)
    results = {s: sweeps[s][chosen_key] for s in symbols}
    if engine_path.read_bytes() != engine_raw or Path(__file__).read_bytes() != runner_raw:
        raise ReportError("analysis_source_changed_during_run")
    created = datetime.now(timezone.utc)
    capture_proofs = []
    streams = {}
    for folder, manifest, proofs in records:
        checkpoints = sorted((folder / "progress").glob("*.json")) if (folder / "progress").is_dir() else []
        manifest_file = checkpoints[-1] if checkpoints else folder / "manifest.json"
        capture_proofs.append({"capture_folder": str(folder), "symbols": manifest["symbols"],
            "manifest_checkpoint": manifest_file.name, "manifest_sha256": sha256(manifest_file.read_bytes()),
            "started_at": manifest["started_at"], "finished_at": manifest["finished_at"],
            "capture_errors_preserved": manifest.get("errors", []), "verification": proofs})
        streams.update({s: {"pages": len(manifest["streams"][s]["pages"]),
                            "rows": manifest["streams"][s]["rows"]} for s in manifest["symbols"]})
    report = {"schema_version": "premarket-365-report/2", "created_at": created.isoformat(),
              "config": {"start": START, "end_exclusive": END, "natural_days": 365, "today_excluded": True,
                         "symbols": symbols, "premarket_threshold": float(chosen_pct / 100),
                         "premarket_threshold_pct": decimal_text(chosen_pct),
                         "threshold_grid_pct": [decimal_text(v) for v in grid_pct],
                         "original_reference_pct": "2.5",
                         "threshold_comparison": ">", "threshold_exploration": True,
                         "automatic_best_threshold_selection": False,
                         "drop_thresholds": [.005, .01, .02], "require_full_rth": False,
                         "bar_label": "end", "price_adjustment": "raw_unadjusted", "execution_eligible": False},
              "source": {"captures": capture_proofs, "source": "moomoo_desktop_history",
                         "complete_pagination": True,
                         "historical_delivery_clocks_verified": False,
                         "streams": streams, "verification": records[0][2]},
              "code": {"engine_sha256": sha256(engine_raw), "runner_sha256": sha256(runner_raw),
                       "python_version": sys.version}, "results": results,
              "threshold_sweep": {decimal_text(v / 100): {s: {"summary": sweeps[s][decimal_text(v / 100)]["summary"],
                 "coverage": sweeps[s][decimal_text(v / 100)]["coverage"]} for s in symbols} for v in all_thresholds}}
    daily, events = flatten_daily(results)
    for row in (*daily, *events):
        row["premarket_threshold_pct"] = decimal_text(chosen_pct)
    grid_rows = []
    for value in all_thresholds:
        for symbol in symbols:
            for definition, summary in sweeps[symbol][decimal_text(value / 100)]["summary"].items():
                event = summary["events"]
                for t in event["thresholds"]:
                    grid_rows.append({"premarket_threshold_pct": decimal_text(value), "symbol": symbol,
                        "definition": definition, "eligible_days": summary["eligible_days"], "event_n": event["n"],
                        "drop_threshold": t["drop_threshold"], **{k: t[k] for k in ("k", "n", "proportion", "lower", "upper")},
                        **event["drop_distribution"]})
    # Write only after validation and analysis have succeeded. Each run is new;
    # no latest pointer or older artifact is replaced.
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT_ROOT / created.strftime("%Y%m%dT%H%M%S%fZ")
    destination.mkdir(exist_ok=False)
    (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (destination / "daily.csv").write_text(_csv(daily), encoding="utf-8-sig")
    (destination / "events.csv").write_text(_csv(events), encoding="utf-8-sig")
    (destination / "threshold-grid.csv").write_text(_csv(grid_rows), encoding="utf-8-sig")
    (destination / "report.html").write_text(render_html(report), encoding="utf-8")
    (destination / "engine-used.py").write_bytes(engine_raw)
    (destination / "runner-used.py").write_bytes(runner_raw)
    (destination / "calendar-used.json").write_bytes((records[0][0] / "calendar.json").read_bytes())
    for index, (folder, manifest, proof) in enumerate(records):
        name = "manifest-used.json" if index == 0 else "manifest-" + "-".join(manifest["symbols"]) + "-used.json"
        (destination / name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts = {p.name: {"bytes": p.stat().st_size, "sha256": sha256(p.read_bytes())} for p in destination.iterdir() if p.is_file()}
    (destination / "artifact-hashes.json").write_text(json.dumps(artifacts, indent=2) + "\n", encoding="utf-8")
    return destination, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, action="append", help="Repeat for disjoint QQQ/SPY/DIA captures")
    parser.add_argument("--premarket-threshold-pct", default="2.5")
    parser.add_argument("--threshold-grid-pct", default=DEFAULT_GRID_PCT)
    args = parser.parse_args(argv)
    try:
        destination, report = run(args.capture or [DEFAULT_CAPTURE],
            premarket_threshold_pct=args.premarket_threshold_pct, threshold_grid=args.threshold_grid_pct)
    except (ReportError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "folder": str(destination), "html": str(destination / "report.html"),
                      "coverage": {s: r["coverage"] for s, r in report["results"].items()},
                      "event_counts": {s: {d: v["events"]["n"] for d, v in r["summary"].items()} for s, r in report["results"].items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
