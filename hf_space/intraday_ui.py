"""Session-local bilingual page for the separate five-minute rule experiment.

Only explicit Run calls the engine. Uploads, settings and immutable report bytes
are held in the visitor's Streamlit session, never a process-wide cache or file.
"""
from __future__ import annotations

import copy
from importlib.metadata import version
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from hf_space.intraday import (
    make_synthetic_intraday_prices,
    parse_intraday_csv,
    run_intraday_comparison,
)


LABELS = {
    "intraday_momentum": ("正动量", "Positive intraday momentum"),
    "intraday_ma_trend": ("日内均线趋势", "Intraday moving-average trend"),
    "opening_range_breakout": ("开盘区间突破", "Opening-range breakout"),
}
COLORS = dict(zip(LABELS, ("#087F8C", "#6554A4", "#C58A28")))
REPORT_KEYS = ("source", "status", "metrics", "equity", "signals", "weights", "trades",
               "session_metrics", "lineage", "warnings")
CSV_TEMPLATE = b"timestamp,symbol,open,high,low,close,volume\n"


def _label(name, tr):
    return tr(*LABELS.get(str(name), (str(name), str(name))))


def _remember(key):
    st.session_state["_saved_" + key] = copy.deepcopy(st.session_state[key])


def _restore(key, default):
    memory = "_saved_" + key
    if memory not in st.session_state:
        st.session_state[memory] = copy.deepcopy(st.session_state.get(key, default))
    st.session_state[key] = copy.deepcopy(st.session_state[memory])


def _input(kind, key, default, text, **kwargs):
    """Restore non-widget state before translated labels recreate widgets."""
    _restore(key, default)
    return getattr(st.sidebar, kind)(text, key=key, on_change=_remember, args=(key,), **kwargs)


def _remember_upload():
    uploaded = st.session_state.get("intraday_upload")
    st.session_state["intraday_upload_bytes"] = uploaded.getvalue() if uploaded else None
    st.session_state["intraday_upload_name"] = uploaded.name if uploaded else None


def _frame(result, key):
    return pd.DataFrame(result.get(key) or [])


def _display_table(frame, tr):
    if frame.empty:
        st.caption(tr("没有记录。", "No records."))
        return
    frame = frame.copy()
    if "strategy" in frame:
        frame["strategy"] = frame.strategy.map(lambda value: _label(value, tr))
    if "symbol" in frame:
        frame.loc[frame.symbol.eq("__CASH__"), "symbol"] = tr("现金", "Cash")
    names = {
        "strategy": ("策略", "Strategy"), "session": ("美东交易日", "ET session"),
        "timestamp": ("K线开始（UTC）", "Bar start (UTC)"),
        "available_at": ("信号可见（UTC）", "Signal available (UTC)"),
        "signal_available_at": ("信号可见（UTC）", "Signal available (UTC)"),
        "execution_at": ("执行（UTC）", "Execution (UTC)"), "as_of": ("参考时点", "As of"),
        "symbol": ("证券", "Symbol"), "score": ("原始因子值", "Raw factor value"),
        "score_unit": ("分数单位", "Score unit"), "eligible": ("符合规则", "Rule eligible"),
        "status": ("状态", "Status"), "weight": ("权重（小数）", "Weight (fraction)"),
        "kind": ("资产类型", "Asset kind"), "qty": ("数量（股）", "Quantity (shares)"),
        "quantity": ("数量（股）", "Quantity (shares)"), "side": ("方向", "Side"),
        "reference_price": ("参考开盘价", "Reference open price"),
        "price": ("含点差／滑点的有效价格", "Effective price with spread/slippage"), "notional": ("参考开盘名义金额", "Reference-open notional"),
        "fee": ("费用", "Fees"), "spread": ("半点差成本", "Half-spread cost"),
        "slippage": ("滑点成本", "Slippage cost"), "spread_cost": ("半点差成本", "Half-spread cost"),
        "slippage_cost": ("滑点成本", "Slippage cost"), "reason": ("原因", "Reason"),
        "target_weight": ("参考目标权重", "Reference target weight"),
        "equity": ("权益", "Equity"), "cash": ("现金", "Cash"),
        "daily_return": ("当日收益", "Daily return"), "return": ("当日收益", "Daily return"),
        "cost": ("当日成本", "Daily cost"), "total_cost": ("总成本", "Total cost"),
    }
    st.dataframe(frame.rename(columns={key: tr(*pair) for key, pair in names.items()}),
                 hide_index=True, use_container_width=True)


def render_intraday_guide(tr):
    st.subheader(tr("先理解信号与成交", "Understand signals and execution"))
    principle, mathematics = st.tabs([tr("三种规则与时点", "Rules and timing"),
                                      tr("数学推导", "Mathematical derivation")])
    with principle:
        rows = [
            ("intraday_momentum", tr("过去L根收盘收益为正才入选；默认L=6，即30分钟。", "Qualify only when the last L-bar close return is positive; L=6 means 30 minutes.")),
            ("intraday_ma_trend", tr("收盘高于慢均线，且快均线高于慢均线；默认3／12根。", "Require the close above the slow average and the fast average above the slow average; defaults are 3/12 bars.")),
            ("opening_range_breakout", tr("先观察开盘后的前R根；之后收盘突破该区间高点入选，跌破低点退出。默认R=6。", "Observe the opening R bars first. Thereafter enter above the opening high and exit below the opening low; R=6 by default.")),
        ]
        for name, text in rows:
            st.markdown(f"**{_label(name, tr)}** — {text}")
        st.caption(tr("建议先比较6根动量、3／12均线、6根开盘区间，再研究附近窗口。数值是教学起点，未按收益选优；同日预热，不借用隔夜K线。",
                      "Start with 6-bar momentum, 3/12 averages and a 6-bar opening range, then explore nearby windows. These are teaching defaults, not optimized parameters; warmup restarts within each session."))
        st.write(tr("CSV时间戳表示UTC的K线开始。例如09:30–09:35美东K线，09:35后才可使用其收盘价。延迟0是在下一根09:35开盘近似成交；延迟1再等一根。延迟0假设端点零处理延迟，现实可能无法按该开盘成交。",
                    "CSV timestamps are UTC bar starts. The 09:30–09:35 ET close becomes available at 09:35. Delay 0 approximates a fill at the next 09:35 open; delay 1 waits one more bar. Delay 0 assumes zero endpoint processing time and may be unattainable in practice."))
        st.write(tr("只比较三组共同可用时段；尾盘预定在最后一根K线开盘清仓，不隔夜。交易所日历处理半日和夏令时，缺失任一证券K线的整天从共同窗口剔除，不补价。至少需要两个完整且在共同预热后仍可执行的交易日；长窗口或额外延迟可能使半日没有可执行时段。",
                    "Compare only the common usable intraday window. A scheduled exit at the final bar open avoids overnight holdings. The exchange calendar handles half-days and daylight saving; any session with missing bars for any symbol is excluded without filling prices. At least two complete sessions with executable windows after common warmup are required; long windows or extra delay can leave half-days unusable."))
        st.caption(tr("按全日是否完整筛选使用了事后数据质量信息，可能改变样本；它不是实时数据中断处理规则。", "Screening for whole-session completeness uses retrospective data-quality information and can change the sample; it is not a live outage-handling rule."))
    with mathematics:
        st.markdown(tr("**1 · 历史因子 → 规则资格**", "**1 · Historical factor → rule eligibility**"))
        st.latex(r"m_{i,t}=\frac{C_{i,t}}{C_{i,t-L}}-1")
        st.latex(r"e_{i,t}=\mathbf{1}[m_{i,t}>0]")
        st.caption(tr("均线策略入选须同时满足以下两项：", "Moving-average eligibility requires both conditions:"))
        st.latex(r"C_{i,t}>\mathrm{SMA}_{s,i,t}")
        st.latex(r"\mathrm{SMA}_{f,i,t}>\mathrm{SMA}_{s,i,t}")
        st.latex(r"H_i^{OR}=\max_{j<R}H_{i,j}")
        st.latex(r"L_i^{OR}=\min_{j<R}L_{i,j}")
        st.caption(tr("开盘区间固定后才判断突破；突破状态在高低点之间保持，日末清除。原始值是历史收益或相对均线／区间的比率，不是未来收益预测，不能与未来收益成本门槛比较。",
                      "Evaluate breakouts only after the opening range is fixed. Retain the breakout state between its high and low and reset it daily. Raw scores describe historical returns or relative price levels, not future-return forecasts; do not compare them with a forecast-cost threshold."))
        st.markdown(tr("**2 · 合格股票 → 等权目标与现金**", "**2 · Eligible assets → equal targets and cash**"))
        st.latex(r"N_t=\sum_i e_{i,t}")
        st.latex(r"w_{i,t}=e_{i,t}\min\!\left(w_{max},\frac{1-c_{min}}{N_t}\right)")
        st.latex(r"w_{cash,t}=1-\sum_i w_{i,t}")
        st.caption(tr("N=0时全部现金。这里使用等权、单股上限和现金下限，不使用EWMA或分钟年化风险预算。约束作用于目标，持仓比例会随价格和成本漂移。",
                      "Hold all cash when N=0. Allocation uses equal weights, a position cap and a cash floor, without EWMA or a minute-annualized risk budget. Constraints apply to targets; held weights drift with prices and costs."))
        st.markdown(tr("**3 · 目标 → 整数股差额 → 纸面成交与成本**", "**3 · Targets → integer-share differences → proxy fills and costs**"))
        st.caption(tr("b_f、b_h、b_s分别是单边费用、半点差和滑点的bps；G是保守的名义换手上界。", "b_f, b_h and b_s are per-side fee, half-spread and slippage in bps; G is a conservative gross-notional turnover bound."))
        st.latex(r"\rho=\frac{b_f+b_h+b_s}{10000}")
        st.latex(r"G=V_{old\ assets}+V_{open}\sum_i w_i")
        st.latex(r"V_{size}=\max(0,V_{open}-\rho G)")
        st.latex(r"q^*_{i,t+1}=\left\lfloor\frac{w_{i,t}V_{size}}{O_{i,t+1}}\right\rfloor")
        st.latex(r"\Delta q_i=q_i^*-q_i")
        st.latex(r"\mathrm{cost}_i=|\Delta q_i|O_i\rho")
        st.caption(tr("先保守预留卖出旧持仓和买入全部目标的成本上界，再先卖后买，并按可用现金限制整数股购买。成本只按实际成交金额逐边扣除，尾盘清仓也有成本。所有成交均为OHLC开盘代理，未建模盘口、排队、部分成交、市场冲击或真实延迟分布，不是券商执行系统。",
                      "First reserve a conservative cost bound for selling old assets and buying all targets, then sell before buying with integer-share buys constrained by cash. Charge costs only on actual executed notional on each side, including the scheduled exit. Fills are OHLC-open proxies without order books, queue position, partial fills, market impact or a real latency distribution; this is not a brokerage execution system."))


def _render_source(result, tr):
    source = result.get("source")
    if source == "synthetic":
        st.warning(tr("上次运行使用合成教学行情：虚构资产、非真实市场表现。", "The last run used synthetic teaching prices: fictional assets, not observed market performance."))
    elif source == "uploaded_csv":
        st.info(tr("上次运行使用访客上传的5分钟CSV；来源真实性与复权口径由上传者确认，平台仅做格式和交易时段校验。",
                   "The last run used an uploaded 5-minute CSV. The uploader must verify provenance and adjustment basis; the platform checks format and session consistency."))
    else:
        st.warning(tr("结果来源未识别，请查看运行信息。", "The result source is unrecognized; inspect the run details."))


def render_intraday_results(result, context, tr):
    _render_source(result, tr)
    st.caption(tr("当前展示上次运行的设置：", "Displayed settings are from the last run: ")
               + f"{context['benchmark']} · L={context['lookback_bars']} · MA={context['fast_bars']}/{context['slow_bars']}"
               + f" · OR={context['opening_range_bars']} · "
               + tr("额外延迟", "extra delay ") + f"{context['execution_delay_bars']} " + tr("根", "bar(s)")
               + f" · fee/spread/slip={context['cost_bps']}/{context['half_spread_bps']}/{context['slippage_bps']} bps"
               + tr("；修改参数后需重新运行。", ". Run again to apply changed settings."))
    overview, day_tab, ledger_tab, information = st.tabs([
        tr("收益与风险", "Returns and risk"), tr("每日汇总", "Daily aggregation"),
        tr("信号、权重与成交", "Signals, weights and fills"), tr("来源与下载", "Provenance and downloads")])
    with overview:
        metrics = _frame(result, "metrics")
        if not metrics.empty:
            view = pd.DataFrame({tr("策略", "Strategy"): metrics.strategy.map(lambda value: _label(value, tr))})
            for field, zh, en, scale in (
                ("total_return", "累计收益 %", "Total return %", 100),
                ("max_drawdown", "最大回撤 %", "Max drawdown %", 100),
                ("sharpe", "日聚合夏普", "Daily-aggregated Sharpe", 1),
                ("annualized_volatility", "日聚合年化波动 %", "Daily-aggregated annualized volatility %", 100),
                ("total_cost", "累计模拟成本", "Total simulated cost", 1),
                ("trade_count", "成交笔数", "Executed fills", 1),
                ("n_sessions", "有效交易日数", "Usable sessions", 1),
            ):
                if field in metrics:
                    view[tr(zh, en)] = pd.to_numeric(metrics[field], errors="coerce") * scale
            view[tr("状态", "Status")] = metrics.status
            st.dataframe(view, hide_index=True, use_container_width=True)
            for row in metrics.to_dict("records"):
                if row.get("status") != "success":
                    st.error(_label(row.get("strategy"), tr) + ": " + str(row.get("error") or row.get("status")))
        coverage = (result.get("lineage") or {}).get("coverage") or {}
        if "complete_session_count" in coverage or "usable_session_count" in coverage:
            st.caption(tr("完整行情日／预热后可执行共同日：", "Complete-data sessions / usable common sessions: ")
                       + f"{coverage.get('complete_session_count', '—')} / {coverage.get('usable_session_count', '—')}")
        st.caption(tr("三组使用共同日期和最长预热窗口。夏普基于每日聚合收益，年化波动为日收益标准差×√252；少于20个有效交易日均不显示，不按5分钟根数年化。这些统计也不构成策略有效性证据。",
                      "All three strategies share dates and the longest warmup. Sharpe uses daily aggregate returns; annualized volatility is daily-return standard deviation ×√252. Both are omitted below 20 usable sessions; neither annualizes by the number of 5-minute bars. These statistics do not establish strategy validity."))
        equity = _frame(result, "equity")
        if not equity.empty:
            equity["timestamp"] = pd.to_datetime(equity.timestamp, utc=True)
            for field, zh, en in (("equity", "含成本纸面权益（UTC）", "Proxy equity after costs (UTC)"),
                                  ("drawdown", "纸面回撤（UTC）", "Proxy drawdown (UTC)")):
                fig = px.line(equity.sort_values(["strategy", "timestamp"]), x="timestamp", y=field,
                              color="strategy", color_discrete_map=COLORS, title=tr(zh, en))
                for trace in fig.data:
                    trace.name = _label(trace.name, tr)
                if field == "equity" and "benchmark_equity" in equity:
                    reference = equity[["timestamp", "benchmark_equity"]].drop_duplicates("timestamp").sort_values("timestamp")
                    fig.add_trace(go.Scatter(x=reference.timestamp, y=reference.benchmark_equity,
                                             name=tr("基准日内全投资参考", "Fully invested intraday benchmark"),
                                             line=dict(dash="dash", color="#273444")))
                if field == "drawdown":
                    fig.update_yaxes(tickformat=".0%")
                fig.update_layout(template="plotly_white", height=350, margin=dict(l=12, r=12, t=52, b=12),
                                  xaxis_title=None, yaxis_title=None, legend_title_text="",
                                  legend=dict(orientation="h", y=-.24), hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(tr("没有权益曲线；数据不足时不生成替代结果。", "No equity curve; insufficient data is not replaced with fabricated results."))
        st.caption(tr("基准每天首根开盘全投资买入、末根开盘卖出，整数股且同费率；它与受单股上限及现金约束的策略风险暴露不同。开盘价加固定费用／半点差／滑点只是近似，不能证明真实可成交或盈利。",
                      "The benchmark buys at each session's first-bar open and sells at its final-bar open, using integer shares and the same cost rates. Its full-investment exposure differs from capped strategies with cash. Open prices plus fixed fees, half-spread and slippage are approximations, not evidence of executable or profitable trading."))
    with day_tab:
        _display_table(_frame(result, "session_metrics"), tr)
        st.caption(tr("每日汇总用于区分日内波动与独立交易日信息；同一天的多根K线不能当作独立样本。", "Daily aggregation separates within-session bars from session-level evidence; many bars from the same day are not independent samples."))
    with ledger_tab:
        weights = _frame(result, "weights")
        if not weights.empty and "kind" in weights:
            targets = weights.loc[weights.kind.eq("target")]
            actual = weights.loc[~weights.kind.eq("target")]
        else:
            targets, actual = pd.DataFrame(), weights
        if not targets.empty:
            st.subheader(tr("最后一次日内参考目标", "Last intraday reference targets"))
            _display_table(targets, tr)
            st.caption(tr("这是最后一次实际调仓采用的等权参考目标；as_of为对应信号可见时间。整数股、成本和尾盘清仓后的实际持仓可能不同，不是可提交订单。", "These equal-weight reference targets were used at the last simulated rebalance; as_of identifies the associated signal's availability. Integer shares, costs and the scheduled exit can leave different actual holdings. These are not orders to submit."))
        st.subheader(tr("实际期末持仓权重", "Actual simulated ending weights"))
        _display_table(actual, tr)
        st.caption(tr("本实验每日尾盘强制清仓，因此最终实际持仓为现金；日内目标分配原理见数学推导。信号与目标不是券商订单。", "Scheduled daily exits leave actual final holdings in cash; the mathematical tab explains intraday target allocation. Signals and targets are not brokerage orders."))
        st.subheader(tr("逐笔模拟成交", "Individual proxy fills"))
        _display_table(_frame(result, "trades"), tr)
        st.caption(tr("有效价格包含半点差及滑点，参考名义金额仍按原始open计算。费用、半点差、滑点单列组成总成本，只扣一次。", "The effective price includes half-spread and slippage; reference notional uses the original open. Fees, half-spread and slippage are itemized into total cost and charged once."))
        with st.expander(tr("完整信号记录", "All signal records")):
            _display_table(_frame(result, "signals"), tr)
    with information:
        for warning in result.get("warnings") or []:
            st.warning(str(warning))
        st.json({"settings": context, "lineage": result.get("lineage") or {}})
        st.download_button(tr("下载5分钟研究JSON", "Download 5-minute research JSON"),
                           data=st.session_state["intraday_result_json"], file_name="intraday-research-report.json",
                           mime="application/json", key="intraday_download_report", use_container_width=True)
        st.caption(tr("下载保留原始字段与该次运行来源、参数和数据审计；语言切换不修改JSON或重新运行。", "The download retains raw fields plus provenance, settings and input audit for this run. Language changes do not alter the JSON or rerun the experiment."))


def render_intraday_page(tr):
    st.title(tr("5分钟动量与趋势实验室", "5-minute Momentum & Trend Lab"))
    st.write(tr("上传真实moomoo分钟行情，或明确选择合成教学数据，比较三种日内规则及其含成本纸面成交。",
                "Upload observed moomoo minute bars or explicitly select synthetic teaching prices to compare three intraday rules and proxy fills after costs."))
    st.caption(tr("独立5分钟研究：不训练DL／GenAI模型，不连接moomoo账户，不自动下载Yahoo分钟行情，不提交订单。",
                  "Separate 5-minute research: no DL/GenAI training, moomoo account connection, automatic Yahoo minute download or order submission."))
    render_intraday_guide(tr)
    st.sidebar.subheader(tr("5分钟数据与参数", "5-minute data and settings"))
    sources = {"uploaded_csv": tr("真实moomoo / 访客5分钟CSV", "Observed moomoo / visitor 5-minute CSV"),
               "synthetic": tr("合成教学数据", "Synthetic teaching data")}
    source = _input("radio", "intraday_source", "uploaded_csv", tr("5分钟数据来源", "5-minute data source"),
                    options=list(sources), index=None, format_func=sources.__getitem__)
    if source == "uploaded_csv":
        st.sidebar.file_uploader("5-minute CSV", type=["csv"], key="intraday_upload", on_change=_remember_upload)
        name = st.session_state.get("intraday_upload_name")
        if name:
            st.sidebar.caption(tr("会话中保留的文件：", "File retained in this session: ") + name)
        st.sidebar.caption(tr("七列：timestamp,symbol,open,high,low,close,volume。timestamp必须为含时区的UTC K线开始；1–12只股票加基准，最多8 MiB／50000行。仅美股常规交易时段，所有证券需覆盖完整交易日。至少2个完整且预热后可执行的共同日；缺bar或无可执行时段的整天剔除。只上传有权在云端处理的行情，不含账户或个人资料。",
                              "Columns: timestamp,symbol,open,high,low,close,volume. Use timezone-aware UTC bar-start timestamps; 1–12 stocks plus benchmark, at most 8 MiB / 50,000 rows. Provide complete US regular sessions for every symbol. At least 2 complete and executable common sessions are required; exclude an entire session for missing bars or no post-warmup execution window. Upload only market data authorized for cloud processing, without account or personal details."))
    else:
        st.sidebar.warning(tr("虚构教学行情，仅说明规则与撮合，不代表真实市场。", "Fictional teaching prices illustrate rules and fills, not observed markets."))
        st.sidebar.caption(tr("使用5个完整交易日、6只虚构股票加BENCH；不足20日不显示夏普及年化波动。", "Use 5 complete sessions, 6 fictional assets and BENCH; Sharpe and annualized volatility are omitted below 20 sessions."))
    st.sidebar.download_button(tr("下载5分钟CSV空白模板", "Download blank 5-minute CSV template"),
                               CSV_TEMPLATE, file_name="intraday-template.csv", mime="text/csv",
                               key="intraday_download_template", use_container_width=True)
    benchmark = "BENCH" if source == "synthetic" else _input("text_input", "intraday_benchmark", "SPY", tr("日内基准代码", "Intraday benchmark symbol")).strip().upper()
    momentum = _input("number_input", "intraday_momentum_lookback", 6, tr("正动量回看（5分钟根数）", "Momentum lookback (5-minute bars)"), min_value=1, max_value=30, step=1)
    fast = _input("number_input", "intraday_fast_window", 3, tr("日内快均线（根）", "Intraday fast average (bars)"), min_value=1, max_value=30, step=1)
    slow = _input("number_input", "intraday_slow_window", 12, tr("日内慢均线（根）", "Intraday slow average (bars)"), min_value=2, max_value=60, step=1)
    opening = _input("number_input", "intraday_opening_range", 6, tr("开盘观察区间（根）", "Opening observation range (bars)"), min_value=1, max_value=12, step=1)
    st.sidebar.caption(tr("建议从6／3／12／6开始；每根5分钟。参数探索不等于新的样本外证据。", "Suggested starting windows: 6 / 3 / 12 / 6; each bar is 5 minutes. Parameter exploration is not fresh out-of-sample evidence."))
    seed = _input("number_input", "intraday_seed", 42, tr("教学数据随机种子", "Teaching-data random seed"), min_value=0, max_value=2147483647, step=1)
    fee = _input("slider", "intraday_cost", 10, tr("单边费用（bps）", "Per-side fees (bps)"), min_value=0, max_value=50, step=1)
    spread = _input("slider", "intraday_half_spread", 1, tr("单边半点差（bps）", "Per-side half-spread (bps)"), min_value=0, max_value=50, step=1)
    slippage = _input("slider", "intraday_slippage", 1, tr("单边滑点（bps）", "Per-side slippage (bps)"), min_value=0, max_value=50, step=1)
    delay_names = {0: tr("0：下一根开盘（零处理延迟近似）", "0: next-bar open (zero processing-delay proxy)"),
                   1: tr("1：额外等待一根K线", "1: wait one additional bar")}
    delay = _input("selectbox", "intraday_execution_delay", 0, tr("额外执行延迟", "Additional execution delay"), options=[0, 1], index=None, format_func=delay_names.__getitem__)
    cap = _input("slider", "intraday_cap", 20, tr("单股目标仓位上限 %", "Per-stock target cap %"), min_value=10, max_value=100, step=5)
    cash = _input("slider", "intraday_cash_floor", 20, tr("目标现金下限 %", "Target cash floor %"), min_value=0, max_value=80, step=5)
    submitted = st.sidebar.button(tr("运行三种5分钟策略", "Run three 5-minute strategies"), key="intraday_run", type="primary", use_container_width=True)
    if submitted:
        st.session_state["intraday_error"] = None
        try:
            params = dict(benchmark=benchmark, source=source, lookback_bars=int(momentum),
                          fast_bars=int(fast), slow_bars=int(slow), opening_range_bars=int(opening),
                          cost_bps=int(fee), half_spread_bps=int(spread), slippage_bps=int(slippage),
                          execution_delay_bars=int(delay), max_weight=cap / 100, cash_floor=cash / 100)
            with st.spinner(tr("正在校验完整交易日并撮合三组规则。", "Validating complete sessions and simulating three rules.")):
                if source == "synthetic":
                    prices = make_synthetic_intraday_prices(seed=int(seed))
                else:
                    contents = st.session_state.get("intraday_upload_bytes")
                    if contents is None:
                        raise ValueError(tr("请先上传5分钟CSV文件。", "Upload a 5-minute CSV file first."))
                    prices = parse_intraday_csv(contents, benchmark=benchmark)
                result = run_intraday_comparison(prices, **params)
                if not isinstance(result, dict) or any(key not in result for key in REPORT_KEYS):
                    raise ValueError(tr("日内引擎返回不完整结果。", "The intraday engine returned an incomplete report."))
                report = {key: copy.deepcopy(result[key]) for key in REPORT_KEYS}
                report.setdefault("lineage", {})["synthetic_seed"] = int(seed) if source == "synthetic" else None
                report["lineage"].setdefault("dependencies", {}).update(
                    {name: version(name) for name in ("streamlit", "plotly", "pyarrow")})
                serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
            st.session_state["intraday_result"] = report
            st.session_state["intraday_result_json"] = serialized
            st.session_state["intraday_result_context"] = params
        except Exception as error:
            st.session_state["intraday_result"] = None
            st.session_state["intraday_result_json"] = None
            st.session_state["intraday_result_context"] = None
            st.session_state["intraday_error"] = str(error)
    if st.session_state.get("intraday_error"):
        st.error(tr("本次5分钟研究未完成：", "This 5-minute experiment did not complete: ") + st.session_state["intraday_error"])
    result = st.session_state.get("intraday_result")
    if result is None:
        st.info(tr("选择5分钟来源和参数后点击运行。切换语言、页面或参数不自动重算。", "Choose 5-minute data and settings, then click Run. Language, page or parameter changes do not rerun the experiment."))
        return
    render_intraday_results(result, st.session_state["intraday_result_context"], tr)
