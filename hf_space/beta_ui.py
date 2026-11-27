"""Explicit-run, bilingual Beta research UI; session-local data and results.

The page never connects to a brokerage. Published daily prices stay inside the
server session; only the allowlisted research report can be downloaded.
"""
from __future__ import annotations

import copy
from importlib.metadata import version
import json
import re

import pandas as pd
import plotly.express as px
import streamlit as st


LABELS = {
    "high_beta": ("高Beta组合", "High-Beta basket"),
    "low_beta": ("低Beta组合", "Low-Beta basket"),
    "equal_weight": ("全池等权", "Universe equal weight"),
    "spy_80": ("80% SPY＋20%现金", "80% SPY + 20% cash"),
    "spy_100": ("100% SPY", "100% SPY"),
}
COLORS = dict(zip(LABELS, ("#C58A28", "#087F8C", "#6554A4", "#718096", "#273444")))
REPORT_KEYS = ("source", "status", "metrics", "equity", "drawdown", "estimates", "beta_history", "weights",
               "latest_targets", "rebalances", "trades", "coverage", "config", "lineage", "warnings")
CSV_TEMPLATE = b"date,symbol,open,high,low,close,volume\n"


def run_beta_comparison(*args, **kwargs):
    from hf_space.beta import run_beta_comparison as run
    return run(*args, **kwargs)


def parse_beta_csv(*args, **kwargs):
    from hf_space.beta import parse_beta_csv as parse
    return parse(*args, **kwargs)


def fetch_moomoo_daily_snapshot():
    from hf_space.daily_snapshot_source import fetch_moomoo_daily_snapshot as fetch
    return fetch()


def _label(value, tr):
    return tr(*LABELS.get(str(value), (str(value), str(value))))


def _remember(key):
    st.session_state["_saved_" + key] = copy.deepcopy(st.session_state[key])


def _input(kind, key, default, text, **kwargs):
    memory = "_saved_" + key
    if memory not in st.session_state:
        st.session_state[memory] = copy.deepcopy(st.session_state.get(key, default))
    st.session_state[key] = copy.deepcopy(st.session_state[memory])
    return getattr(st.sidebar, kind)(text, key=key, on_change=_remember, args=(key,), **kwargs)


def _remember_upload():
    upload = st.session_state.get("beta_upload")
    st.session_state["beta_upload_bytes"] = upload.getvalue() if upload else None
    st.session_state["beta_upload_name"] = upload.name if upload else None


def _snapshot_prices(*, refresh=False, loader=None):
    cached = st.session_state.get("beta_snapshot_cache")
    if refresh or cached is None:
        prices, provenance = (loader or fetch_moomoo_daily_snapshot)()
        if not isinstance(prices, pd.DataFrame) or not isinstance(provenance, dict):
            raise ValueError("Invalid snapshot loader response")
        cached = {"prices": prices.copy(deep=True), "provenance": copy.deepcopy(provenance)}
        st.session_state["beta_snapshot_cache"] = cached
    return cached["prices"].copy(deep=True), copy.deepcopy(cached["provenance"])


def _snapshot_error(code, tr):
    if code == "NOT_CONFIGURED":
        st.info(tr("已发布的moomoo日K快照尚未连接；可使用访客CSV。", "The published moomoo daily snapshot is not connected yet; visitor CSV is available."))
    elif code == "NOT_FOUND":
        st.info(tr("尚未找到已发布的moomoo日K快照；可稍后刷新或使用访客CSV。", "No published moomoo daily snapshot was found; refresh later or use visitor CSV."))
    else:
        st.error(tr("moomoo日K快照暂不可用或未通过校验。本次没有替换其他行情。", "The moomoo daily snapshot is unavailable or failed validation. No other prices were substituted."))


def _table(frame, tr):
    if frame.empty:
        st.caption(tr("没有记录。", "No records."))
        return
    frame = frame.copy()
    if "strategy" in frame:
        frame["strategy"] = frame.strategy.map(lambda item: _label(item, tr))
    if "symbol" in frame:
        frame.loc[frame.symbol.eq("__CASH__"), "symbol"] = tr("现金", "Cash")
    if "status" in frame:
        statuses = {"success": tr("完成", "Complete"), "unavailable": tr("不可用", "Unavailable"), "failed": tr("失败", "Failed")}
        frame["status"] = frame.status.map(lambda value: statuses.get(value, value))
    if "side" in frame:
        frame["side"] = frame.side.map(lambda value: {"BUY": tr("买入", "Buy"), "SELL": tr("卖出", "Sell")}.get(value, value))
    if "kind" in frame:
        frame["kind"] = frame.kind.map(lambda value: {"asset": tr("股票", "Stock"), "cash": tr("现金", "Cash")}.get(value, value))
    names = {
        "strategy": ("策略", "Strategy"), "symbol": ("证券", "Symbol"),
        "date": ("日期", "Date"), "as_of": ("参考时点", "As of"),
        "signal_date": ("信号日期", "Signal date"), "execution_date": ("模拟执行日期", "Proxy execution date"),
        "beta": ("估计Beta", "Estimated Beta"), "predicted_beta": ("事前组合Beta", "Ex-ante portfolio Beta"),
        "correlation": ("市场相关性", "Market correlation"), "r_squared": ("R²", "R²"),
        "standard_error": ("Beta标准误", "Beta standard error"), "nobs": ("收益样本数", "Return observations"),
        "annual_vol": ("年化总波动（小数）", "Annual total volatility (fraction)"),
        "residual_vol": ("残差波动（小数）", "Residual volatility (fraction)"),
        "weight": ("权重（小数）", "Weight (fraction)"), "quantity": ("数量（股）", "Quantity (shares)"),
        "kind": ("类型", "Kind"), "status": ("状态", "Status"), "reason": ("原因", "Reason"),
        "side": ("买卖方向", "Side"), "price": ("OHLC代理价", "OHLC proxy price"),
        "cost": ("模拟成本", "Simulated cost"), "eligible": ("符合历史要求", "History eligible"),
    }
    st.dataframe(frame.rename(columns={key: tr(*pair) for key, pair in names.items()}),
                 hide_index=True, use_container_width=True)


def render_beta_math(tr):
    st.write(tr("Beta衡量与基准共同变化的敏感度；总波动和市场相关性共同决定Beta。波动很大的股票也可能只有低Beta。", "Beta measures sensitivity to benchmark movements. Total volatility and market correlation jointly determine Beta; a very volatile stock can still have low Beta."))
    st.latex(r"S_{im}=\sum_s(r_{i,s}-\bar r_i)(r_{m,s}-\bar r_m)")
    st.latex(r"S_{mm}=\sum_s(r_{m,s}-\bar r_m)^2")
    st.latex(r"\hat\beta_i=\frac{S_{im}}{S_{mm}}")
    st.latex(r"\hat\beta_i=\rho_{i,m}\frac{\sigma_i}{\sigma_m}")
    st.write(tr("使用带截距、中心化OLS，窗口126或252个共同日收益；每个窗口需要额外一根价格。没有无风险利率输入，当前是原始收益市场模型，截距不作为Jensen Alpha展示。", "Use centered OLS with an intercept over 126 or 252 aligned daily returns, requiring one extra price. Without a risk-free-rate input, this is a raw-return market model; its intercept is not presented as Jensen alpha."))
    st.latex(r"r_{i,s}=a_i+\beta_i r_{m,s}+\epsilon_{i,s}")
    st.latex(r"\hat\beta_{p,t}=\sum_i w_{i,t}\hat\beta_{i,t}")
    st.write(tr("高／低Beta各选当时合格股票的最高／最低20%，至少20只合格股。每月收盘形成信号，下一个交易日开盘以OHLC代理换仓；首次评估开盘前也只用此前已知收盘。", "Select the highest/lowest 20% of stocks eligible at the time, with at least 20 eligible stocks. Form monthly signals at the close and use the next session's open as a fill proxy; initial formation also uses only prior closes."))
    st.write(tr("三组股票组合目标80%股票、至少20%现金，单股上限20%；80%和100% SPY对照豁免单股上限。全部采用整数股、先卖后买并扣单边成本，期间权重可漂移。", "The three stock baskets target 80% stocks and at least 20% cash, with a 20% per-stock cap. The 80% and 100% SPY controls are exempt from that cap. All use integer shares, sell before buying and incur per-side costs; weights drift between trades."))
    st.caption(tr("事前Beta用于描述持仓暴露，事后实现Beta只用于评价。低Beta不是低波动，Beta不保证未来涨跌；本页没有Beta中性对冲、BAB、杠杆或券商订单。", "Ex-ante Beta describes held exposure; ex-post realized Beta is evaluation only. Low Beta is not low volatility, and Beta does not guarantee future moves. This page has no Beta-neutral hedge, BAB, leverage or brokerage orders."))


def _warning(value, tr):
    pairs = {
        "Historical thematic/visitor universe, not a reconstructed historical investable market or S&P index.": "使用历史主题／访客股票池，没有重建历史可投资市场或S&P指数。",
        "Research price returns, not independently verified total returns. Cash earns zero; intercept is not Jensen alpha.": "使用研究价格收益，未独立核验总收益。现金收益为0；截距不称为Jensen Alpha。",
        "Classical OLS standard errors assume uncorrelated homoskedastic residuals; they are descriptive, not robust inference.": "经典OLS标准误假设残差不相关且同方差；仅作描述，不是稳健推断。",
        "Next-session open is an OHLC execution proxy. Market impact, order-book depth and actual fills are not modelled.": "下一交易日开盘是OHLC成交代理，未模拟市场冲击、盘口深度或真实券商成交。",
        "Stock/cash limits apply at rebalance targets; actual weights drift between rebalances.": "股票与现金限制作用于调仓目标，实际权重在两次调仓间会漂移。",
        "No signal Rank IC, leverage, shorting, Beta-cap or live orders are implemented by this comparison.": "本对照没有信号Rank IC、杠杆、做空、Beta上限或实盘订单。",
        "Visitor-supplied prices have not been independently verified.": "访客提供的行情尚未独立核验。",
    }
    text = str(value)
    match = re.fullmatch(r"(\d+) supplied close-to-close moves exceed 30%; retained for review without automatic repair\.", text)
    if match:
        return tr(f"源行情有{match[1]}次收盘到收盘变动超过30%；保留待核查，没有自动修价。", text)
    return tr(pairs.get(text, text), text)


def render_beta_results(result, context, tr):
    source = result.get("source")
    if source == "moomoo_daily_snapshot":
        st.info(tr("结果使用已发布的moomoo私有日K快照；公开研究结果，不提供原始行情下载。", "Results use a published private moomoo daily snapshot. Research results are public; raw prices cannot be downloaded."))
    else:
        st.info(tr("结果使用访客上传的日K CSV；上传者须确认数据来源与复权口径。", "Results use a visitor-uploaded daily CSV; the uploader must verify provenance and adjustment basis."))
    st.caption(tr("当前展示上次运行：", "Displayed settings are from the last run: ")
               + f"{context['benchmark']} · Beta={context['beta_window']} · "
               + tr("评估", "evaluation ") + str(context["test_sessions"]) + tr("交易日", " sessions")
               + f" · {context['cost_bps']} bps"
               + tr("；修改左侧设置后须重新运行。", ". Run again to apply changed settings."))
    if result.get("status") != "success":
        st.warning(tr("本次对照未全部完成；仅显示实际完成的组，不显示替代净值。请查看各组状态、数据审计和运行提示。", "Not every comparison completed. Only completed groups are shown, without substitute equity curves; inspect group status, Data audit and run messages."))
    overview, measurement, mathematics, audit = st.tabs([
        tr("收益与风险", "Returns and risk"), tr("Beta测量与权重", "Beta measurements and weights"),
        tr("数学原理", "Mathematical principles"), tr("数据审计与下载", "Data audit and download")])
    with overview:
        metrics = pd.DataFrame(result.get("metrics") or [])
        if not metrics.empty and "strategy" in metrics:
            view = pd.DataFrame({tr("策略", "Strategy"): metrics.strategy.map(lambda value: _label(value, tr))})
            if "status" in metrics:
                view[tr("状态", "Status")] = metrics.status.map(lambda value: tr("完成", "Complete") if value == "success" else tr("未完成", "Incomplete"))
            for key, zh, en, scale in (
                ("total_return", "累计收益 %", "Total return %", 100),
                ("annual_return", "年化收益 %", "Annualized return %", 100),
                ("annual_vol", "年化波动 %", "Annualized volatility %", 100),
                ("sharpe", "夏普比率", "Sharpe ratio", 1),
                ("max_drawdown", "最大回撤 %", "Max drawdown %", 100),
                ("realized_beta", "事后实现Beta", "Ex-post realized Beta", 1),
                ("realized_r_squared", "事后R²", "Ex-post R²", 1),
                ("realized_beta_standard_error", "事后Beta标准误", "Ex-post Beta standard error", 1),
                ("realized_beta_nobs", "事后Beta样本数", "Ex-post Beta observations", 1),
                ("latest_predicted_beta", "期末事前Beta", "Final ex-ante Beta", 1),
                ("total_costs", "总模拟成本", "Total simulated costs", 1),
                ("trade_count", "成交笔数", "Executed trades", 1),
                ("turnover", "名义换手", "Notional turnover", 1),
            ):
                if key in metrics:
                    view[tr(zh, en)] = pd.to_numeric(metrics[key], errors="coerce") * scale
            st.dataframe(view, hide_index=True, use_container_width=True)
        frame = pd.DataFrame(result.get("equity") or [])
        if not frame.empty and {"date", "strategy", "equity", "drawdown"} <= set(frame):
            for field, zh, en, percent in (("equity", "含成本模拟权益", "Simulated equity after costs", False),
                                            ("drawdown", "模拟回撤", "Simulated drawdown", True)):
                fig = px.line(frame.sort_values(["strategy", "date"]), x="date", y=field, color="strategy",
                              color_discrete_map=COLORS, title=tr(zh, en))
                for trace in fig.data:
                    trace.name = _label(trace.name, tr)
                fig.update_layout(template="plotly_white", height=370, margin=dict(l=12, r=12, t=52, b=12), legend_title_text="")
                fig.update_xaxes(title_text=tr("交易日", "Trading session"))
                fig.update_yaxes(title_text=tr("权益", "Equity") if not percent else tr("回撤", "Drawdown"), tickformat=".0%" if percent else None)
                st.plotly_chart(fig, use_container_width=True)
            if "predicted_beta" in frame and frame.predicted_beta.notna().any():
                fig = px.line(frame, x="date", y="predicted_beta", color="strategy", color_discrete_map=COLORS,
                              title=tr("持仓的事前估计Beta", "Ex-ante estimated Beta of holdings"))
                for trace in fig.data:
                    trace.name = _label(trace.name, tr)
                fig.update_layout(template="plotly_white", height=340, legend_title_text="")
                fig.update_xaxes(title_text=tr("交易日", "Trading session"))
                fig.update_yaxes(title_text=tr("事前Beta", "Ex-ante Beta"))
                st.plotly_chart(fig, use_container_width=True)
        st.caption(tr("五组共享评估日期和所选单边费用。80% SPY对照资金暴露，100% SPY是完整市场基准，二者均不受单股20%上限。期末只估值，不虚构平仓；现金收益为0。", "All five share evaluation dates and selected per-side costs. The 80% SPY control matches target cash allocation; 100% SPY is a full-market reference. Neither has the stock 20% cap. The final close is valuation only, without a fabricated exit; cash earns zero."))
    with measurement:
        estimates = pd.DataFrame(result.get("estimates") or [])
        st.subheader(tr("最新个股测量", "Latest stock measurements"))
        _table(estimates, tr)
        if not estimates.empty and {"beta", "annual_vol", "symbol"} <= set(estimates):
            plot = estimates.copy()
            plot["annual_vol_pct"] = pd.to_numeric(plot.annual_vol, errors="coerce") * 100
            plot["beta"] = pd.to_numeric(plot.beta, errors="coerce")
            plot = plot.dropna(subset=["annual_vol_pct", "beta"])
            if not plot.empty:
                fig = px.scatter(plot, x="beta", y="annual_vol_pct", hover_name="symbol",
                                 title=tr("市场Beta与总波动是两项测量", "Market Beta and total volatility are distinct measurements"),
                                 labels={"beta": tr("估计Beta", "Estimated Beta"), "annual_vol_pct": tr("年化总波动 %", "Annual total volatility %")})
                fig.update_layout(template="plotly_white", height=370)
                st.plotly_chart(fig, use_container_width=True)
        st.caption(tr("标准误描述估计不确定性，不是未来收益置信区间。相对股票池排名低也不保证Beta小于1。", "Standard errors describe estimation uncertainty, not confidence intervals for future returns. A low rank within the universe need not imply Beta below one."))
        st.subheader(tr("期末实际模拟持仓", "Final actual simulated holdings"))
        _table(pd.DataFrame(result.get("weights") or []), tr)
        st.subheader(tr("最后一次调仓的参考目标", "Reference targets at the latest rebalance"))
        _table(pd.DataFrame(result.get("latest_targets") or []), tr)
        st.caption(tr("参考目标与期末实际持仓的日期和含义不同；均不是券商账户仓位或下单指令。", "Reference targets and final holdings have different dates and meanings; neither is a brokerage position or order instruction."))
    with mathematics:
        render_beta_math(tr)
    with audit:
        for warning in result.get("warnings") or []:
            st.warning(_warning(warning, tr))
        st.write(tr("数据覆盖及资格排除", "Data coverage and eligibility exclusions"))
        coverage = result.get("coverage") or {}
        if isinstance(coverage, list):
            _table(pd.DataFrame(coverage), tr)
        else:
            st.json(coverage)
        st.caption(tr("主题池并非历史完整可投资股票池；交易成本为所选bps近似，未模拟真实盘口、市场冲击或券商部分成交。调参数属于探索，不能当作新样本外证据。", "The thematic universe is not a historical investable universe. Selected bps approximate costs without order books, market impact or brokerage partial fills. Parameter exploration is not fresh out-of-sample evidence."))
        with st.expander(tr("来源、参数与可复现信息", "Provenance, settings and reproducibility")):
            st.json({"settings": context, "lineage": result.get("lineage") or {}, "config": result.get("config") or {}})
        st.download_button(tr("下载Beta研究JSON", "Download Beta research JSON"),
                           st.session_state["beta_result_json"], file_name="beta-research-report.json",
                           mime="application/json", key="beta_download_report", use_container_width=True)
        st.caption(tr("JSON包含测量、策略指标与来源指纹，不包含完整原始OHLCV。切换语言不修改下载内容。", "JSON contains measurements, strategy metrics and source fingerprints, without the complete raw OHLCV. Language changes do not modify the download."))


def render_beta_page(tr, *, snapshot_loader=None):
    st.title(tr("Beta测量与策略对照", "Beta Measurements & Strategy Comparison"))
    st.write(tr("用历史日K测量市场敏感度，比较高Beta、低Beta、全池等权及两种SPY基准。", "Measure market sensitivity using historical daily bars; compare high Beta, low Beta, equal weight and two SPY controls."))
    st.caption(tr("无杠杆日频研究，不训练DL／GenAI，不做Beta中性对冲或BAB，不连接券商或提交订单。", "Unlevered daily research: no DL/GenAI training, Beta-neutral hedge, BAB, brokerage connection or order submission."))
    st.sidebar.subheader(tr("Beta数据与参数", "Beta data and settings"))
    names = {"moomoo_daily_snapshot": tr("已发布moomoo日K快照", "Published moomoo daily snapshot"),
             "uploaded_csv": tr("访客日K CSV", "Visitor daily CSV")}
    source = _input("radio", "beta_source", "moomoo_daily_snapshot", tr("Beta数据来源", "Beta data source"),
                    options=list(names), index=None, format_func=names.__getitem__)
    if source == "moomoo_daily_snapshot":
        benchmark = "SPY"
        st.sidebar.caption(tr("SPY基准固定。首次运行获取私有日K快照，此后参数比较复用同一revision；只有主动刷新才获取新版本。", "Benchmark is fixed to SPY. The first Run fetches a private daily snapshot; parameter comparisons reuse its revision until an explicit refresh."))
        if st.sidebar.button(tr("获取／刷新日K快照", "Fetch / refresh daily snapshot"), key="beta_snapshot_refresh"):
            try:
                with st.spinner(tr("正在获取并核对日K快照。", "Fetching and checking the daily snapshot.")):
                    _snapshot_prices(refresh=True, loader=snapshot_loader)
                st.session_state["beta_snapshot_error"] = None
                if st.session_state.get("beta_error_is_snapshot"):
                    st.session_state["beta_error"] = None
            except Exception as error:
                st.session_state["beta_snapshot_cache"] = None
                st.session_state["beta_snapshot_error"] = getattr(error, "code", "SERVICE_UNAVAILABLE")
        if st.session_state.get("beta_snapshot_error"):
            _snapshot_error(st.session_state["beta_snapshot_error"], tr)
        cached = st.session_state.get("beta_snapshot_cache")
        if cached:
            meta = cached["provenance"]
            st.sidebar.caption(tr("当前会话快照截至：", "Session snapshot as of: ") + str(meta.get("as_of", "—")))
            st.sidebar.caption(tr("快照ID：", "Snapshot ID: ") + str(meta.get("snapshot_id", "—")))
            used = ((st.session_state.get("beta_result") or {}).get("lineage") or {}).get("external_data") or {}
            same = used.get("revision") == meta.get("revision") and used.get("snapshot_id") == meta.get("snapshot_id")
            st.sidebar.caption(tr("与当前结果使用同一快照。", "This snapshot is used by the displayed result.") if same else
                               tr("此快照尚未用于当前展示结果；刷新不重算旧结果。", "This snapshot is not used by the displayed result; refresh does not recompute old results."))
    else:
        st.sidebar.file_uploader("日K CSV / Daily OHLCV CSV", type=["csv"], key="beta_upload", on_change=_remember_upload)
        if st.session_state.get("beta_upload_name"):
            st.sidebar.caption(tr("会话中保留的文件：", "File retained in this session: ") + st.session_state["beta_upload_name"])
        st.sidebar.caption(tr("七列：date,symbol,open,high,low,close,volume。至少20只合格股票加基准；最多12 MiB、80000行、60只股票、1260日期。只上传有权在云端处理的日K，不含账户或个人资料。", "Columns: date,symbol,open,high,low,close,volume. At least 20 eligible stocks plus benchmark; at most 12 MiB, 80,000 rows, 60 stocks and 1,260 dates. Upload only daily prices authorized for cloud processing, excluding account or personal details."))
        benchmark = _input("text_input", "beta_benchmark", "SPY", tr("基准代码", "Benchmark symbol")).strip().upper()
    st.sidebar.download_button(tr("下载日K空白CSV模板", "Download blank daily CSV template"), CSV_TEMPLATE,
                               file_name="beta-daily-template.csv", mime="text/csv", key="beta_download_template", use_container_width=True)
    window = _input("selectbox", "beta_window", 126, tr("Beta估计窗口（交易日收益）", "Beta estimation window (session returns)"), options=[126, 252], index=None)
    test = _input("number_input", "beta_test_sessions", 252, tr("共同评估窗口（交易日）", "Common evaluation window (sessions)"), min_value=20, max_value=504, step=1)
    cost = _input("slider", "beta_cost", 10, tr("单边成交成本（bps）", "Execution cost per side (bps)"), min_value=0, max_value=50, step=1)
    st.sidebar.caption(tr("初始资本100000，股票组合单股上限20%、现金至少20%；无风险利率未输入，现金收益为0。调整参数仅为研究探索。", "Initial capital 100,000; stock baskets cap each stock at 20% and hold at least 20% cash. No risk-free rate is supplied; cash return is zero. Parameter changes are research exploration."))
    missing = source == "uploaded_csv" and not st.session_state.get("beta_upload_bytes")
    if missing:
        st.sidebar.info(tr("请先上传日K CSV。", "Upload a daily CSV first."))
    if st.sidebar.button(tr("运行Beta测量与五组对照", "Run Beta measurements and five comparisons"), key="beta_run", type="primary", disabled=missing, use_container_width=True):
        st.session_state["beta_error"] = None
        st.session_state["beta_error_is_snapshot"] = False
        params = {"benchmark": benchmark, "source": source, "beta_window": int(window), "test_sessions": int(test),
                  "cost_bps": int(cost), "max_weight": .2, "capital": 100000.}
        snapshot_stage = False
        try:
            external = None
            with st.spinner(tr("正在校验历史、估计Beta并运行共同窗口对照。", "Validating history, estimating Beta and running a common-window comparison.")):
                if source == "moomoo_daily_snapshot":
                    snapshot_stage = True
                    prices, external = _snapshot_prices(loader=snapshot_loader)
                    snapshot_stage = False
                    st.session_state["beta_snapshot_error"] = None
                else:
                    prices = parse_beta_csv(st.session_state["beta_upload_bytes"], benchmark=benchmark)
                result = run_beta_comparison(prices, **params)
                if not isinstance(result, dict) or not {"source", "status", "metrics", "equity", "lineage"} <= set(result):
                    raise ValueError("Incomplete Beta report")
                report = {key: copy.deepcopy(result[key]) for key in REPORT_KEYS if key in result}
                report["source"] = source
                if external is not None:
                    report["lineage"]["external_data"] = external
                report["lineage"].setdefault("ui_dependencies", {}).update({name: version(name) for name in ("streamlit", "plotly", "pyarrow")})
                serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
            st.session_state["beta_result"] = report
            st.session_state["beta_result_json"] = serialized
            st.session_state["beta_result_context"] = params
        except Exception as error:
            st.session_state["beta_result"] = None
            st.session_state["beta_result_json"] = None
            st.session_state["beta_result_context"] = None
            st.session_state["beta_error_is_snapshot"] = snapshot_stage
            st.session_state["beta_error"] = getattr(error, "code", "SERVICE_UNAVAILABLE") if snapshot_stage else "RUN_FAILED"
            if snapshot_stage:
                st.session_state["beta_snapshot_cache"] = None
    if st.session_state.get("beta_error"):
        if st.session_state.get("beta_error_is_snapshot"):
            _snapshot_error(st.session_state["beta_error"], tr)
        else:
            st.error(tr("本次Beta研究未完成：请核对历史长度、基准、CSV格式和至少20只股票的共同资格；没有替换数据或策略结果。", "This Beta study did not complete. Check history length, benchmark, CSV format and at least 20 jointly eligible stocks. No data or strategy results were substituted."))
    result = st.session_state.get("beta_result")
    if result is None:
        st.info(tr("选择来源和参数后点击运行。切换语言、页面或参数不自动计算；没有行情时不显示假设净值。", "Choose data and settings, then Run. Language, page or parameter changes do not compute; no hypothetical equity is displayed when prices are unavailable."))
        return
    render_beta_results(result, st.session_state["beta_result_context"], tr)
