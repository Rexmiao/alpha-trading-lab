"""Run the fixed free Cboe examples locally; never publish data or call a broker.

All reports, including derived tables and charts, remain in ignored state/.
Run from the repository root: python scripts/run_cboe_mm_validation.py
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.cboe_mm_sample import (  # noqa: E402
    audit_open_close_sample, audit_tbt_sample, observed_mm_change,
)
from research.dealer_methods import (  # noqa: E402
    DEFAULT_CAPABILITIES, initial_inventory_sensitivity, method_catalog,
)
from hf_space.gex_scenarios import make_teaching_gex_contracts, run_gex_scenarios  # noqa: E402

OUTPUT_ROOT = ROOT / "state" / "cboe-mm-validation"
SYMBOLS = ("SPY", "QQQ")
MOOMOO_CAPTURE_DATE = "2026-11-27"
MOOMOO_AUDIT_ID = "dealer-inventory-audit/20261127T170839607943Z"
SCRIPT_VERSION = "cboe-mm-validation-v1"


def _e(value):
    return html.escape(str(value), quote=True)


def _sign(value):
    return (value > 0) - (value < 0)


def compare_contract_samples(tbt_audits, open_close_audits):
    """Compare exact source-series keys, not inferred counterparts or true q.

    Both supplied samples can be incomplete. Opposite signs are sampling/scope
    counterexamples; the function deliberately supplies no accuracy score.
    """
    for audit in [*tbt_audits, *open_close_audits]:
        if audit.get("contract_summaries_truncated"):
            raise ValueError("contract_summaries_truncated")
    tbt = {}
    eod = {}
    dates_tbt, dates_eod = set(), set()
    for audits, target, dates in ((tbt_audits, tbt, dates_tbt), (open_close_audits, eod, dates_eod)):
        for audit in audits:
            dates.update(audit["trading_dates"])
            for row in audit["contract_summaries"]:
                key = row["contract_key"]
                if key in target:
                    raise ValueError("duplicate_contract_scope")
                target[key] = row
    if len(dates_tbt) != 1 or dates_tbt != dates_eod:
        raise ValueError("same_single_trading_date_required")
    counts = Counter()
    examples = []
    by_symbol = {}
    root_matches_underlying = Counter()
    different_root_examples = []
    for key in sorted(tbt.keys() & eod.keys()):
        left, right = tbt[key], eod[key]
        if left["mm_buy_contracts"] + left["mm_sell_contracts"] == 0:
            continue
        a = left["sampled_observed_mm_signed_contracts"]
        b = right["sampled_observed_mm_signed_contracts"]
        category = ("strict_opposite_nonzero" if _sign(a) * _sign(b) == -1 else
                    "same_nonzero_sign" if _sign(a) == _sign(b) != 0 else
                    "both_zero" if a == b == 0 else "tbt_zero_only" if a == 0 else "eod_zero_only")
        counts[category] += 1
        by_symbol.setdefault(left["underlying"], Counter())[category] += 1
        source_root = key.split("|")[1]
        if source_root == left["underlying"]:
            root_matches_underlying[category] += 1
        else:
            different_root_examples.append({"contract_key": key, "underlying": left["underlying"],
                                            "source_option_root": source_root,
                                            "tbt_sample_signed_side_sum": a, "eod_sample_signed_side_sum": b,
                                            "multiplier": None, "deliverable_verified": False})
        if category == "strict_opposite_nonzero":
            examples.append({"contract_key": key, "underlying": left["underlying"],
                             "tbt_sample_mm_buys": left["mm_buy_contracts"],
                             "tbt_sample_mm_sells": left["mm_sell_contracts"],
                             "tbt_sample_signed_side_sum": a,
                             "eod_sample_mm_buys": right["mm_buy_contracts"],
                             "eod_sample_mm_sells": right["mm_sell_contracts"],
                             "eod_sample_signed_side_sum": b,
                             "eod_snapshot_source_local": right["snapshot_source_local"],
                             "inventory_q": None, "full_interval_delta_q": None})
    chosen = next((row for row in examples if row["contract_key"] == "C1|SPY|2025-03-28|P|558"), None)
    return {
        "join_kind": "same_date_exact_source_series_key_not_inventory_truth",
        "trading_date": next(iter(dates_tbt)), "venue": "C1",
        "overlapping_contracts_with_observed_tbt_MM_sides": sum(counts.values()),
        "sign_comparison_counts": dict(sorted(counts.items())),
        "by_underlying": {u: dict(sorted(v.items())) for u, v in sorted(by_symbol.items())},
        "root_equals_underlying_comparison_counts": dict(sorted(root_matches_underlying.items())),
        "root_equals_underlying_comparison_contracts": sum(root_matches_underlying.values()),
        "different_root_overlap_examples": different_root_examples,
        "underlying_filter_includes_distinct_option_roots": True,
        "sign_reversal_examples": examples[:20], "selected_failure_example": chosen,
        "sampling_mechanisms_comparable": False, "eod_completeness_verified": False,
        "classification_accuracy": None, "inventory_direction_accuracy": None,
        "interpretation": "Partial samples can reverse an observed signed-flow sum; neither sample establishes q.",
    }


def build_report(tbt_path, open_close_path, *, created_at=None):
    created_at = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # Separate all-file counts from selected-symbol derived displays. Summary
    # caps do not truncate the parser's input or its aggregate counters.
    whole_tbt = audit_tbt_sample(tbt_path, max_contract_rows=0)
    whole_oc = {kind: audit_open_close_sample(open_close_path, kind=kind, max_contract_rows=0)
                for kind in ("eod", "10m", "1m")}
    tbt = {u: audit_tbt_sample(tbt_path, underlyings=[u], max_contract_rows=2000) for u in SYMBOLS}
    eod = {u: audit_open_close_sample(open_close_path, kind="eod", underlyings=[u], max_contract_rows=2000)
           for u in SYMBOLS}
    comparison = compare_contract_samples(list(tbt.values()), list(eod.values()))
    # A separately declared hypothetical q0 sensitivity illustrates why buys
    # cannot establish current long/short. Missing activity is set to zero only
    # in the explicit scenario, not estimated or quietly filled in observed q.
    example = comparison["selected_failure_example"]
    sensitivities = []
    if example:
        scope = comparison["trading_date"] + "/" + example["contract_key"] + "/observed_sides_only"
        for label, lower, upper in (("short_initial_scenario", -200, -100),
                                    ("uncertain_initial_scenario", -100, 100),
                                    ("long_initial_scenario", 0, 100)):
            scenario = initial_inventory_sensitivity(
                example["tbt_sample_signed_side_sum"], q0_lower=lower, q0_upper=upper,
                inventory_scope=scope, flow_scope=scope, assume_no_other_changes=True)
            sensitivities.append({"label": label, **scenario})
    toy = run_gex_scenarios(
        make_teaching_gex_contracts(), spot=100., price_grid=[float(x) for x in range(80, 121)],
        complete_chain_verified=True, source_kind="synthetic_demo")
    caps = DEFAULT_CAPABILITIES | {"mm_capacity_sample", "contract_identity", "execution_ids", "trade_quantity"}
    sample_dates = set(whole_tbt["trading_dates"])
    return {
        "schema_version": SCRIPT_VERSION, "created_at": created_at,
        "purpose": "local_free_sample_capacity_and_accounting_validation",
        "report_is_public": False, "public_distribution_rights_verified": False,
        "inventory_q": None, "full_interval_delta_q": None, "net_inventory_gex": None,
        "calibrated_mm_probabilities": None, "execution_eligible": False,
        "lineage": {"tbt_raw_sha256": whole_tbt["raw_sha256"],
                    "open_close_raw_sha256": whole_oc["eod"]["raw_sha256"],
                    "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "core_sha256": hashlib.sha256((ROOT / "research/cboe_mm_sample.py").read_bytes()).hexdigest(),
                    "catalog_sha256": hashlib.sha256((ROOT / "research/dealer_methods.py").read_bytes()).hexdigest(),
                    "python": sys.version.split()[0], "sample_download_received_at": None,
                    "report_generated_at_is_historical_available_at": False},
        "whole_file": {"tbt": whole_tbt, "open_close": whole_oc},
        "selected_symbols": list(SYMBOLS), "selected_tbt": tbt, "selected_eod": eod,
        "same_day_sample_comparison": comparison,
        "declared_q0_sensitivity": sensitivities,
        "accounting_checks": {"buy_to_close_increases_net_q_by_3": observed_mm_change(3, 0),
                              "sell_to_close_decreases_net_q_by_4": observed_mm_change(0, 4),
                              "both_MM_same_group_cancel": observed_mm_change(5, 5),
                              "source_kind": "declared_accounting_examples_not_market_observations"},
        "methods": {"en": method_catalog("en", caps), "zh": method_catalog("zh", caps)},
        "teaching_gex_scenarios": toy,
        "moomoo_alignment": {"moomoo_capture_date": MOOMOO_CAPTURE_DATE,
                             "moomoo_audit_id": MOOMOO_AUDIT_ID,
                             "cboe_sample_dates": sorted(sample_dates),
                             "overlapping_capture_dates": sorted(sample_dates & {MOOMOO_CAPTURE_DATE}),
                             "same_date_matched_trade_labels": 0,
                             "historical_Greeks_join_performed": False,
                             "rejection_reasons": ["different_capture_dates", "moomoo_execution_venue_missing",
                                                   "cross_vendor_execution_id_unverified", "historical_Greeks_not_available"],
                             "next_design": "Use capacity labels for same-scope flow validation; join contemporaneous moomoo Greeks only after time/contract/units acceptance."},
        "limitations": ["observed_MM_sides_not_full_executions", "partial_sample_not_complete_interval_delta_q",
                        "unknown_initial_inventory", "single_venue_C1", "sample_net_sign_not_current_inventory_sign",
                        "no_statistical_accuracy_or_incremental_alpha_claim", "teaching_curves_are_separate_synthetic_inputs",
                        "no_network_no_broker_no_paid_data_no_public_upload"],
    }


def _table(headers, rows):
    return "<div class='scroll'><table><thead><tr>" + "".join(f"<th>{_e(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join(f"<td>{_e(v)}</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table></div>"


def _flow_svg(rows, language):
    zh = language == "zh"
    width, height = 900, max(180, len(rows) * 66 + 45)
    maximum = max((max(r["mm_buy_contracts"], r["mm_sell_contracts"]) for r in rows), default=1) or 1
    parts = [f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{'抽样MM买卖数量' if zh else 'Observed sampled MM buys and sells'}'>"]
    for n, row in enumerate(rows):
        y = 35 + n * 66
        label = f"{row['underlying']} {row['call_put']}"
        parts.append(f"<text x='8' y='{y+12}'>{_e(label)}</text>")
        for dy, field, color in ((0, "mm_buy_contracts", "#067a79"), (22, "mm_sell_contracts", "#c86636")):
            value = row[field]
            bar_width = 600 * value / maximum
            parts.append(f"<rect x='112' y='{y+dy}' width='{bar_width:.3f}' height='17' rx='3' fill='{color}'/><text x='{122+bar_width:.3f}' y='{y+dy+14}'>{value:,}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _gex_svg(toy, language):
    models = toy["models"]
    colors = ("#1769aa", "#0a7d71", "#d98d10", "#8360a6", "#c7475f")
    maximum = max(abs(p["gex"]) for model in models.values() for p in model["curve"]) or 1
    parts = ["<svg viewBox='0 0 900 390' role='img' aria-label='Synthetic teaching GEX scenarios'>",
             "<line x1='80' y1='170' x2='850' y2='170' stroke='#9caec0'/>"]
    for i, (key, model) in enumerate(models.items()):
        pts = " ".join(f"{80+770*(p['spot']-80)/40:.3f},{170-145*p['gex']/maximum:.3f}" for p in model["curve"])
        dash = " stroke-dasharray='7 5'" if i >= 3 else ""
        parts.append(f"<polyline points='{pts}' fill='none' stroke='{colors[i]}' stroke-width='2.2'{dash}/>")
    for price in (80, 90, 100, 110, 120):
        x = 80 + 770 * (price - 80) / 40
        parts.append(f"<text x='{x}' y='342' text-anchor='middle'>{price}</text>")
    parts.append(f"<text x='7' y='24'>{maximum:,.0f}</text><text x='22' y='174'>0</text><text x='7' y='320'>{-maximum:,.0f}</text>")
    parts.append(f"<text x='450' y='380' text-anchor='middle'>{'假设股价 · TOY' if language=='zh' else 'Hypothetical spot · TOY'}</text></svg>")
    return "".join(parts)


def _language_section(report, language):
    zh = language == "zh"
    t = lambda en, cn: cn if zh else en
    whole = report["whole_file"]["tbt"]
    flows = [row for u in SYMBOLS for row in report["selected_tbt"][u]["underlying_call_put"]]
    comparison = report["same_day_sample_comparison"]
    sample_counts = [[u, report["selected_tbt"][u]["side_records"], report["selected_tbt"][u]["option_side_records"],
                      report["selected_tbt"][u]["observed_totals"]["mm_buy_contracts"],
                      report["selected_tbt"][u]["observed_totals"]["mm_sell_contracts"],
                      report["selected_tbt"][u]["observed_totals"]["sampled_observed_mm_signed_contracts"]] for u in SYMBOLS]
    quote_rows = [[key, value, whole.get("mm_quote_position_contracts", {}).get(key, 0)]
                  for key, value in sorted(whole.get("mm_quote_position_side_records", {}).items())]
    p = [f"<section data-lang='{language}'>",
         f"<h1>{t('MM side and inventory-change research', 'MM买卖侧与库存变化研究')}</h1>",
         f"<p class='lead'>{t('Local validation using fixed free Cboe samples. No paid feed, network request or brokerage action.', '使用固定免费Cboe样本的本机核验。无付费数据、联网请求或券商操作。')}</p>",
         f"<div class='warning'>{t('SAMPLED_CAPACITY_ONLY · Actual q = unknown · Full-interval Δq = unknown · Real net GEX = unknown. Exchange capacity labels are observed on sampled sides; the full position book is not observed.', 'SAMPLED_CAPACITY_ONLY · 实际q未知 · 完整区间Δq未知 · 真实净GEX未知。观测到的是部分参与侧的交易所分类，不是完整持仓账本。')}</div>",
         f"<h2>{t('1. Verified inputs and observed MM sides', '1. 已核输入与观测MM侧')}</h2>",
         f"<p>{t('C1 sample trading date: 2025-03-28. Whole ZIP: ', 'C1样本交易日：2025-03-28。整个ZIP：')}{whole['side_records']:,} {t('side records, ', '侧记录，其中')}{whole['option_side_records']:,} {t('valid C/P option-side records; ', '条有效C/P期权侧；隔离')}{whole['quarantined_instrument_side_records']:,} {t('unverified instrument sides quarantined.', '条未核instrument侧。')}</p>",
         _table([t('Underlying','标的'),t('All sides','全部侧'),t('Option sides','期权侧'),t('MM buys','MM买数量'),t('MM sells','MM卖数量'),t('Sample signed sum','抽样签名和')], sample_counts),
         f"<p class='legend'><b style='color:#067a79'>● {t('MM buys', 'MM买')}</b>　<b style='color:#c86636'>● {t('MM sells', 'MM卖')}</b> · {t('Contract quantity, valid C/P option rows only.', '数量口径，仅有效C/P期权侧。')}</p>",
         _flow_svg(flows, language),
         f"<p>{t('MM buys increase long-minus-short even when closing shorts; MM sells decrease it even when closing longs. MM on both sides cancels within the defined group. A missing side remains unknown.', 'MM买入增加多减空，买平亦然；MM卖出减少多减空，卖平亦然。同群体MM双侧相抵，缺失对侧保持未知。')}</p>",
         f"<h3>{t('MM identity and trade location in the quote are different observations', 'MM身份与成交在报价中的位置是不同观测')}</h3>",
         _table([t('Observed MM side / quote location','观测MM侧／报价位置'),t('Side records','侧记录数'),t('Contract quantity','合约数量')], quote_rows),
         f"<p>{t('Whole-file valid C/P MM rows; B/S means the observed MM side. Quote locations use strictly positive, nonlocked, noncrossed NBBO. Invalid quotes are retained as a separate count. This describes quote position, not independently verified aggressor direction or classification accuracy.', '范围为全文件有效C/P MM侧；B/S是已观测MM买卖侧。报价位置只用严格正价、非锁定、非交叉NBBO，无效报价另计。这是报价位置描述，不是独立验证的主动方或分类准确率。')}</p>",
         f"<h2>{t('2. Failure cases: partial samples can reverse the flow sign', '2. 失败案例：不同抽样可以翻转净流符号')}</h2>",
         f"<p>{t('Exact same-day C1 series overlap with observed TBT MM sides: ', '同日C1精确合约重叠且TBT观测到MM侧：')}{comparison['overlapping_contracts_with_observed_tbt_MM_sides']:,}. {t('Opposite nonzero signs: ', '非零异号：')}{comparison['sign_comparison_counts'].get('strict_opposite_nonzero',0)}. {t('This is a sample-comparison diagnostic, not an error rate against complete truth. EOD sample completeness and historical first availability are unverified.', '这是样本差异诊断，不是对完整真值的错误率。EOD样本完整性和历史首次可得时间未核。')}</p>"]
    p.append(f"<p>{t('Filtering by underlying also includes distinct original roots. The root=underlying subset has ', '按标的筛选也包含不同原始option root。root等于underlying的子集有')}{comparison['root_equals_underlying_comparison_contracts']} {t('overlapping contracts; ', '个重叠合约；另有')}{len(comparison['different_root_overlap_examples'])} {t('additional different-root contracts remain separate. Their deliverable and multiplier are unknown; no standard 100 multiplier is inserted.', '个不同root合约单独保留。其交付物与乘数未知，不强填标准100。')}</p>")
    ex = comparison["selected_failure_example"]
    if ex:
        p.extend([_table([t('Contract','合约'),t('TBT sampled buys/sells/net','TBT抽样买/卖/净'),t('Provided EOD buys/sells/net','所给EOD买/卖/净')], [[ex['contract_key'], f"{ex['tbt_sample_mm_buys']} / {ex['tbt_sample_mm_sells']} / {ex['tbt_sample_signed_side_sum']:+}", f"{ex['eod_sample_mm_buys']} / {ex['eod_sample_mm_sells']} / {ex['eod_sample_signed_side_sum']:+}"]]),
                  f"<p>{t('No sample expansion is applied. Neither net flow establishes whether old inventory was long or short.', '不放大抽样量；两种净流都不能确定旧库存是净多还是净空。')}</p>"])
    p.extend([f"<h2>{t('3. Initial-inventory sensitivity', '3. 初始库存敏感性')}</h2>",
              f"<p>{t('Illustrative q0 bounds below are manually declared scenarios. Only this conditional arithmetic assumes no other missing flows or adjustments; it is not a confidence interval. Actual q remains null.', '以下q0范围是手动声明的示意情景。仅该条件算术假设没有其他缺失流和调整，不是置信区间；实际q保持null。')}</p>",
              _table([t('Declared q0 range','声明q0范围'),t('Observed sample change','观测样本变化'),t('Conditional endpoints','条件端点'),t('Scenario sign','情景符号')], [[f"[{r['q0_lower']}, {r['q0_upper']}]",r['declared_signed_change'],f"[{r['scenario_lower']}, {r['scenario_upper']}]",r['scenario_direction']] for r in report['declared_q0_sensitivity']]),
              f"<h2>{t('4. Method comparison and data gates', '4. 方法对照与数据门槛')}</h2>",
              _table([t('Method','方法'),t('Status','状态'),t('Interpretation and limits','解释与边界')], [[r['label'],r['status_label'],r['description']+' '+r['limitations'][0]] for r in report['methods'][language]]),
              f"<h2>{t('5. Separate teaching GEX curves', '5. 独立教学GEX曲线')}</h2>",
              f"<div class='warning'>{t('SYNTHETIC_DEMO · Fictional TOY chain, spot 100. No Cboe sample quantity, current moomoo Greek or real option position is used in these curves.', 'SYNTHETIC_DEMO · 虚构TOY链，股价100。以下曲线不使用Cboe抽样数量、当前moomoo Greeks或真实期权持仓。')}</div>",
              t("<p class='legend'><span style='color:#1769aa'>● fixed Call+/Put−</span>　<span style='color:#0a7d71'>● prior</span>　<span style='color:#d98d10'>● unsigned</span>　<span style='color:#8360a6'>┄ all long</span>　<span style='color:#c7475f'>┄ all short</span></p>",
                "<p class='legend'><span style='color:#1769aa'>● 固定Call正/Put负</span>　<span style='color:#0a7d71'>● 库存先验</span>　<span style='color:#d98d10'>● 无符号</span>　<span style='color:#8360a6'>┄ 全多</span>　<span style='color:#c7475f'>┄ 全空</span></p>"),
              _gex_svg(report['teaching_gex_scenarios'], language),
              _table([t('Teaching scenario','教学情景'),t('Current value / 1% spot move','当前值/标的变动1%')], [[key,f"{model['current_gex']:,.2f}"] for key,model in report['teaching_gex_scenarios']['models'].items()]),
              f"<p>{t('The five curves are fixed Call+/Put−, uncalibrated inventory prior, unsigned concentration, all-long and all-short stress. Extremes are not equally likely scenarios. Negative Gamma does not itself forecast falling prices.', '五曲线为固定Call正/Put负、未校准库存先验、无符号集中度、全多与全空压力。极端情景不表示同等概率；负Gamma本身不预测下跌。')}</p>",
              f"<h2>{t('6. How moomoo can help next', '6. 下一步如何配合moomoo')}</h2>",
              f"<p>{t('Existing moomoo capture: 2026-11-27; Cboe sample: 2025-03-28. Same-date trade-label matches = 0. Do not splice current Greeks onto old prints. moomoo venue/exec-ID matching and quote timestamps remain unverified.', '现有moomoo采集为2026-11-27，Cboe样本为2025-03-28；同日逐笔标签匹配=0。不拼今天Greeks与旧成交；moomoo执行场所/跨源ID与报价时点尚待验证。')}</p>",
              f"<p>{t('First validate same-scope capacity flow. With contemporaneous, contract-matched Greeks, the arithmetic 0.01 × S² × M × Gamma × Δq gives a change contribution. Complete net GEX additionally needs initial inventory, missing venues and nontrade adjustments. Predictive value requires a separate time-held-out experiment.', '先验证同范围分类流。具备同期同合约Greeks时，0.01×S²×M×Gamma×Δq可给出变化贡献；完整净GEX另需初仓、缺失场所和非成交调整。预测价值需单独的时间留出实验。')}</p>",
              f"<p class='muted'>{t('Local research only. Derived output also remains private until external-display licensing is resolved. No accuracy, calibrated probability, incremental alpha or trade decision is claimed.', '仅本机研究。派生结果在外发许可核清前同样保持私有。没有声称准确率、校准概率、增量alpha或交易判断。')}</p>",
              "</section>"])
    return "".join(p)


def render_html(report):
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Local MM Capacity Research</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f6f9;color:#19314b;font:16px/1.6 system-ui,Segoe UI,sans-serif}main{max-width:1120px;margin:auto;padding:28px}nav{display:flex;justify-content:space-between;align-items:center;gap:16px}button{background:white;color:#19314b;border:1px solid #9baec0;border-radius:8px;padding:9px 16px;cursor:pointer}h1{font-size:34px;line-height:1.25}h2{margin-top:40px;font-size:23px}.lead{font-size:18px}.warning{padding:18px;background:#fff3d7;border-left:5px solid #cb8a19;border-radius:7px}.muted{color:#617083}.scroll{overflow-x:auto;margin:16px 0}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #dce5ec}th{background:#e9f0f5}svg{width:100%;height:auto;background:white;border:1px solid #dce5ec;border-radius:8px}svg text{fill:#19314b;font:14px system-ui,sans-serif}.legend{font-size:14px}body[data-language=en] [data-lang=zh],body[data-language=zh] [data-lang=en]{display:none}@media(max-width:600px){main{padding:16px}h1{font-size:27px}td,th{padding:9px;font-size:14px}}
</style></head><body data-language="en"><main><nav><b>Alpha Trading Lab · LOCAL / PRIVATE</b><div><button type="button" onclick="setLanguage('en')">English</button> <button type="button" onclick="setLanguage('zh')">中文</button></div></nav>""" + _language_section(report, "en") + _language_section(report, "zh") + """</main><script>function setLanguage(v){if(v!=='en'&&v!=='zh')return;document.body.dataset.language=v;document.documentElement.lang=v;}</script></body></html>"""


def write_report(report, output_root=OUTPUT_ROOT):
    allowed = OUTPUT_ROOT.resolve()
    target_root = Path(output_root).resolve()
    if target_root != allowed and allowed not in target_root.parents:
        raise ValueError("derived_output_must_remain_in_private_state")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = target_root / stamp
    target.mkdir(parents=True, exist_ok=False)
    json_path, html_path = target / "report.json", target / "report.html"
    with json_path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, allow_nan=False, indent=2)
        f.write("\n")
    with html_path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(render_html(report))
    manifest = {"schema_version": SCRIPT_VERSION, "files": {
        p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
        for p in (json_path, html_path)}, "public_distribution_rights_verified": False}
    with (target / "manifest.json").open("x", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tbt", type=Path, default=ROOT / "state/mm-data-sources/cboe-samples/tbt_289.zip")
    parser.add_argument("--open-close", type=Path, default=ROOT / "state/mm-data-sources/cboe-samples/openclose_218.zip")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    report = build_report(args.tbt, args.open_close)
    target = write_report(report, args.output_root)
    print(json.dumps({"status": "completed_local_private_research", "output_dir": str(target),
                      "html": str(target / "report.html"),
                      "whole_file_side_records": report["whole_file"]["tbt"]["side_records"],
                      "valid_option_side_records": report["whole_file"]["tbt"]["option_side_records"],
                      "sample_sign_comparison": report["same_day_sample_comparison"]["sign_comparison_counts"],
                      "inventory_q": None, "same_date_moomoo_labels": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
