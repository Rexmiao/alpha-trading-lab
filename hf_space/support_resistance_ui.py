"""Session-local, explicit-run support/resistance research page.

Private OHLCV stays on the server. Only the allowlisted derived research report
is downloadable; the event chart uses a selected close path, not raw candles.
"""
from __future__ import annotations

import copy
from importlib.metadata import version
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from hf_space.intraday import make_synthetic_intraday_prices, parse_intraday_csv


LABELS = {
    "support_bounce": ("支撑反弹", "Support bounce"),
    "resistance_breakout": ("阻力突破", "Resistance breakout"),
    "breakout_retest": ("突破后回踩", "Breakout and retest"),
    "benchmark_rth": ("基准日内持有", "Benchmark RTH holding"),
}
COLORS = dict(zip(LABELS, ("#087F8C", "#C58A28", "#6554A4", "#718096")))
REPORT_KEYS = ("source", "status", "metrics", "equity", "drawdown", "signals", "events", "levels",
               "weights", "trades", "session_metrics", "coverage", "config", "lineage", "warnings")
CSV_TEMPLATE = b"timestamp,symbol,open,high,low,close,volume\n"


def run_sr_comparison(*args, **kwargs):
    from hf_space.support_resistance import run_sr_comparison as run
    return run(*args, **kwargs)


def fetch_moomoo_snapshot():
    from hf_space.snapshot_source import fetch_moomoo_snapshot as fetch
    return fetch()


def _label(value, tr):
    return tr(*LABELS.get(str(value), (str(value), str(value))))


def _remember(key):
    st.session_state["_saved_" + key] = copy.deepcopy(st.session_state[key])


def _input(kind, key, default, label, *, host=None, **kwargs):
    memory = "_saved_" + key
    if memory not in st.session_state:
        st.session_state[memory] = copy.deepcopy(st.session_state.get(key, default))
    options = kwargs.get("options")
    if options is not None and st.session_state[memory] not in options:
        st.session_state[memory] = default if default in options else options[0]
    st.session_state[key] = copy.deepcopy(st.session_state[memory])
    return getattr(host or st.sidebar, kind)(label, key=key, on_change=_remember, args=(key,), **kwargs)


def _remember_upload():
    upload = st.session_state.get("sr_upload")
    st.session_state["sr_upload_bytes"] = upload.getvalue() if upload else None
    st.session_state["sr_upload_name"] = upload.name if upload else None


def _snapshot_prices(*, refresh=False, loader=None):
    cached = st.session_state.get("sr_snapshot_cache")
    if refresh or cached is None:
        prices, provenance = (loader or fetch_moomoo_snapshot)()
        if not isinstance(prices, pd.DataFrame) or not isinstance(provenance, dict):
            raise ValueError("Invalid snapshot response")
        cached = {"prices": prices.copy(deep=True), "provenance": copy.deepcopy(provenance)}
        st.session_state["sr_snapshot_cache"] = cached
    return cached["prices"].copy(deep=True), copy.deepcopy(cached["provenance"])


def _snapshot_error(code, tr):
    if code == "NOT_CONFIGURED":
        st.info(tr("moomoo私有5分钟快照尚未连接；可上传CSV或主动选择教学数据。",
                   "The private moomoo 5-minute snapshot is not connected yet; upload CSV or explicitly choose teaching data."))
    elif code == "NOT_FOUND":
        st.info(tr("尚未找到已发布5分钟快照，可稍后刷新或上传CSV。",
                   "No published 5-minute snapshot was found; refresh later or upload CSV."))
    else:
        st.error(tr("moomoo快照暂不可用或未通过校验；本次没有替换成其他行情。",
                    "The moomoo snapshot is unavailable or failed validation; no other prices were substituted."))


def _table(rows, tr):
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows or [])
    if frame.empty:
        st.caption(tr("没有记录。", "No records."))
        return
    if "strategy" in frame:
        frame["strategy"] = frame.strategy.map(lambda value: _label(value, tr))
    values = {
        "success": ("完成", "Complete"), "failed": ("失败", "Failed"),
        "unavailable": ("不可用", "Unavailable"), "BUY": ("买入", "Buy"),
        "SELL": ("卖出", "Sell"), "support": ("支撑", "Support"),
        "resistance": ("阻力", "Resistance"), "__CASH__": ("现金", "Cash"),
        "cash": ("现金", "Cash"), "asset": ("股票", "Stock"),
        "target": ("历史参考目标", "Historical reference target"), "actual": ("实际模拟持仓", "Actual simulated holdings"),
    }
    for field in ("symbol", "status", "side", "type", "kind", "asset_kind"):
        if field in frame:
            frame[field] = frame[field].map(lambda value: tr(*values[value]) if value in values else value)
    names = {
        "strategy": ("策略", "Strategy"), "symbol": ("证券", "Symbol"),
        "session": ("美东交易日", "ET session"), "timestamp": ("事件／K线开始（UTC）", "Event / bar start (UTC)"),
        "available_at": ("可见时刻（UTC）", "Available (UTC)"),
        "source_available_at": ("来源已完成（UTC）", "Source completed (UTC)"),
        "execution_at": ("执行时刻（UTC）", "Execution (UTC)"),
        "planned_execution_at": ("计划执行（UTC）", "Planned execution (UTC)"),
        "signal_available_at": ("信号可见（UTC）", "Signal available (UTC)"),
        "source_session": ("价位来源日", "Level source session"), "level_id": ("区域版本ID", "Level version ID"),
        "event_id": ("事件ID", "Event ID"), "event": ("事件", "Event"), "type": ("区域类型", "Level type"),
        "reason": ("审计原因", "Audit reason"), "from_state": ("此前状态", "From state"),
        "to_state": ("随后状态", "To state"), "state": ("事件状态", "Event state"),
        "selected": ("进入目标候选", "Target eligible"), "status": ("状态", "Status"),
        "touch_at": ("触碰K线开始（UTC）", "Touch bar start (UTC)"), "center": ("中心价位", "Level center"),
        "lower": ("区域下沿", "Zone lower bound"), "upper": ("区域上沿", "Zone upper bound"),
        "weight": ("权重（小数）", "Weight (fraction)"), "target_weight": ("参考目标权重", "Reference target weight"),
        "quantity": ("数量（股）", "Quantity (shares)"), "qty": ("数量（股）", "Quantity (shares)"),
        "kind": ("持仓类型", "Holding kind"), "as_of": ("参考时点", "As of"), "side": ("方向", "Side"),
        "asset_kind": ("资产类型", "Asset kind"), "quantity_after_execution": ("执行后股数", "Shares after execution"),
        "reference_price": ("参考开盘价", "Reference open price"), "price": ("含点差／滑点价格", "Price incl. spread/slippage"),
        "notional": ("名义金额", "Notional"), "fee": ("费用", "Fees"),
        "spread_cost": ("半点差成本", "Half-spread cost"), "slippage_cost": ("滑点成本", "Slippage cost"),
    }
    st.dataframe(frame.rename(columns={key: tr(*pair) for key, pair in names.items()}),
                 hide_index=True, use_container_width=True)


def render_sr_math(tr):
    st.write(tr("先确定当时已知的区域，再检测事件，最后在下一根K线开盘近似执行。价位只来自紧邻前一完整XNYS常规交易日，盘中不追着价格改区域。",
                "Fix a zone using information already available, detect an event, then approximate execution at a subsequent bar open. Levels come only from the immediately preceding complete XNYS regular session and remain fixed intraday."))
    st.caption(tr("timestamp与touch_at标记UTC K线开始；available_at才是该bar完成后的信息可见时刻，真实盘中触碰顺序未知。",
                  "timestamp and touch_at mark UTC bar starts; available_at is when a completed bar makes information known. The intrabar order of touches is unknown."))
    st.latex(r"s_d=\min_{t\in d-1} L_t")
    st.latex(r"r_d=\max_{t\in d-1} H_t")
    st.latex(r"z^-(p)=p(1-b/10^4)")
    st.latex(r"z^+(p)=p(1+b/10^4)")
    st.caption(tr("b是区域半宽的bps，不是经验证的最佳参数；支撑以s、阻力以r为中心。确认等待上限以5分钟根数计。",
                  "b is the zone half-width in bps, not an optimized value. Support is centered on s and resistance on r; the confirmation limit is counted in 5-minute bars."))
    for name, zh, en in (
        ("support_bounce", "从上方进入支撑区域，之后的已完成K线收盘站回上沿，才确认反弹。", "Enter support from above; confirm a bounce only when a later completed bar closes back above the zone."),
        ("resistance_breakout", "收盘跨过阻力上沿加缓冲才确认突破，影线触碰不是收盘突破。", "Confirm a crossing by the close above the resistance zone plus buffer; a wick touch is not a closing breakout."),
        ("breakout_retest", "先确认突破，再等待后续K线回踩冻结区域并收盘守住；不能把同一根OHLC猜成先突破再回踩。", "Confirm a breakout, then wait for a later retest of the frozen zone and a holding close. One OHLC bar cannot establish a breakout-then-retest sequence."),
    ):
        st.markdown(f"**{_label(name, tr)}** — {tr(zh, en)}")
    st.latex(r"t_{fill}=t_{close}+5\mathrm{min}\times\delta")
    st.caption(tr("δ=0表示下一根开盘恰好与本根完成端点相接，假设零处理延迟；δ=1再等一根。失效、确认超时与收盘退出均按已完成bar判断，日末预定清仓。没有盘中止损、止盈或OCO。",
                  "With δ=0, the next open shares the completed bar's endpoint, assuming zero processing latency; δ=1 waits one more bar. Invalidation, confirmation expiry and closing exits use completed bars, with a scheduled daily flatten. There are no intrabar stops, profit targets or OCO orders."))
    st.write(tr("确认须发生在设置之后第1至N根内；超过N根、收盘跌破区域下沿减缓冲则取消。支撑反弹持仓在收盘到达阻力下沿时退出；三组均会在收盘跌破各自区域下沿减缓冲时退出。新的候选变化会替代尚未执行的旧目标，日末预定清仓优先。",
                "Confirmation must occur on later bars 1 through N. Expiry or a close below the zone minus buffer cancels a setup. A support-bounce position exits on a close reaching the resistance zone's lower bound; all three exit below their own zone minus buffer. A newer selection change supersedes unexecuted targets, and scheduled daily flattening takes priority."))
    st.latex(r"w_i=e_i\min\left(w_{max},\frac{1-c_{min}}{N}\right)")
    st.latex(r"\rho=(b_f+b_h+b_s)/10^4")
    st.latex(r"\mathrm{cost}=|\Delta q|\,O\,\rho")
    st.caption(tr("N=0时持有现金；整数股、先卖后买，按实际成交额计单边费用、半点差与滑点。目标上限和现金下限不能保证持有期权重不漂移。Beta是独立的市场暴露测量，本页没有Beta过滤、对冲、DL／GenAI训练或券商下单。",
                  "Hold cash when N=0. Use integer shares, sell before buying and charge fees, half-spread and slippage on actual one-way turnover. Target caps and cash floors do not prevent weight drift. Beta is a separate market-exposure measurement; this page has no Beta filter, hedge, DL/GenAI training or brokerage orders."))


def _close_path(prices):
    """Keep only chart inputs in session state; never add these to the download."""
    frame = prices.loc[:, ["timestamp", "symbol", "close"]].copy()
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["session"] = frame.timestamp.dt.tz_convert("America/New_York").dt.date.astype(str)
    frame["timestamp"] += pd.Timedelta(minutes=5)
    return frame


def _event_chart(result, tr):
    levels = pd.DataFrame(result.get("levels") or [])
    path = st.session_state.get("sr_executed_close_path")
    if levels.empty or path is None or path.empty or not {"symbol", "session"} <= set(levels):
        st.caption(tr("没有可绘制的价位事件。", "No level events are available to plot."))
        return
    symbols = sorted(levels.symbol.dropna().astype(str).unique().tolist())
    if not symbols:
        return
    symbol = _input("selectbox", "sr_chart_symbol", symbols[0], tr("查看证券", "Inspect symbol"),
                    host=st, options=symbols, index=None)
    sessions = sorted(levels.loc[levels.symbol.eq(symbol), "session"].astype(str).unique().tolist())
    session = _input("selectbox", "sr_chart_session", sessions[-1], tr("查看交易日", "Inspect session"),
                     host=st, options=sessions, index=None)
    selected = path.loc[path.symbol.eq(symbol) & path.session.eq(session)].sort_values("timestamp")
    if selected.empty:
        st.caption(tr("所选交易日没有收盘路径。", "No close path is available for this session."))
        return
    fig = go.Figure(go.Scatter(x=selected.timestamp, y=selected.close,
                              name=tr("已完成5分钟收盘", "Completed 5-minute close"), mode="lines", line=dict(color="#273444")))
    for _, row in levels.loc[levels.symbol.eq(symbol) & levels.session.astype(str).eq(session)].iterrows():
        support = str(row.get("type")) == "support"
        color = "#087F8C" if support else "#C58A28"
        if pd.notna(row.get("lower")) and pd.notna(row.get("upper")):
            fig.add_hrect(y0=float(row.lower), y1=float(row.upper), fillcolor=color, opacity=.12, line_width=0)
        if pd.notna(row.get("center")):
            fig.add_hline(y=float(row.center), line_color=color, line_dash="dot",
                          annotation_text=tr("支撑", "Support") if support else tr("阻力", "Resistance"))
    events = pd.DataFrame(result.get("events") or [])
    if not events.empty and {"symbol", "session", "available_at"} <= set(events):
        events = events.loc[events.symbol.eq(symbol) & events.session.astype(str).eq(session)].copy()
        if "event" in events:
            events = events.loc[events.event.astype(str).str.contains("confirm|entry|selected", case=False, regex=True)]
        for strategy, group in events.groupby("strategy") if "strategy" in events else []:
            times = pd.to_datetime(group.available_at, utc=True, errors="coerce")
            close_at = selected.set_index("timestamp").close
            ys = list(group.signal_close) if "signal_close" in group else [close_at.get(time, float("nan")) for time in times]
            fig.add_trace(go.Scatter(x=times, y=ys, mode="markers", marker=dict(symbol="circle", size=8, color=COLORS.get(strategy)),
                                     name=_label(strategy, tr) + tr(" · 确认", " · confirmation")))
    trades = pd.DataFrame(result.get("trades") or [])
    if not trades.empty and {"symbol", "session", "execution_at"} <= set(trades):
        trades = trades.loc[trades.symbol.eq(symbol) & trades.session.astype(str).eq(session)]
        for strategy, group in trades.groupby("strategy") if "strategy" in trades else []:
            field = "reference_price" if "reference_price" in group else "price" if "price" in group else None
            if field:
                fig.add_trace(go.Scatter(x=pd.to_datetime(group.execution_at, utc=True), y=group[field], mode="markers",
                                         marker=dict(symbol="x", size=9, color=COLORS.get(strategy)),
                                         name=_label(strategy, tr) + tr(" · 纸面成交", " · proxy fill")))
    fig.update_layout(template="plotly_white", height=410, margin=dict(l=12, r=12, t=48, b=12),
                      title=tr("冻结区域、确认与执行", "Frozen zones, confirmations and execution"), legend_title_text="")
    fig.update_xaxes(title_text=tr("UTC时刻", "UTC time"))
    fig.update_yaxes(title_text=tr("研究价格", "Research price"))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(tr("仅绘制所选日的收盘路径和派生区域／事件，不展示完整OHLCV；圆点是确认，叉号是实际纸面成交，确认不保证成交。",
                  "Only the selected day's close path and derived zones/events are plotted, without complete OHLCV. Circles mark confirmations and crosses actual proxy fills; confirmation does not guarantee execution."))


def _results(result, context, tr):
    source = result.get("source")
    if source == "synthetic":
        st.warning(tr("上次运行使用明确选择的合成教学行情，属于虚构资产。", "The last run used explicitly selected synthetic teaching prices for fictional assets."))
    elif source == "moomoo_snapshot":
        st.info(tr("结果来自已发布moomoo私有5分钟快照；公开研究结果，原始OHLCV不提供下载。", "Results use a published private moomoo 5-minute snapshot. Research results are public; raw OHLCV cannot be downloaded."))
    else:
        st.info(tr("结果来自访客CSV；行情来源和复权口径由上传者确认。", "Results use visitor CSV; the uploader must verify provenance and adjustment basis."))
    st.caption(tr("当前展示上次运行：", "Displayed settings from the last run: ")
               + f"{context['benchmark']} · " + tr("区域半宽", "zone half-width ") + f"{context['band_bps']} bps · "
               + tr("确认上限", "confirmation limit ") + str(context["confirmation_bars"])
               + tr("根", " bars") + f" · {context['cost_bps']}+{context['half_spread_bps']}+{context['slippage_bps']} bps"
               + tr(" · 额外延迟", " · extra delay ") + str(context["execution_delay_bars"])
               + tr("；修改设置须重新运行。", ". Run again to apply changes."))
    symbols = (result.get("lineage") or {}).get("data", {}).get("symbols") or []
    if not symbols:
        symbols = sorted({row["symbol"] for row in result.get("levels") or [] if row.get("symbol")})
    stock_count = len(set(symbols) - {context["benchmark"]})
    if stock_count:
        stock_limit = min(1 - context["cash_floor"], stock_count * context["max_weight"])
        st.caption(tr(
            f"本次股票池{stock_count}只：即使全部入选，股票目标也最多{stock_limit:.0%}、现金至少{1-stock_limit:.0%}。基准日内目标100%，资金暴露未匹配，收益差异不能直接解释为alpha。",
            f"This run has {stock_count} stocks: even if all qualify, target stocks are at most {stock_limit:.0%} and cash at least {1-stock_limit:.0%}. The benchmark targets 100% intraday exposure. Exposures are not matched, so return differences are not direct evidence of alpha."))
    if result.get("status") != "success":
        st.warning(tr("本次研究未全部完成；查看组别状态和数据审计。没有用其他行情或策略替代。",
                      "This study did not fully complete; inspect group status and data audit. No substitute data or strategy were used."))


def _render_tabs(result, context, tr):
    overview, events_tab, math_tab, audit_tab = st.tabs([
        tr("收益与风险", "Returns and risk"), tr("区域与事件审计", "Zones and event audit"),
        tr("数学原理", "Mathematical principles"), tr("数据审计与下载", "Data audit and download")])
    with overview:
        if result is None:
            st.info(tr("选择来源与参数后点击运行。切换语言、页面或参数不自动重算。", "Choose data and settings, then Run. Language, page or parameter changes do not recompute results."))
        else:
            metrics = pd.DataFrame(result.get("metrics") or [])
            if not metrics.empty and "strategy" in metrics:
                view = pd.DataFrame({tr("策略", "Strategy"): metrics.strategy.map(lambda value: _label(value, tr))})
                if "status" in metrics:
                    view[tr("状态", "Status")] = metrics.status.map(lambda value: tr("完成", "Complete") if value == "success" else tr("未完成", "Incomplete"))
                for key, zh, en, scale in (
                    ("total_return", "累计收益 %", "Total return %", 100),
                    ("max_drawdown", "最大回撤 %", "Max drawdown %", 100),
                    ("sharpe", "日收益夏普", "Daily-return Sharpe", 1),
                    ("annualized_volatility", "年化日收益波动 %", "Annualized daily-return volatility %", 100),
                    ("total_cost", "总模拟成本", "Total simulated costs", 1),
                    ("trade_count", "成交笔数", "Executed trades", 1),
                    ("n_sessions", "评估交易日", "Evaluation sessions", 1),
                ):
                    if key in metrics:
                        view[tr(zh, en)] = pd.to_numeric(metrics[key], errors="coerce") * scale
                st.dataframe(view, hide_index=True, use_container_width=True)
            equity = pd.DataFrame(result.get("equity") or [])
            if not equity.empty and {"timestamp", "strategy", "equity", "drawdown"} <= set(equity):
                for field, zh, en in (("equity", "含成本纸面权益", "Proxy equity after costs"), ("drawdown", "模拟回撤", "Simulated drawdown")):
                    fig = px.line(equity.sort_values(["strategy", "timestamp"]), x="timestamp", y=field,
                                  color="strategy", color_discrete_map=COLORS, title=tr(zh, en))
                    for trace in fig.data:
                        trace.name = _label(trace.name, tr)
                    fig.update_layout(template="plotly_white", height=360, margin=dict(l=12, r=12, t=48, b=12), legend_title_text="")
                    fig.update_xaxes(title_text=tr("UTC时刻", "UTC time"))
                    fig.update_yaxes(title_text=tr("权益", "Equity") if field == "equity" else tr("回撤", "Drawdown"),
                                     tickformat=".0%" if field == "drawdown" else None)
                    st.plotly_chart(fig, use_container_width=True)
            st.caption(tr("没有触发时持有现金、零成交是合法结果。少于20个评估日不报告夏普或年化值；基准也是同评估日的日内持有代理，不等于隔夜买入持有，且不受股票仓位上限与现金下限约束。",
                          "Cash and zero trades are valid when no events qualify. Sharpe and annualized values are not reported below 20 evaluation sessions. The benchmark is a same-session holding proxy, not overnight buy-and-hold, and is exempt from stock caps and cash floors."))
    with events_tab:
        if result is None:
            st.caption(tr("运行后显示冻结区域、事件路径和成交审计。", "Run to inspect frozen zones, event paths and proxy execution audit."))
        else:
            _event_chart(result, tr)
            for key, zh, en in (("levels", "冻结区域", "Frozen zones"), ("events", "事件状态与确认", "Event states and confirmations"),
                                 ("trades", "实际纸面成交", "Actual proxy trades"), ("weights", "参考目标与期末现金", "Reference targets and final cash")):
                with st.expander(tr(zh, en)):
                    _table(result.get(key), tr)
            st.caption(tr("预定日末清仓后，期末实际持仓应为现金；日内参考目标有自己的时点，不能冒充期末持仓或券商订单。touch_at仅为触碰K线开始，真实盘中触碰时刻未知，事件须等该bar完成才可见。状态码保留便于审计。",
                          "After scheduled daily flattening, final actual holdings should be cash. Intraday targets have their own timestamps and are not final holdings or brokerage orders. touch_at identifies a bar start, not a known intrabar touch instant; events become available only when the bar completes. State codes are retained for audit."))
    with math_tab:
        render_sr_math(tr)
    with audit_tab:
        if result is None:
            st.caption(tr("运行后提供覆盖范围、来源指纹和研究JSON。", "Run to obtain coverage, provenance fingerprints and research JSON."))
        else:
            st.write(tr("共同日、前日价位与排除原因", "Common sessions, prior-session levels and exclusions"))
            st.json(result.get("coverage") or {})
            st.caption(tr("缺K线的整日不补价，且评估日须有紧邻前一交易所日的完整价位来源；第一日仅预热。完整日筛选使用事后质量信息，不是实盘断线处理。至少需要两个可评估交易日；短历史只够工程验证，不能判断策略稳定性。",
                          "Do not fill missing bars. Each evaluation day requires a complete immediately preceding exchange session for levels; the first day is warmup only. Whole-session screening uses retrospective quality information, not a live outage policy. At least two evaluation days are required; short histories support engineering checks rather than strategy stability claims."))
            with st.expander(tr("参数、来源与可复现信息", "Settings, provenance and reproducibility")):
                st.json({"settings": context, "config": result.get("config") or {}, "lineage": result.get("lineage") or {},
                         "engine_warning_codes": result.get("warnings") or []})
            st.download_button(tr("下载支撑阻力研究JSON", "Download support/resistance research JSON"),
                               st.session_state["sr_result_json"], file_name="support-resistance-research.json", mime="application/json",
                               key="sr_download_report", use_container_width=True)
            st.caption(tr("JSON只包含派生研究结果、事件与来源指纹，不含完整原始OHLCV；切换语言不改变下载内容。", "JSON contains derived research results, events and source fingerprints, without complete raw OHLCV. Language changes do not alter the download."))


def render_sr_page(tr, *, snapshot_loader=None):
    st.title(tr("5分钟支撑与阻力实验室", "5-minute Support & Resistance Lab"))
    st.write(tr("以前一完整交易日高低点形成冻结区域，比较支撑反弹、阻力突破和突破后回踩。", "Build frozen zones from the prior complete session's high and low; compare support bounce, resistance breakout and breakout-retest."))
    st.caption(tr("独立研究与纸面成交；不连接券商、训练模型或自动提交订单。", "Separate research and proxy fills; no brokerage connection, model training or automatic orders."))
    st.sidebar.subheader(tr("支撑阻力数据与参数", "Support/resistance data and settings"))
    sources = {"moomoo_snapshot": tr("已发布moomoo 5分钟快照", "Published moomoo 5-minute snapshot"),
               "uploaded_csv": tr("访客5分钟CSV", "Visitor 5-minute CSV"),
               "synthetic": tr("合成教学数据", "Synthetic teaching data")}
    source = _input("radio", "sr_source", "moomoo_snapshot", tr("行情来源", "Price source"), options=list(sources),
                    index=None, format_func=sources.__getitem__)
    if source == "moomoo_snapshot":
        benchmark = "SPY"
        if st.sidebar.button(tr("获取／刷新私有快照", "Fetch / refresh private snapshot"), key="sr_snapshot_refresh"):
            try:
                with st.spinner(tr("正在获取并核对5分钟快照。", "Fetching and checking the 5-minute snapshot.")):
                    _snapshot_prices(refresh=True, loader=snapshot_loader)
                st.session_state["sr_snapshot_error"] = None
                if st.session_state.get("sr_error_is_snapshot"):
                    st.session_state["sr_error"] = None
            except Exception as error:
                st.session_state["sr_snapshot_cache"] = None
                st.session_state["sr_snapshot_error"] = getattr(error, "code", "SOURCE_UNAVAILABLE")
        if st.session_state.get("sr_snapshot_error"):
            _snapshot_error(st.session_state["sr_snapshot_error"], tr)
        cached = st.session_state.get("sr_snapshot_cache")
        if cached:
            meta = cached["provenance"]
            used = ((st.session_state.get("sr_result") or {}).get("lineage") or {}).get("external_data") or {}
            same = used.get("revision") == meta.get("revision") and used.get("snapshot_id") == meta.get("snapshot_id")
            st.sidebar.caption(tr("会话快照截至：", "Session snapshot as of: ") + str(meta.get("as_of", "—")))
            st.sidebar.caption(tr("此快照用于当前结果。", "This snapshot is used by the displayed result.") if same else
                               tr("此快照尚未用于当前结果；刷新不重算。", "This snapshot is not used by the displayed result; refresh does not recompute."))
        st.sidebar.caption(tr("首次运行取数；参数比较复用同一revision。原始行情仅在服务端，不开放下载。", "First Run fetches prices; parameter comparisons reuse one revision. Raw prices stay server-side without download."))
    elif source == "uploaded_csv":
        benchmark = _input("text_input", "sr_benchmark", "SPY", tr("基准代码", "Benchmark symbol")).strip().upper()
        st.sidebar.file_uploader("5-minute CSV", type=["csv"], key="sr_upload", on_change=_remember_upload)
        if st.session_state.get("sr_upload_name"):
            st.sidebar.caption(tr("会话文件：", "Session file: ") + st.session_state["sr_upload_name"])
        st.sidebar.caption(tr("UTC K线开始；七列timestamp,symbol,open,high,low,close,volume。≤8MiB／50000行，1–12只股票加基准，仅完整美股RTH。建议至少3个连续交易日。", "UTC bar starts; columns timestamp,symbol,open,high,low,close,volume. Up to 8 MiB / 50,000 rows, 1–12 stocks plus benchmark, complete US RTH only. Supply at least three consecutive sessions."))
    else:
        benchmark = "BENCH"
        st.sidebar.caption(tr("虚构资产，仅用于理解机制；不会替代真实数据失败。", "Fictional assets for understanding mechanisms; never substituted for failed observed data."))
    band = _input("number_input", "sr_band", 10, tr("区域半宽（bps）", "Zone half-width (bps)"), min_value=1, max_value=200, step=1)
    confirmation = _input("number_input", "sr_confirmation", 12, tr("确认等待上限（5分钟根数）", "Confirmation limit (5-minute bars)"), min_value=1, max_value=60, step=1)
    with st.sidebar.expander(tr("高级设置", "Advanced settings")) as advanced:
        buffer = _input("number_input", "sr_buffer", 0, tr("突破缓冲（bps）", "Breakout buffer (bps)"), min_value=0, max_value=100, step=1, host=advanced)
        delays = {0: tr("0：下一根开盘", "0: next-bar open"), 1: tr("1：额外等一根", "1: wait one extra bar")}
        delay = _input("selectbox", "sr_delay", 0, tr("额外执行延迟", "Extra execution delay"), options=[0, 1], index=None, format_func=delays.__getitem__, host=advanced)
        fee = _input("slider", "sr_cost", 10, tr("单边费用（bps）", "Per-side fees (bps)"), min_value=0, max_value=50, step=1, host=advanced)
        spread = _input("slider", "sr_spread", 1, tr("单边半点差（bps）", "Per-side half-spread (bps)"), min_value=0, max_value=50, step=1, host=advanced)
        slip = _input("slider", "sr_slippage", 1, tr("单边滑点（bps）", "Per-side slippage (bps)"), min_value=0, max_value=50, step=1, host=advanced)
        cap = _input("slider", "sr_cap", 20, tr("单股目标上限 %", "Per-stock target cap %"), min_value=10, max_value=100, step=5, host=advanced)
        cash = _input("slider", "sr_cash", 20, tr("目标现金下限 %", "Target cash floor %"), min_value=0, max_value=80, step=5, host=advanced)
        seed = _input("number_input", "sr_seed", 42, tr("教学数据随机种子", "Teaching-data random seed"), min_value=0, max_value=2147483647, step=1, host=advanced)
        st.caption(tr("初始资金100000；以上为研究起点，未按收益选优。", "Initial capital 100,000; these are research starting points, not optimized parameters."))
        st.download_button(tr("下载空白5分钟CSV模板", "Download blank 5-minute CSV template"), CSV_TEMPLATE,
                           file_name="support-resistance-template.csv", mime="text/csv", key="sr_download_template", use_container_width=True)
    missing = source == "uploaded_csv" and not st.session_state.get("sr_upload_bytes")
    if missing:
        st.sidebar.info(tr("请先上传5分钟CSV。", "Upload a 5-minute CSV first."))
    if st.sidebar.button(tr("运行三种支撑阻力策略", "Run three support/resistance strategies"), key="sr_run", type="primary", disabled=missing, use_container_width=True):
        st.session_state["sr_error"] = None
        st.session_state["sr_error_is_snapshot"] = False
        params = {"benchmark": benchmark, "source": source, "band_bps": int(band), "breakout_buffer_bps": int(buffer),
                  "confirmation_bars": int(confirmation), "execution_delay_bars": int(delay), "max_weight": cap / 100,
                  "cash_floor": cash / 100, "cost_bps": int(fee), "half_spread_bps": int(spread), "slippage_bps": int(slip), "initial_cash": 100000.}
        snapshot_stage = False
        try:
            external = None
            with st.spinner(tr("正在核对前日价位并运行事件与成交。", "Checking prior-session levels and simulating events and proxy fills.")):
                if source == "moomoo_snapshot":
                    snapshot_stage = True
                    prices, external = _snapshot_prices(loader=snapshot_loader)
                    snapshot_stage = False
                    st.session_state["sr_snapshot_error"] = None
                elif source == "synthetic":
                    prices = make_synthetic_intraday_prices(seed=int(seed))
                else:
                    prices = parse_intraday_csv(st.session_state["sr_upload_bytes"], benchmark=benchmark)
                result = run_sr_comparison(prices, **params)
                if not isinstance(result, dict) or not {"status", "metrics", "equity", "lineage"} <= set(result):
                    raise ValueError("Incomplete support/resistance report")
                report = {key: copy.deepcopy(result[key]) for key in REPORT_KEYS if key in result}
                # Per-bar closes would reconstruct the private close path across
                # all sessions. Sparse event/trade reference prices remain audit
                # evidence; the chart's selected close path stays session-only.
                report["signals"] = [{key: value for key, value in row.items() if key != "signal_close"}
                                     for row in report.get("signals") or []]
                report["source"] = source
                report.setdefault("lineage", {})["synthetic_seed"] = int(seed) if source == "synthetic" else None
                if external is not None:
                    report["lineage"]["external_data"] = external
                report["lineage"].setdefault("ui_dependencies", {}).update({name: version(name) for name in ("streamlit", "plotly", "pyarrow")})
                serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
                close_path = _close_path(prices)
            st.session_state["sr_result"] = report
            st.session_state["sr_result_json"] = serialized
            st.session_state["sr_result_context"] = params
            st.session_state["sr_executed_close_path"] = close_path
        except Exception as error:
            for key in ("sr_result", "sr_result_json", "sr_result_context", "sr_executed_close_path"):
                st.session_state[key] = None
            st.session_state["sr_error_is_snapshot"] = snapshot_stage
            st.session_state["sr_error"] = getattr(error, "code", "SOURCE_UNAVAILABLE") if snapshot_stage else "RUN_FAILED"
            if snapshot_stage:
                st.session_state["sr_snapshot_cache"] = None
    if st.session_state.get("sr_error"):
        if st.session_state.get("sr_error_is_snapshot"):
            _snapshot_error(st.session_state["sr_error"], tr)
        else:
            st.error(tr("本次支撑阻力研究未完成：请核对CSV、基准、区域宽度（支撑与阻力带不能重叠），以及至少两个可评估日所需的完整连续交易日。没有替换数据或复制其他结果。", "This support/resistance study did not complete. Check CSV, benchmark, zone width (support and resistance bands must not overlap), and complete consecutive sessions allowing at least two evaluation days. No data or results were substituted."))
    result = st.session_state.get("sr_result")
    context = st.session_state.get("sr_result_context")
    if result is not None:
        _results(result, context, tr)
    _render_tabs(result, context, tr)
