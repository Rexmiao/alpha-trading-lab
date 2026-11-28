"""Explicit-run UI for frozen, public derived premarket event statistics."""
from __future__ import annotations

import copy
import json

import pandas as pd
import streamlit as st

from hf_space import ui_theme as ui

from hf_space.premarket import PremarketReferenceError, analyze_reference, load_reference


DEFINITIONS = {
    "fixed_0925": ("09:25 已完成分钟收盘价", "09:25 completed-minute close"),
    "fixed_0929": ("09:29 已完成分钟收盘价", "09:29 completed-minute close"),
    "ever_before_0925": ("04:00 至 09:25 期间曾超过", "Any premarket high through 09:25"),
    "ever_before_open": ("04:00 至 09:30 期间曾超过", "Any premarket high through 09:30"),
}


def _input(kind, key, default, label, **kwargs):
    """Keep form values across translated widgets and leaving the study page."""
    memory = "_saved_" + key
    if key in st.session_state:
        st.session_state[memory] = copy.deepcopy(st.session_state[key])
    if memory not in st.session_state:
        st.session_state[memory] = copy.deepcopy(default)
    st.session_state[key] = copy.deepcopy(st.session_state[memory])
    return getattr(st, kind)(label, key=key, **kwargs)


def _pct(value):
    return "—" if value is None else f"{value * 100:.3f}%"


def _frequency(value):
    if not value["n"]:
        return "0/0 · —"
    return (f"{value['k']}/{value['n']} · {_pct(value['proportion'])} "
            f"[{_pct(value['lower'])}, {_pct(value['upper'])}]")


def _frame(rows):
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _status(entry, tr):
    if not entry["eligible_days"]:
        return "warn", tr("不可估计 · 覆盖不足", "Not estimable · insufficient coverage")
    if not entry["events"]["n"]:
        return "info", tr("当前阈值无事件", "No events at this threshold")
    if entry["events"]["n"] < 10:
        return "warn", tr("小样本", "Small sample")
    return "ok", tr("有事件样本", "Events observed")


def _summary_cards(results, tr):
    """One card per ETF: sample counts first, then the downside distribution."""
    columns = st.columns(len(results)) if results else []
    for column, (symbol, entry) in zip(columns, results.items()):
        event = entry["events"]
        with column, st.container(border=True, key=f"premarket_card_{symbol}"):
            st.markdown(f"**{symbol}**")
            ui.badges([_status(entry, tr)])
            st.markdown("<div class='alpha-kpis'>"
                        f"<div><span>{tr('事件样本数', 'Event n')}</span><b>{event['n']}</b></div>"
                        f"<div><span>{tr('合格交易日', 'Eligible sessions')}</span><b>{entry['eligible_days']}/{entry['total_days']}</b></div>"
                        "</div>", unsafe_allow_html=True)
            stats = ((tr("平均最大下探", "Mean max downside"), event["mean"]),
                     (tr("中位最大下探", "Median max downside"), event["median"]),
                     (tr("P90最大下探", "P90 max downside"), event["p90"]),
                     (tr("最大观察下探", "Worst observed"), event["max"]))
            st.markdown("<div class='alpha-stats'>" + "".join(
                f"<div><span>{label}</span><b>{_pct(value)}</b></div>" for label, value in stats) + "</div>",
                unsafe_allow_html=True)
            if not entry["eligible_days"]:
                st.info(tr(f"{symbol}：按当前规则没有合格观察日，条件概率无法估计。整段盘前要求每一分钟都有有效正成交量；这不表示从未盘前大涨。",
                           f"{symbol}: no eligible observations under this definition, so conditional probabilities are unavailable. Full premarket windows require every minute to have valid positive volume; this does not mean large premarket gains never occurred."))
                hits = entry["partial_observed_hit_dates"]
                if hits:
                    st.caption(tr(f"不完整窗口中已观察到 {len(hits)} 次触发（不计入主概率），见“全部事件明细”。",
                                  f"{len(hits)} hit(s) observed in incomplete windows (excluded from primary probabilities); see All event days."))
            elif not event["n"]:
                st.info(tr(f"{symbol}：当前阈值下没有触发事件，条件概率无法估计，不是0%。",
                           f"{symbol}: no qualifying events at this threshold. Conditional probabilities are unavailable, not 0%."))


def _render_results(result, context, tr, *, current=None):
    ui.run_bar(tr, [", ".join(context["symbols"]), f">{context['threshold_pct']}%", tr(*DEFINITIONS[context["definition"]])],
               changed=current is not None and current != context)
    st.warning(tr("样本可能很少；这些是历史频率，不是下一次事件的可靠概率。更换阈值属于探索比较，不能据此选出已验证的最优交易条件。",
                  "Samples can be small. These are historical frequencies, not reliable probabilities for the next event. Changing thresholds is exploratory and does not establish an optimal trading rule."))
    results = result["results"]
    _summary_cards(results, tr)
    tabs = st.tabs([tr("样本与下探", "Samples & downside"), tr("全部事件明细", "All event days"),
                    tr("定义与来源", "Definitions & source")])
    with tabs[0]:
        rows = []
        for symbol, entry in results.items():
            event = entry["events"]
            rows.append({"ETF": symbol, tr("合格交易日", "Eligible sessions"): f"{entry['eligible_days']}/{entry['total_days']}",
                         tr("事件样本数", "Event n"): event["n"],
                         tr("平均最大下探", "Mean maximum downside"): _pct(event["mean"]),
                         tr("中位最大下探", "Median maximum downside"): _pct(event["median"]),
                         tr("P90最大下探", "P90 maximum downside"): _pct(event["p90"]),
                         tr("最大观察下探", "Worst observed downside"): _pct(event["max"]),
                         tr("状态", "Status"): _status(entry, tr)[1]})
        _frame(rows)
        chart_rows = [(symbol, entry["events"]) for symbol, entry in results.items() if entry["events"]["n"]]
        if chart_rows:
            import plotly.graph_objects as go
            figure = go.Figure(go.Bar(x=[symbol for symbol, _ in chart_rows],
                y=[event["max"] * 100 for _, event in chart_rows],
                text=[f"{_pct(event['max'])} · n={event['n']}" for _, event in chart_rows],
                textposition="outside", marker_color="#176779"))
            figure.update_layout(title=tr("各ETF观察到的最大开盘半小时下探", "Largest observed opening 30-minute downside"),
                xaxis_title="ETF", yaxis_title=tr("相对开盘的下探（%）", "Downside from opening-minute open (%)"),
                margin=dict(t=65, b=30), height=340)
            st.plotly_chart(figure, use_container_width=True)
        with st.expander(tr("下探频率与相同合格日基线", "Downside frequencies & same-eligible-day baseline")):
            rows = []
            for symbol, entry in results.items():
                for event, baseline in zip(entry["events"]["thresholds"], entry["baseline_same_eligible_days"]["thresholds"]):
                    rows.append({"ETF": symbol, tr("下探至少", "Downside at least"): _pct(event["drop_threshold"]),
                                 tr("事件日频率及95%参考区间", "Event frequency & 95% reference interval"): _frequency(event),
                                 tr("同覆盖基线及95%参考区间", "Matched-coverage baseline & 95% reference interval"): _frequency(baseline)})
            _frame(rows)
            st.caption(tr("Wilson区间采用近似独立交易日假设；没有修正市场状态变化或多阈值检验。各ETF同日发生的事件不作为独立市场冲击合并。",
                          "Wilson intervals assume approximately independent trading dates and do not adjust for regime changes or multiple thresholds. Same-day events across ETFs are not pooled as independent market shocks."))
    with tabs[1]:
        rows = []
        for symbol, entry in results.items():
            for event in entry["event_rows"]:
                row = {"ETF": symbol, tr("日期", "Date"): event["date"],
                       tr("盘前涨幅", "Premarket gain"): _pct(event["premarket_return"]),
                       tr("首30分钟最大下探", "30-minute maximum downside"): _pct(event["max_drop_from_open"]),
                       tr("10:00相对开盘收益", "10:00 return from open"): _pct(event["return_30m"])}
                for window in event.get("windows", []):
                    row[tr(f"首{window['minutes']}分钟下探", f"First {window['minutes']}m downside")] = _pct(window["max_drop_from_open"])
                rows.append(row)
        if rows:
            _frame(rows)
        else:
            st.caption(tr("当前条件没有可列出的合格事件。", "There are no qualifying event days for these settings."))
        st.caption(tr("所有符合条件事件都保留，包括未明显回落的案例。", "All qualifying events are retained, including cases without a substantial decline."))
        for symbol, entry in results.items():
            dates = entry["partial_observed_hit_dates"]
            if dates:
                st.write(tr(f"{symbol} 不完整盘前窗口中已观察到触发（不计入主概率）：", f"{symbol} observed hits in incomplete premarket windows (excluded from primary probabilities): ")
                         + ", ".join(dates))
    with tabs[2]:
        st.write(tr("盘前涨幅相对前一真实交易日的常规收盘价。固定09:25／09:29使用当时已完成的分钟收盘价；‘曾超过’使用04:00至截止时点的最高成交价，并保留严格完整窗口规则。",
                    "Premarket gains are measured against the previous actual session's regular close. Fixed 09:25 / 09:29 observations use completed-minute closes. Ever-high definitions use the highest traded price from 04:00 to the cutoff, under the strict complete-window rule."))
        st.latex(r"D_{30}=\max\left(0,1-\frac{\min Low_{[09:30,10:00)}}{Open_{09:30}}\right)")
        st.write(tr("开盘价是首根常规分钟K线的open代理；最大下探不是10:00收盘收益，也不是已成交的做空利润。历史API实际交付时刻和公司行动未完整重建，未计点差、滑点和费用。",
                    "The open is the first regular-minute OHLC open proxy. Maximum downside is distinct from the 10:00 close return and from realizable short-sale profit. Historical API delivery times and corporate actions were not fully reconstructed; spreads, slippage and fees are excluded."))
        st.json(result["provenance"])
    st.download_button(tr("下载研究结果JSON", "Download research results JSON"),
        data=st.session_state["premarket_result_json"], file_name="premarket-opening-downside-results.json",
        mime="application/json", key="premarket_download", icon=":material/download:")


def render_premarket_page(tr):
    st.markdown("<div class='alpha-eyebrow'>" + tr(*ui.STUDIES["premarket"]["group"]) + "</div>", unsafe_allow_html=True)
    st.title(tr("盘前涨幅与开盘半小时下探", "Premarket Gains & Opening Downside"))
    ui.study_meta(tr, "premarket")
    st.write(tr("比较QQQ、SPY与道指ETF DIA：盘前上涨超过指定阈值后，开盘半小时内有多少样本、最大下探多少。",
                "Compare QQQ, SPY and Dow ETF DIA: after a chosen premarket gain, how many historical events occurred and how far did prices fall in the first 30 minutes?"))
    st.caption(tr("冻结区间2025-11-27至2026-11-26，不含2026-11-27当天，共250个交易日。来源为已核验moomoo 1分钟历史行情的派生统计；不是实时行情。",
                  "Frozen period: 2025-11-27 through 2026-11-26, excluding 2026-11-27; 250 trading sessions. Derived statistics from verified moomoo 1-minute history, not a live feed."))
    with st.form("premarket_settings"):
        st.markdown("**" + tr("研究参数", "Study settings") + "**")
        etf_column, threshold_column, definition_column = st.columns([4, 3, 4])
        with etf_column:
            symbols = _input("multiselect", "premarket_symbols", ["QQQ", "SPY", "DIA"], tr("ETF选择", "ETFs"), options=["QQQ", "SPY", "DIA"])
        with threshold_column:
            threshold = _input("number_input", "premarket_threshold", 2.5, tr("盘前涨幅阈值（%）", "Premarket gain threshold (%)"),
                               min_value=0.000001, max_value=10., step=.25, format="%.6f",
                               help=tr("严格大于该值；1.25 表示 1.25%。", "Strictly greater than this value; 1.25 means 1.25%."))
        definition_labels = {value: tr(*titles) for value, titles in DEFINITIONS.items()}
        with definition_column:
            definition = _input("selectbox", "premarket_definition", "fixed_0925", tr("盘前观察口径", "Premarket observation"),
                                options=list(DEFINITIONS), format_func=definition_labels.__getitem__)
        st.caption(tr("输入1.25表示盘前涨幅严格大于1.25%；开盘后下探0.5%／1%／2%是另外三个统计档位。修改参数后点击统计；不会自动取数、训练或下单。",
                      "Entering 1.25 means a premarket gain strictly greater than 1.25%. Opening downside levels of 0.5% / 1% / 2% are separate outcome thresholds. Click Compare to apply changes; there is no automatic data fetch, training or order submission."))
        submitted = st.form_submit_button(tr("统计历史事件", "Compare historical events"), key="premarket_run", type="primary",
                                          icon=":material/query_stats:")
    if submitted:
        try:
            if not symbols:
                raise PremarketReferenceError("select_at_least_one_etf")
            context = {"symbols": list(symbols), "threshold_pct": str(threshold), "definition": definition}
            reference = load_reference()
            result = analyze_reference(reference, threshold_pct=context["threshold_pct"], definition=definition, symbols=symbols)
            st.session_state["premarket_result"] = result
            st.session_state["premarket_result_context"] = context
            st.session_state["premarket_result_json"] = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False)
            st.session_state.pop("premarket_error", None)
        except (PremarketReferenceError, OSError, ValueError, KeyError, TypeError):
            st.session_state["premarket_error"] = True
    if st.session_state.get("premarket_error"):
        st.error(tr("本次统计未完成。请至少选择一只ETF并输入大于0、不超过10%的有效阈值；研究参考文件也必须通过校验。已有结果保持为上一次成功运行。",
                    "This comparison did not complete. Select at least one ETF and enter a valid threshold above 0 and at most 10%; the research reference must also pass validation. Any displayed results remain the last successful run."))
    result = st.session_state.get("premarket_result")
    if result is None:
        st.info(tr("选择ETF和盘前涨幅阈值，然后点击「统计历史事件」。", "Choose ETFs and a premarket gain threshold, then click Compare historical events."))
        return
    current = {"symbols": list(symbols), "threshold_pct": str(threshold), "definition": definition}
    _render_results(result, st.session_state["premarket_result_context"], tr, current=current)
