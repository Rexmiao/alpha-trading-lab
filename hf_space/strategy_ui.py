"""Bilingual, session-local daily rule-strategy page for the public lab."""
from __future__ import annotations

import copy
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from hf_space.engine import make_synthetic_prices, parse_csv
from hf_space.history import fetch_history
from hf_space.strategies import run_strategy_comparison


LABELS = {
    "cross_sectional_momentum": ("横截面动量", "Cross-sectional momentum"),
    "time_series_momentum": ("时间序列动量", "Time-series momentum"),
    "moving_average_trend": ("均线趋势", "Moving-average trend"),
    "channel_breakout": ("通道突破", "Channel breakout"),
}
COLORS = dict(zip(LABELS, ("#087F8C", "#6554A4", "#C58A28", "#486581")))
DEFAULT_SYMBOLS = "NVDA, AMD, AVGO, MU, WDC, NBIS, CRWV"


def label(name, tr):
    return tr(*LABELS.get(str(name), (str(name), str(name))))


def render_guide(tr):
    st.subheader(tr("理解四种策略", "Understand the four strategies"))
    previous = st.session_state.get("strategy_explanation", next(iter(LABELS)))
    names = {name: label(name, tr) for name in LABELS}
    selected = st.selectbox(tr("查看策略原理", "Explore a strategy"), list(LABELS), index=list(LABELS).index(previous),
                            format_func=names.__getitem__, key="strategy_explanation")
    descriptions = {
        "cross_sectional_momentum": (
            "比较股票之间谁过去更强。按回看窗口收益排序，最多选择前四只；即使全部下跌，排名第一仍可能入选。",
            "Compare stocks with one another. Rank lookback returns and select up to four stocks; the strongest stock can still have a negative return.",
            r"m_{i,t}=C_{i,t}/C_{i,t-L}-1,\quad S_t=\operatorname{TopK}(m_{i,t})"),
        "time_series_momentum": (
            "每只股票先与自己的历史比较。让回看收益为正的股票参与风险分配；没有合格股票时保留现金。",
            "Compare each stock with its own history. Positive-lookback-return stocks qualify for risk allocation; hold cash when none qualify.",
            r"m_{i,t}=C_{i,t}/C_{i,t-L}-1,\quad \mathrm{eligible}_{i,t}=[m_{i,t}>0]"),
        "moving_average_trend": (
            "同时要求收盘价高于慢均线、快均线高于慢均线。符合条件的股票参与风险分配；默认快慢窗口为50／200个交易日。",
            "Require the close above the slow average and the fast average above the slow average. Allocate risk among qualifying stocks; defaults are 50/200 sessions.",
            r"\mathrm{eligible}_{i,t}=[C_{i,t}>\mathrm{SMA}_{slow,t}]\land[\mathrm{SMA}_{fast,t}>\mathrm{SMA}_{slow,t}]"),
        "channel_breakout": (
            "收盘价突破此前入场窗口最高价后进入候选状态，跌破此前退出窗口最低价后退出；窗口排除当天，状态在两次突破之间保持。所有合格候选参与风险分配。",
            "Enter the candidate state when the close exceeds the prior entry-window high; exit below the prior exit-window low. Exclude today's bar and retain state between crossings, allocate risk among all qualifying candidates.",
            r"\mathrm{enter}:C_t>\max(H_{t-E},\ldots,H_{t-1}),\quad\mathrm{exit}:C_t<\min(L_{t-X},\ldots,L_{t-1})"),
    }
    zh, en, formula = descriptions[selected]
    st.write(tr(zh, en))
    st.latex(formula)
    st.caption(tr("这些是可检查的研究基线，参数不是经验证的最优值。动量分数不是未来收益预测，不用于收益／成本门槛；实际换仓仍扣成本，并共用仓位与风险约束。",
                  "These are inspectable research baselines, not optimized parameters. Momentum scores are not return forecasts and do not pass a forecast-versus-cost gate; executed trades still incur costs and share position/risk constraints."))
    with st.expander(tr("分钟级动量：研究与数据入口", "Minute-level momentum: research and data")):
        st.write(tr("本页当前运行日频策略。分钟数据不等于秒级高频交易；5／15分钟策略还需要独立的时间戳、完整K线、点差、延迟与成交验证，当前没有分钟回测结果。",
                    "This page currently runs daily strategies. Minute bars are different from sub-second trading. A 5/15-minute strategy needs separate timestamp, completed-bar, spread, latency and execution validation; no intraday backtest is presented here."))
        st.markdown(tr(
            "- [Market Intraday Momentum（JFE 2018）](https://doi.org/10.1016/j.jfineco.2018.05.009)：前收盘至10:00的收益预测尾盘半小时，包含隔夜跳空。\n- [moomoo分钟历史接口](https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-history-kline.html)：支持分钟周期，账户权限、历史额度与接入路线需核实。\n- [Alpaca历史数据规则](https://docs.alpaca.markets/us/docs/market-data-faq) / [Massive分钟历史](https://massive.com/docs/rest/stocks/aggregates/custom-bars)：免费历史与实时全市场权限不同。",
            "- [Market Intraday Momentum (JFE 2018)](https://doi.org/10.1016/j.jfineco.2018.05.009): the previous close to 10:00 return predicts the final half-hour, including the overnight gap.\n- [moomoo historical bars](https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-history-kline.html): minute intervals are supported; account access, quotas and connection route need verification.\n- [Alpaca historical data rules](https://docs.alpaca.markets/us/docs/market-data-faq) / [Massive minute history](https://massive.com/docs/rest/stocks/aggregates/custom-bars): free history differs from real-time consolidated access."))


def render_results(result, context, tr):
    st.caption(tr("当前展示的是上次运行：", "Displayed results are from the last run: ")
               + f"{context['benchmark']} · {context['rebalance_days']} "
               + tr("交易日调仓", "sessions per rebalance")
               + f" · {context['cost_bps']} bps · L={context['lookback']}"
               + tr("；修改参数后需再次点击运行。", ". Click Run again to apply changed settings."))
    overview, signals_tab, details = st.tabs([tr("收益与风险", "Returns and risk"),
                                            tr("信号与权重", "Signals and weights"),
                                            tr("运行信息", "Run details")])
    with overview:
        metrics = pd.DataFrame(result.get("metrics") or [])
        if not metrics.empty:
            view = pd.DataFrame({tr("策略", "Strategy"): metrics.strategy.map(lambda value: label(value, tr))})
            fields = [("total_return", "累计收益 %", "Total return %", 100),
                      ("sharpe", "夏普比率", "Sharpe ratio", 1),
                      ("max_drawdown", "最大回撤 %", "Max drawdown %", 100),
                      ("annualized_volatility", "年化波动 %", "Annualized volatility %", 100),
                      ("total_cost", "累计模拟成本", "Total simulated costs", 1),
                      ("trade_count", "成交笔数", "Executed trades", 1)]
            for key, zh, en, scale in fields:
                if key in metrics:
                    view[tr(zh, en)] = pd.to_numeric(metrics[key], errors="coerce") * scale
            if "status" in metrics:
                view[tr("状态", "Status")] = metrics.status.map(
                    lambda value: tr("完成", "Complete") if value == "success" else tr("未完成", "Incomplete"))
            st.dataframe(view, hide_index=True, use_container_width=True)
            for row in metrics.to_dict("records"):
                if row.get("status") != "success":
                    st.error(label(row.get("strategy"), tr) + ": " + str(row.get("error") or row.get("status")))
        st.caption(tr("四组策略使用共同评估窗口，收盘后形成信号、下一交易日开盘模拟换仓。最终收盘为估值，基准买入持有不扣费用。短窗口夏普和年化波动仅作描述。",
                      "The four strategies share an evaluation window, with post-close signals and next-open simulated rebalancing. The final close is a valuation; benchmark buy-and-hold excludes fees. Short-window Sharpe and annualized volatility are descriptive."))
        st.caption(tr("仓位上限和现金下限约束调仓目标，期间比例随价格漂移；风险预算基于历史估计，实际波动可能超过预算。",
                      "Position caps and cash floors constrain rebalance targets; weights drift between rebalances. Risk budgets use historical estimates, so realized volatility can exceed the budget."))
        frame = pd.DataFrame(result.get("equity") or [])
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame.date)
            for field, zh, en in (("equity", "含成本的模拟权益", "Simulated equity after costs"),
                                  ("drawdown", "模拟回撤", "Simulated drawdown")):
                fig = px.line(frame.sort_values(["strategy", "date"]), x="date", y=field, color="strategy",
                              color_discrete_map=COLORS, title=tr(zh, en))
                for trace in fig.data:
                    trace.name = label(trace.name, tr)
                if field == "equity" and "benchmark_equity" in frame:
                    bench = frame[["date", "benchmark_equity"]].drop_duplicates("date").sort_values("date")
                    fig.add_trace(go.Scatter(x=bench.date, y=bench.benchmark_equity,
                                            name=tr("基准买入持有", "Benchmark buy and hold"),
                                            line=dict(color="#273444", dash="dash")))
                if field == "drawdown":
                    fig.update_yaxes(tickformat=".0%")
                fig.update_layout(template="plotly_white", height=380, margin=dict(l=12, r=12, t=52, b=12),
                                  xaxis_title=None, yaxis_title=None, legend_title_text="",
                                  legend=dict(orientation="h", y=-.2), hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)
    with signals_tab:
        st.caption(tr("最新规则状态是研究参考，不是待提交订单；每天观察信号，实际换仓只发生在调仓锚点。",
                      "Latest rule states are research references, not queued orders. Observe signals daily; rebalance only at scheduled anchors."))
        signals = pd.DataFrame(result.get("signals") or [])
        if not signals.empty:
            latest = signals.loc[signals.date.eq(signals.date.max())].copy()
            st.subheader(tr("最新信号：", "Latest signals: ") + str(signals.date.max()))
            latest["strategy"] = latest.strategy.map(lambda value: label(value, tr))
            units = {"historical_simple_return": tr("历史区间收益", "Historical return"),
                     "close_to_slow_average_fraction": tr("收盘/慢均线−1", "Close / slow MA − 1"),
                     "close_to_previous_entry_high_fraction": tr("收盘/此前高点−1", "Close / prior high − 1")}
            statuses = {"eligible": tr("符合规则", "Eligible"), "rule_off": tr("规则未触发", "Rule off"),
                        "not_selected": tr("未入选", "Not selected"), "missing_bar": tr("缺少行情", "Missing bar"),
                        "insufficient_history": tr("历史不足", "Insufficient history")}
            latest["score_unit"] = latest.score_unit.map(lambda value: units.get(value, value))
            latest["status"] = latest.status.map(lambda value: statuses.get(value, value))
            latest = latest[["strategy", "date", "symbol", "score", "score_unit", "eligible", "status"]]
            st.dataframe(latest.rename(columns={"strategy": tr("策略", "Strategy"), "date": tr("日期", "Date"),
                "symbol": tr("证券", "Symbol"), "score": tr("原始因子值", "Raw factor value"),
                "score_unit": tr("因子含义", "Factor meaning"),
                "eligible": tr("符合规则", "Rule eligible"), "status": tr("数据状态", "Data status")}),
                hide_index=True, use_container_width=True)
        weights = pd.DataFrame(result.get("weights") or [])
        if not weights.empty:
            st.subheader(tr("最新参考目标权重", "Latest reference target weights"))
            weights["strategy"] = weights.strategy.map(lambda value: label(value, tr))
            weights.loc[weights.symbol.eq("__CASH__"), "symbol"] = tr("现金", "Cash")
            weights["weight"] = pd.to_numeric(weights.weight) * 100
            st.dataframe(weights[["strategy", "symbol", "weight"]].rename(columns={
                "strategy": tr("策略", "Strategy"), "symbol": tr("证券", "Symbol"),
                "weight": tr("目标权重 %", "Target weight %")}), hide_index=True, use_container_width=True)
    with details:
        for warning in result.get("warnings") or []:
            st.caption(str(warning))
        st.json({"settings": context, "lineage": result.get("lineage") or {}})
        st.download_button(tr("下载策略研究 JSON", "Download strategy research JSON"),
            data=st.session_state["strategy_result_json"], file_name="momentum-trend-report.json",
            mime="application/json", use_container_width=True)
        st.caption(tr("与 AI 页面比较时，须同时对齐行情快照、评估日期、仓位和成本；两个页面不会自动组成统一样本外比赛。",
                      "To compare with the AI page, align the price snapshot, evaluation dates, allocation and costs. The pages do not automatically form a common out-of-sample contest."))


def render_strategy_page(tr, render_data_source, input_coverage, render_online_downloads):
    st.title(tr("动量与趋势实验室", "Momentum & Trend Lab"))
    st.write(tr("用同一份日 K 比较四类规则策略，查看信号、仓位、含成本权益与回撤。",
                "Compare four rule strategies on the same daily bars: signals, weights, equity after costs and drawdowns."))
    render_guide(tr)
    st.sidebar.subheader(tr("策略数据与参数", "Strategy data and settings"))
    sources = {"uploaded_csv": tr("moomoo / 访客 CSV", "moomoo / visitor CSV"),
               "online_history": tr("在线真实历史日 K", "Online real daily history"),
               "synthetic": tr("合成教学数据", "Synthetic teaching data")}
    previous_source = st.session_state.get("strategy_source", "uploaded_csv")
    source = st.sidebar.radio(tr("数据来源", "Data source"), list(sources), index=list(sources).index(previous_source),
                              format_func=sources.__getitem__, key="strategy_source")
    uploaded = None
    if source == "uploaded_csv":
        uploaded = st.sidebar.file_uploader(tr("选择日 K CSV", "Choose daily OHLCV CSV"),
                                            type=["csv"], key="strategy_csv")
        st.sidebar.caption(tr("7列：date,symbol,open,high,low,close,volume；3–12股加基准，最多3 MiB／8000行／600日期。只上传有权在云端处理的行情，不含账户或个人信息。",
                              "Columns: date,symbol,open,high,low,close,volume; 3–12 stocks plus benchmark, at most 3 MiB / 8,000 rows / 600 dates. Upload only authorized market data, excluding account and personal information."))
    elif source == "online_history":
        st.sidebar.caption(tr("运行时获取最多400个已完成交易日的 Yahoo 历史；无密钥、非实时，失败不替换成合成数据。",
                              "Run retrieves up to 400 completed sessions of Yahoo history; no API key, not real time, and no synthetic fallback on failure."))
    else:
        st.sidebar.caption(tr("6只虚构资产＋BENCH、400个工作日；不代表市场数据或业绩。",
                              "Six fictional assets plus BENCH over 400 weekdays; not market observations or performance."))
    with st.sidebar.form("strategy_run_form"):
        benchmark = "BENCH" if source == "synthetic" else st.text_input(
            tr("基准代码", "Benchmark symbol"), value="SPY", key="strategy_benchmark").strip().upper()
        symbols_text, refresh = "", False
        if source == "online_history":
            symbols_text = st.text_input(tr("股票代码（逗号分隔，3–8只）", "Stock symbols (comma-separated, 3–8)"),
                                         value=DEFAULT_SYMBOLS, key="strategy_symbols")
            refresh = st.checkbox(tr("重新获取在线行情", "Refresh online history"), key="strategy_refresh")
        rebalance = st.number_input(tr("调仓间隔（交易日）", "Rebalance interval (sessions)"),
                                     min_value=1, max_value=20, value=5, key="strategy_rebalance")
        lookback = st.number_input(tr("动量回看（交易日）", "Momentum lookback (sessions)"),
                                    min_value=5, max_value=200, value=60, key="strategy_lookback")
        fast = st.number_input(tr("快均线窗口", "Fast average window"), min_value=2, max_value=100, value=50, key="strategy_fast")
        slow = st.number_input(tr("慢均线窗口", "Slow average window"), min_value=20, max_value=300, value=200, key="strategy_slow")
        entry = st.number_input(tr("突破入场窗口", "Breakout entry window"), min_value=5, max_value=200, value=55, key="strategy_entry")
        exit_ = st.number_input(tr("突破退出窗口", "Breakout exit window"), min_value=2, max_value=100, value=20, key="strategy_exit")
        test = st.number_input(tr("共同评估窗口（交易日）", "Common evaluation window (sessions)"),
                                min_value=20, max_value=180, value=60, key="strategy_test")
        st.caption(tr("先固定参数做比较；预热历史不计入评估。参数变化是探索，不构成新的样本外证据。",
                      "Freeze settings before comparison; warmup history is excluded from evaluation. Changing settings is exploratory, not fresh out-of-sample evidence."))
        seed = st.number_input(tr("教学数据随机种子", "Teaching-data random seed"),
                                min_value=0, max_value=2147483647, value=42, key="strategy_seed")
        cost = st.slider(tr("单边成交成本（bps）", "Execution cost per side (bps)"), 0, 50, 10, key="strategy_cost")
        cap = st.slider(tr("单股仓位上限 %", "Per-stock position cap %"), 10, 40, 20, 5, key="strategy_cap")
        risk = st.slider(tr("组合年化波动预算 %", "Annualized portfolio volatility budget %"), 5, 30, 15, key="strategy_risk")
        submitted = st.form_submit_button(tr("运行四种策略", "Run four strategies"), type="primary", use_container_width=True)
    if submitted:
        st.session_state["strategy_error"] = None
        try:
            params = dict(benchmark=benchmark, source=source, rebalance_days=int(rebalance), cost_bps=int(cost),
                max_weight=cap / 100, target_vol=risk / 100, lookback=int(lookback), fast_window=int(fast),
                slow_window=int(slow), entry_window=int(entry), exit_window=int(exit_), test_sessions=int(test))
            with st.spinner(tr("正在校验行情并回测四种规则；无需训练模型。", "Validating prices and backtesting four rules; no model training.")):
                external = None
                if source == "synthetic":
                    prices = make_synthetic_prices(seed=int(seed))
                elif source == "uploaded_csv":
                    if uploaded is None:
                        raise ValueError(tr("请先选择 CSV 文件。", "Choose a CSV file first."))
                    prices = parse_csv(uploaded.getvalue(), benchmark=benchmark)
                else:
                    symbols = tuple(symbol.strip().upper() for symbol in symbols_text.split(",") if symbol.strip())
                    cache_key = (tuple(sorted(symbols)), benchmark)
                    cached = st.session_state.get("hf_online_snapshot")
                    if refresh or not cached or cached.get("key") != cache_key:
                        prices, external = fetch_history(symbols, benchmark=benchmark, sessions=400)
                        st.session_state["hf_online_snapshot"] = {"key": cache_key, "prices": prices.copy(deep=True),
                                                                 "provenance": copy.deepcopy(external)}
                    else:
                        prices, external = cached["prices"].copy(deep=True), copy.deepcopy(cached["provenance"])
                report = run_strategy_comparison(prices, **params)
                report.setdefault("lineage", {})["input_coverage"] = input_coverage(prices)
                if external is not None:
                    report["lineage"]["external_data"] = external
                report["lineage"]["synthetic_seed"] = int(seed) if source == "synthetic" else None
                serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)
            st.session_state["strategy_result"] = report
            st.session_state["strategy_result_json"] = serialized
            st.session_state["strategy_result_context"] = params
        except Exception as error:
            st.session_state["strategy_result"] = None
            st.session_state["strategy_result_json"] = None
            st.session_state["strategy_error"] = str(error)
    if st.session_state.get("strategy_error"):
        st.error(tr("本次策略运行未完成：", "This strategy run did not complete: ") + st.session_state["strategy_error"])
    result = st.session_state.get("strategy_result")
    if source == "online_history":
        render_online_downloads(result)
    if result is None:
        st.info(tr("选择日 K 来源和参数，再点击「运行四种策略」。切换语言或调整参数不会自动运行。",
                   "Choose daily data and settings, then click Run four strategies. Changing language or settings does not run a backtest."))
        return
    render_data_source(result)
    render_results(result, st.session_state["strategy_result_context"], tr)
