"""Public Streamlit simulation UI; computation stays behind an explicit Run.

Results belong to the current Streamlit session. This module does not use
shared caching, brokerage clients, credentials, arbitrary paths or model files.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# Supports both `streamlit run hf_space/streamlit_app.py` and Docker /app.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))



MODEL_NAMES = ("ridge", "mlp", "mlp_resample", "mlp_diffusion")
MODEL_COLORS = {"ridge": "#718096", "mlp": "#087F8C", "mlp_resample": "#C58A28",
                "mlp_diffusion": "#6554A4"}
REPORT_KEYS = ("source", "metrics", "ic", "equity", "predictions", "weights", "lineage", "warnings")
DEFAULT_ONLINE_SYMBOLS = "NVDA, AMD, AVGO, MU, WDC, NBIS, CRWV"

LANGUAGE_PREFERENCE_JS = """
export default function(component) {
    const { data, parentElement, setStateValue } = component;
    const valid = value => value === 'en' || value === 'zh';
    const selected = data && data.save;
    let language = 'en';
    if (valid(selected)) {
        language = selected;
        if (parentElement.__alphaLanguageSaved !== language) {
            try { localStorage.setItem('alpha-lab.uiLanguage', language); } catch {}
            parentElement.__alphaLanguageSaved = language;
        }
    } else {
        try {
            const saved = localStorage.getItem('alpha-lab.uiLanguage');
            if (valid(saved)) language = saved;
        } catch {}
    }
    if (parentElement.__alphaLanguageReported !== language) {
        parentElement.__alphaLanguageReported = language;
        setStateValue('language', language);
    }
}
"""
_language_preference = st.components.v2.component(
    "alpha_lab_language_preference", js=LANGUAGE_PREFERENCE_JS,
)


def _remember_language_preference() -> None:
    choice = st.session_state.get("hf_language")
    if choice in ("English", "中文"):
        st.session_state["_hf_language_user_chosen"] = True
        st.session_state["_hf_language_save"] = "zh" if choice == "中文" else "en"


def _restore_language_preference() -> None:
    # Only an explicit radio change writes browser storage. A delayed initial
    # browser response must never replace a choice already made in this session.
    if "hf_language" not in st.session_state:
        st.session_state["hf_language"] = "English"
    result = _language_preference(
        data={"save": st.session_state.get("_hf_language_save")},
        default={"language": None}, on_language_change=lambda: None,
        key="_hf_language_preference",
    )
    saved = result.language
    if (not st.session_state.get("_hf_language_user_chosen")
            and not st.session_state.get("_hf_language_restored")
            and isinstance(saved, str) and saved in ("en", "zh")):
        st.session_state["hf_language"] = "中文" if saved == "zh" else "English"
        st.session_state["_hf_language_restored"] = True


def tr(zh: str, en: str) -> str:
    return zh if st.session_state.get("hf_language") == "中文" else en


def model_label(name: str) -> str:
    labels = {
        "ridge": ("Ridge 线性基线", "Ridge baseline"),
        "mlp": ("MLP", "MLP"),
        "mlp_resample": ("重采样 MLP", "Resampled MLP"),
        "mlp_diffusion": ("DDPM 增强 MLP", "DDPM-augmented MLP"),
    }
    return tr(*labels.get(str(name), (str(name), str(name))))


def records_frame(result: dict, key: str, required: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(result.get(key) or [])
    if frame.empty or not set(required).issubset(frame.columns):
        return pd.DataFrame(columns=required)
    if "model" in frame:
        frame = frame.loc[frame.model.isin(MODEL_NAMES)].copy()
    return frame


def render_model_status(result: dict) -> None:
    lineage = result.get("lineage") or {}
    statuses = lineage.get("model_status") or lineage.get("models") or {}
    metrics = records_frame(result, "metrics", ("model",))
    available = set(metrics.model) if not metrics.empty else set()
    rows, incomplete = [], False
    for name in MODEL_NAMES:
        info = statuses.get(name, {}) if isinstance(statuses, dict) else {}
        info = info if isinstance(info, dict) else {"status": str(info)}
        status = info.get("status")
        error = info.get("error")
        if status == "success" and name in available:
            state = tr("已完成", "Completed")
        elif status and status != "success":
            incomplete = True
            state = tr("未完成", "Not completed")
            if error:
                st.error(f"{model_label(name)}: {error}")
        elif name not in available:
            incomplete = True
            state = tr("缺少结果", "Result missing")
        else:
            state = tr("已返回指标 状态未提供", "Metrics returned; status unavailable")
        rows.append({tr("模型", "Model"): model_label(name), tr("运行状态", "Run status"): state})
    if incomplete:
        st.warning(tr("部分模型没有完成。下面只展示实际返回的结果，缺失模型不以其他结果替代。",
                      "Some models did not complete. Only returned results are shown; missing models are not substituted."))
    with st.expander(tr("查看四组模型状态", "View status of the four models"), expanded=incomplete):
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def render_metrics(result: dict) -> None:
    frame = records_frame(result, "metrics", ("model",))
    if frame.empty:
        st.info(tr("没有可展示的模型指标。", "No model metrics are available."))
        return
    options = [
        ("model", tr("模型", "Model"), None),
        ("total_return", tr("累计收益 %", "Total return %"), 100),
        ("sharpe", tr("夏普比率", "Sharpe ratio"), 1),
        ("max_drawdown", tr("最大回撤 %", "Max drawdown %"), 100),
        ("rank_ic_mean", tr("平均 Rank IC", "Mean Rank IC"), 1),
        ("annualized_return", tr("年化收益 %", "Annualized return %"), 100),
        ("annualized_volatility", tr("年化波动 %", "Annualized volatility %"), 100),
        ("total_cost", tr("累计模拟成本", "Total simulated costs"), 1),
        ("trade_count", tr("成交笔数", "Executed trades"), 1),
    ]
    view, columns = pd.DataFrame(index=frame.index), {}
    for field, label, multiplier in options:
        if field not in frame:
            continue
        if field == "model":
            view[label] = frame[field].map(model_label)
        else:
            view[label] = pd.to_numeric(frame[field], errors="coerce") * multiplier
            columns[label] = st.column_config.NumberColumn(label, format="%.3f" if field == "rank_ic_mean" else "%.2f")
    st.dataframe(view, hide_index=True, use_container_width=True, column_config=columns)
    st.caption(tr("收益曲线含所选单边成交成本；预测指标与模拟组合收益需要分别判断。短窗口年化值可能不稳定。",
                  "Strategy curves include the selected per-side execution cost. Assess predictive metrics and simulated returns separately; short-window annualization can be unstable."))


def line_figure(frame: pd.DataFrame, value: str, title: str, *, percent=False) -> go.Figure:
    import plotly.express as px

    chart = frame.copy()
    chart["date"] = pd.to_datetime(chart["date"], errors="coerce")
    chart[value] = pd.to_numeric(chart[value], errors="coerce")
    chart = chart.dropna(subset=["date", value]).sort_values(["model", "date"])
    fig = px.line(chart, x="date", y=value, color="model", title=title,
                  color_discrete_map=MODEL_COLORS, category_orders={"model": list(MODEL_NAMES)})
    for trace in fig.data:
        trace.name = model_label(trace.name)
        trace.hovertemplate = "%{x|%Y-%m-%d}<br>%{y:.2%}<extra>%{fullData.name}</extra>" if percent else "%{x|%Y-%m-%d}<br>%{y:.3f}<extra>%{fullData.name}</extra>"
    fig.update_layout(template="plotly_white", height=360, margin=dict(l=12, r=12, t=52, b=12),
                      legend_title_text="", legend=dict(orientation="h", y=-0.2),
                      xaxis_title=None, yaxis_title=None, hovermode="x unified")
    if percent:
        fig.update_yaxes(tickformat=".0%")
    return fig


def render_curves(result: dict) -> None:
    frame = records_frame(result, "equity", ("date", "model", "equity", "drawdown", "benchmark_equity"))
    if frame.empty:
        st.info(tr("没有可展示的净值或回撤曲线。", "No equity or drawdown curves are available."))
        return
    fig = line_figure(frame, "equity", tr("含成本的模拟组合权益", "Simulated portfolio equity after costs"))
    benchmark = frame[["date", "benchmark_equity"]].drop_duplicates("date").sort_values("date")
    fig.add_trace(go.Scatter(x=pd.to_datetime(benchmark.date), y=benchmark.benchmark_equity,
                             mode="lines", name=tr("基准买入持有", "Benchmark buy and hold"),
                             line=dict(color="#273444", dash="dash", width=2)))
    st.plotly_chart(fig, use_container_width=True)
    st.plotly_chart(line_figure(frame, "drawdown", tr("模拟回撤", "Simulated drawdown"), percent=True),
                    use_container_width=True)


def render_predictions_and_weights(result: dict) -> None:
    ic = records_frame(result, "ic", ("date", "model", "value"))
    if ic.empty:
        st.info(tr("没有可展示的 Rank IC 记录。", "No Rank IC observations are available."))
    else:
        fig = line_figure(ic, "value", tr("留出期每日 Rank IC", "Daily held-out Rank IC"))
        fig.add_hline(y=0, line_color="#A0AEC0", line_width=1)
        st.plotly_chart(fig, use_container_width=True)
    st.caption(tr("Rank IC 衡量同一天预测排序与后续超额收益排序的关系，不是收益率。",
                  "Rank IC measures the relation between same-day predicted ranks and subsequent excess-return ranks; it is not a return."))
    st.subheader(tr("最新参考目标权重", "Latest reference target weights"))
    weights = records_frame(result, "weights", ("model", "symbol", "weight"))
    if weights.empty:
        st.info(tr("没有股票目标权重；请查看运行警告，可能没有超过门槛的信号。",
                   "No stock target weights were returned. Check warnings; signals may not have cleared the threshold."))
    else:
        cash_rows = weights["kind"].eq("cash") if "kind" in weights else weights.symbol.eq("__CASH__")
        weights = weights[["model", "symbol", "weight"]].copy()
        weights.loc[cash_rows, "symbol"] = tr("现金", "Cash")
        weights["model"] = weights.model.map(model_label)
        weights["weight"] = pd.to_numeric(weights.weight, errors="coerce") * 100
        labels = {"model": tr("模型", "Model"), "symbol": tr("证券", "Symbol"), "weight": tr("目标权重 %", "Target weight %")}
        st.dataframe(weights.rename(columns=labels), hide_index=True, use_container_width=True,
                     column_config={labels["weight"]: st.column_config.NumberColumn(labels["weight"], format="%.2f")})
    st.caption(tr("权重受成本、仓位和风险参数约束，剩余部分为现金。这里只显示模拟参考，不连接账户或提交订单。",
                  "Weights reflect the cost, position and risk settings; the remainder is cash. These are simulation references with no account connection or order submission."))
    with st.expander(tr("逐日预测记录", "Daily prediction records")):
        predictions = records_frame(result, "predictions", ("date", "symbol", "model", "score", "realized_excess"))
        if predictions.empty:
            st.info(tr("没有预测记录。", "No predictions were returned."))
        else:
            view = predictions.copy()
            view["model"] = view.model.map(model_label)
            view = view.rename(columns={"date": tr("信号日", "Signal date"), "symbol": tr("证券", "Symbol"),
                                        "model": tr("模型", "Model"), "score": tr("预测超额收益", "Predicted excess return"),
                                        "realized_excess": tr("实际后续超额收益", "Realized subsequent excess return")})
            st.dataframe(view, hide_index=True, use_container_width=True)


def input_coverage(prices: pd.DataFrame) -> dict:
    """Describe exactly the submitted rows; unavailable history is never filled."""
    dates = pd.to_datetime(prices.date)
    return {"start": dates.min().strftime("%Y-%m-%d"),
            "end": dates.max().strftime("%Y-%m-%d"), "rows": len(prices),
            "symbols": sorted(prices.symbol.unique()),
            "by_symbol": [{"symbol": str(symbol), "rows": len(group),
                           "start": pd.to_datetime(group.date).min().strftime("%Y-%m-%d"),
                           "end": pd.to_datetime(group.date).max().strftime("%Y-%m-%d")}
                          for symbol, group in prices.groupby("symbol")]}


def render_online_downloads(result: dict | None) -> None:
    """Offer the session's fetched snapshot without confusing it with a result."""
    cached = st.session_state.get("hf_online_snapshot")
    if not cached:
        return
    provenance = cached["provenance"]
    result_provenance = ((result or {}).get("lineage") or {}).get("external_data")
    same_result_snapshot = (result or {}).get("source") == "online_history" and result_provenance == provenance
    st.sidebar.subheader(tr("在线行情快照下载", "Online snapshot downloads"))
    st.sidebar.caption(tr("当前会话最近获取的快照：", "Latest snapshot fetched in this session: ")
                       + ", ".join(provenance.get("symbols") or [])
                       + f" · {provenance.get('benchmark', '—')}"
                       + tr(" · 获取时间（UTC）：", " · Retrieved (UTC): ")
                       + str(provenance.get("retrieved_at", "—")))
    st.sidebar.caption(tr("与当前展示结果使用同一快照。", "This is the snapshot used by the displayed result.")
                       if same_result_snapshot else
                       tr("此快照尚未用于当前展示结果；不要与其他来源或之前运行的结果混用。",
                          "This snapshot is not used by the currently displayed result; do not confuse it with another source or an earlier run."))
    csv_data = cached["prices"].to_csv(index=False, date_format="%Y-%m-%d", lineterminator="\n").encode("utf8")
    st.sidebar.download_button(tr("下载行情 CSV 快照", "Download price CSV snapshot"), data=csv_data,
        file_name="online-history-snapshot.csv", mime="text/csv", key="hf_download_snapshot", use_container_width=True)
    st.sidebar.download_button(tr("下载来源 JSON", "Download source JSON"),
        data=json.dumps(provenance, ensure_ascii=False, allow_nan=False, indent=2),
        file_name="online-history-provenance.json", mime="application/json",
        key="hf_download_provenance", use_container_width=True)


def render_data_source(result: dict) -> None:
    """Use the saved result's source, never the current, unsubmitted selector."""
    source = result.get("source")
    lineage = result.get("lineage") or {}
    if source == "synthetic":
        st.warning(tr("假设教学数据，非市场收益。以下曲线和指标不是任何证券、真实账户或可获利策略的业绩。",
                      "Hypothetical teaching data, not market returns. These curves and metrics are not performance of securities, a real account or a proven profitable strategy."))
    elif source == "online_history":
        external = lineage.get("external_data") or {}
        st.info(tr("以下使用在线获取的真实历史日 K（Yahoo），是离线研究模拟；不是实时行情、券商成交或实盘表现。",
                   "These offline research simulations use real daily history retrieved from Yahoo; they are not live quotes, broker fills or live performance."))
        st.caption(tr("来源：", "Provider: ") + str(external.get("provider", "Yahoo Finance"))
                   + tr(" · 数据区间：", " · Dates: ")
                   + f"{external.get('start', '—')} — {external.get('end', '—')}"
                   + tr(" · 获取时间（UTC）：", " · Retrieved (UTC): ")
                   + str(external.get("retrieved_at", "—")))
        st.caption(tr("股票：", "Stocks: ") + ", ".join(external.get("symbols") or [])
                   + tr(" · 基准：", " · Benchmark: ") + str(external.get("benchmark", "—")))
        st.caption(tr("本会话使用同一行情快照比较参数；重新获取可能修订历史。缺失和新上市历史不作填充，逐股覆盖与复权口径见运行信息。",
                      "Parameter comparisons reuse this session's price snapshot. Refreshing can revise history. Missing or pre-IPO history is not filled; per-symbol coverage and adjustment details are in Run details."))
    elif source == "uploaded_csv":
        st.info(tr("以下为上传 CSV 的离线模拟结果；数据已在云端处理，不代表券商成交或实盘表现。",
                   "These are offline simulation results from the uploaded CSV, processed in the cloud; they are not broker fills or live performance."))
        coverage = lineage.get("input_coverage") or lineage.get("data") or {}
        st.caption(tr("CSV 覆盖：", "CSV coverage: ")
                   + f"{coverage.get('start', '—')} — {coverage.get('end', '—')}"
                   + tr(" · 证券：", " · Symbols: ") + ", ".join(coverage.get("symbols") or []))
    else:
        st.warning(tr("结果来源未识别，请查看运行信息。", "Result source is unrecognized; check Run details."))


def main() -> None:
    st.set_page_config(page_title="Alpha Trading Lab", page_icon="📈", layout="wide")
    _restore_language_preference()
    brand, language = st.columns([3, 2], vertical_alignment="center")
    with brand:
        st.markdown("**Alpha Trading Lab**")
    with language:
        st.radio("Language / 语言", ("English", "中文"), key="hf_language", horizontal=True,
                 on_change=_remember_language_preference)
    app_entry, project_entry = st.columns(2)
    with app_entry:
        st.link_button(tr("打开应用", "Open app"), "https://rexymiao-alpha-trading-lab.hf.space/", use_container_width=True)
    with project_entry:
        st.link_button(tr("Hugging Face项目页", "Hugging Face project"), "https://huggingface.co/spaces/Rexymiao/alpha-trading-lab", use_container_width=True)
    # Keep navigation in non-widget state: translated labels may recreate widgets.
    memory = "_hf_study_choice"
    if memory not in st.session_state:
        st.session_state[memory] = st.session_state.get("hf_study", "ai")
    st.session_state["hf_study"] = st.session_state[memory]
    def remember_study():
        st.session_state[memory] = st.session_state["hf_study"]
    study_labels = {"ai": tr("AI 模型对照", "AI model comparison"),
                    "strategies": tr("日频动量与趋势", "Daily momentum & trend"),
                    "intraday": tr("5 分钟动量与趋势", "5-minute momentum & trend"),
                    "beta": tr("Beta 测量与策略对照", "Beta measurement & comparison"),
                    "sr": tr("支撑与阻力策略", "Support & resistance"),
                    "options": tr("期权结构研究", "Options structure research"),
                    "premarket": tr("盘前涨幅与开盘下探", "Premarket & opening downside")}
    study = st.radio(tr("研究页面", "Study page"), ("ai", "strategies", "intraday", "beta", "sr", "options", "premarket"), index=None,
                     format_func=study_labels.__getitem__, key="hf_study", on_change=remember_study,
                     horizontal=True)
    st.divider()
    if study == "premarket":
        from hf_space.premarket_ui import render_premarket_page
        render_premarket_page(tr)
        return
    if study == "options":
        from hf_space.options_research_ui import render_options_research_page
        render_options_research_page(tr)
        return
    if study == "sr":
        from hf_space.support_resistance_ui import render_sr_page
        render_sr_page(tr)
        return
    if study == "beta":
        from hf_space.beta_ui import render_beta_page
        render_beta_page(tr)
        return
    if study == "intraday":
        from hf_space.intraday_ui import render_intraday_page
        render_intraday_page(tr)
        return
    if study == "strategies":
        from hf_space.strategy_ui import render_strategy_page
        render_strategy_page(tr, render_data_source, input_coverage, render_online_downloads)
        return
    st.title(tr("Alpha量化研究实验室", "Alpha Trading Research Lab"))
    st.write(tr("研究日频AI Alpha、动量／趋势、Beta、支撑／阻力、期权结构与盘前涨幅后的开盘下探；在上方切换专题。",
                "Explore daily AI alpha, momentum and trend, Beta, support and resistance, options structure, and opening downside after premarket gains. Choose a study above."))
    st.subheader(tr("AI Alpha：四模型对照", "AI alpha: four-model comparison"))
    st.write(tr("比较四种预测方法，并观察交易成本、仓位上限与风险预算如何改变模拟结果。",
                "Compare four prediction methods and see how execution costs, position limits and risk budgets change simulated results."))
    st.caption(tr("Ridge · MLP · 重采样 MLP · 条件 DDPM 增强 MLP。这是有限研究对照，并非相关论文的完整复现。",
                  "Ridge · MLP · resampled MLP · conditional-DDPM-augmented MLP. This is a bounded research comparison, not a full replication of the papers."))

    st.sidebar.subheader(tr("数据与参数", "Data and settings"))
    source_labels = {"uploaded_csv": tr("moomoo / 访客 CSV（主要入口）", "moomoo / visitor CSV (primary)"),
                     "online_history": tr("在线真实历史日 K", "Online real daily history"),
                     "synthetic": tr("合成教学数据", "Synthetic teaching data")}
    mode = st.sidebar.radio(tr("数据来源", "Data source"), ("uploaded_csv", "online_history", "synthetic"),
                            format_func=source_labels.__getitem__,
                            key="hf_source_mode")
    uploaded = None
    if mode == "uploaded_csv":
        st.sidebar.caption(tr("主要使用 moomoo 导出的历史日 K，也接受访客提供的标准 CSV；请先整理为下方 7 列。这里不连接 moomoo 登录或账户。",
                              "Primarily use historical daily bars exported from moomoo; visitor-supplied standard CSV is also accepted. Map it to the seven columns below. No moomoo login or account is connected."))
        st.sidebar.caption(tr("CSV 会发送到运行此模拟的云端环境临时处理。请勿上传账户、个人信息或密钥；请确认有权用于云端处理。",
                           "CSV files are sent to the server hosting this simulation for temporary processing. Exclude account details, personal information and secrets, and ensure you have the right to process the data in the cloud."))
        uploaded = st.sidebar.file_uploader(tr("选择日 K CSV", "Choose a daily OHLCV CSV"), type=["csv"], key="hf_uploaded_csv")
        with st.sidebar.expander(tr("CSV 格式要求", "CSV requirements")):
            st.code("date,symbol,open,high,low,close,volume", language="text")
            st.write(tr("同一文件内需包含股票和基准，日期使用 YYYY-MM-DD。历史长度需足够切分训练、验证和测试；不足会明确报错。",
                        "Include both stocks and the benchmark in the same file, using YYYY-MM-DD dates. Enough history is needed for chronological train, validation and test splits; insufficient data raises an explicit error."))
            st.caption(tr("上限为3 MiB、8000行、600个日期、3至12只股票加基准；训练样本超过3000行时请减少范围。",
                          "Limits: 3 MiB, 8,000 rows, 600 dates, and 3–12 stocks plus a benchmark. Reduce the scope if training rows exceed 3,000."))
    elif mode == "online_history":
        st.sidebar.info(tr("点击运行后从 Yahoo 获取公开历史日 K，无需 API 密钥；最多取最近 400 个已完成基准交易日，保守排除美东今日。不是实时行情。获取失败会明确报错，不改用合成数据。",
                           "Run fetches public daily history from Yahoo without an API key: up to 400 completed benchmark sessions, conservatively excluding today's New York date. This is not live data. Fetch failures are reported without synthetic fallback."))
        st.sidebar.caption(tr("在线默认 7 股：NVDA、AMD、AVGO、MU、WDC、NBIS、CRWV；这是在线来源的独立名单，不会修改你的 moomoo CSV 股票范围。",
                              "Online default: 7 stocks—NVDA, AMD, AVGO, MU, WDC, NBIS, CRWV. This separate online list does not change the symbols in your moomoo CSV."))
    else:
        st.sidebar.caption(tr("固定 6 只虚构资产、400 个工作日，基准为 BENCH。", "Six fictional assets over 400 business days; benchmark: BENCH."))

    with st.sidebar.form("hf_run_settings"):
        if mode in {"uploaded_csv", "online_history"}:
            benchmark = st.text_input(tr("基准代码", "Benchmark symbol"), value="SPY", key="hf_benchmark").strip().upper()
        else:
            benchmark = "BENCH"
            st.caption(tr("基准：BENCH", "Benchmark: BENCH"))
        symbols_text, refresh_history = "", False
        if mode == "online_history":
            symbols_text = st.text_input(tr("股票代码（逗号分隔，3–8 只）", "Stock symbols (comma-separated, 3–8)"),
                                         value=DEFAULT_ONLINE_SYMBOLS, key="hf_online_symbols")
            refresh_history = st.checkbox(tr("重新获取在线行情", "Refresh online history"), value=False,
                                          key="hf_refresh_online",
                                          help=tr("默认重用本会话同一股票和基准的快照；勾选时每次运行都会重新获取。",
                                                  "By default, reuse this session's snapshot for the same symbols and benchmark. When checked, each Run fetches a fresh snapshot."))
        horizon = st.number_input(tr("预测与调仓周期（交易日）", "Forecast and rebalance horizon (sessions)"),
                                  min_value=1, max_value=20, value=5, step=1, key="hf_horizon",
                                  help=tr("同时决定收益标签的持有期与调仓间隔；较长周期会减少可用标签和可观察的调仓次数。",
                                          "Sets both the return-label holding period and the rebalance interval; longer horizons leave fewer usable labels and observed rebalances."))
        st.caption(tr("建议从 5 个交易日开始，初期在 10 个交易日以内研究；可输入 1–20 的整数。这是教学起点，并非经验证的最优周期。",
                      "Start with 5 trading days; use 10 or fewer for initial experiments. Enter an integer from 1–20. This is a teaching starting point, not a validated optimal horizon."))
        with st.expander(tr("高级设置", "Advanced settings")):
            seed = st.number_input(tr("随机种子", "Random seed"), min_value=0, max_value=2147483647,
                                   value=42, step=1, key="hf_seed")
            cost_bps = st.slider(tr("单边成交成本（bps）", "Execution cost per side (bps)"), 0, 50, 10, 1, key="hf_cost_bps")
            max_weight_pct = st.slider(tr("单股仓位上限 %", "Per-stock position cap %"), 10, 40, 20, 5, key="hf_max_weight_pct")
            target_vol_pct = st.slider(tr("组合年化波动预算 %", "Annualized portfolio volatility budget %"), 5, 30, 15, 1, key="hf_target_vol_pct")
        submitted = st.form_submit_button(tr("运行模拟", "Run simulation"), type="primary", use_container_width=True)
    st.sidebar.caption(tr("只在点击运行后计算。结果保存在当前会话，切换语言无需重新训练；可下载 JSON 自行保存。",
                          "Computation starts only when you click Run. Results stay in this session; switching language does not retrain. Download JSON to keep a copy."))

    if submitted:
        st.session_state["hf_last_error"] = None
        st.session_state["hf_last_error_source"] = None
        try:
            if mode == "uploaded_csv" and uploaded is None:
                raise ValueError(tr("请先选择 CSV 文件。", "Choose a CSV file first."))
            if not benchmark:
                raise ValueError(tr("基准代码不能为空。", "The benchmark symbol cannot be empty."))
            context = {"source": mode, "benchmark": benchmark, "seed": int(seed), "horizon": int(horizon),
                       "cost_bps": int(cost_bps), "max_weight": max_weight_pct / 100,
                       "target_vol": target_vol_pct / 100}
            with st.spinner(tr("正在校验数据、训练并评估，请等待本次运行结束。", "Validating, training and evaluating; please wait for this run to finish.")):
                # Keep training dependencies out of the first screen and other studies.
                from hf_space.engine import make_synthetic_prices, parse_csv, run_simulation
                from hf_space.history import fetch_history

                external_data = None
                if mode == "synthetic":
                    prices = make_synthetic_prices(seed=int(seed), periods=400, n_assets=6)
                elif mode == "uploaded_csv":
                    prices = parse_csv(uploaded.getvalue(), benchmark=benchmark)
                else:
                    symbols = tuple(symbol.strip().upper() for symbol in symbols_text.split(",") if symbol.strip())
                    cache_key = (tuple(sorted(symbols)), benchmark)
                    cached = st.session_state.get("hf_online_snapshot")
                    if refresh_history or not cached or cached.get("key") != cache_key:
                        prices, external_data = fetch_history(symbols, benchmark=benchmark, sessions=400)
                        st.session_state["hf_online_snapshot"] = {"key": cache_key,
                            "prices": prices.copy(deep=True), "provenance": copy.deepcopy(external_data)}
                    else:
                        prices = cached["prices"].copy(deep=True)
                        external_data = copy.deepcopy(cached["provenance"])
                result = run_simulation(prices, **context)
                if not isinstance(result, dict) or any(key not in result for key in REPORT_KEYS):
                    raise ValueError(tr("模拟引擎返回了不完整的结果。", "The simulation engine returned an incomplete report."))
                result.setdefault("lineage", {})["input_coverage"] = input_coverage(prices)
                if external_data is not None:
                    result["lineage"]["external_data"] = copy.deepcopy(external_data)
                # The export contains report data and metadata, never model objects.
                report = {key: result[key] for key in REPORT_KEYS}
                report_json = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)
            st.session_state["hf_result"] = report
            st.session_state["hf_result_json"] = report_json
            st.session_state["hf_result_context"] = context
        except Exception as error:
            st.session_state["hf_result"] = None
            st.session_state["hf_result_json"] = None
            st.session_state["hf_result_context"] = None
            st.session_state["hf_last_error"] = str(error)
            st.session_state["hf_last_error_source"] = mode

    error = st.session_state.get("hf_last_error")
    if error:
        st.error(tr("本次运行未完成：", "This run did not complete: ") + error)
        if st.session_state.get("hf_last_error_source") == "online_history":
            st.info(tr("在线数据流程未完成，没有替换成合成数据。可检查股票与数据覆盖，或改用 moomoo / 访客 CSV。",
                       "The online-data workflow did not complete; no synthetic data was substituted. Check symbols and coverage, or use a moomoo / visitor CSV."))
    result = st.session_state.get("hf_result")
    if mode == "online_history":
        render_online_downloads(result)
    if result is None:
        if mode == "synthetic":
            st.warning(tr("合成模式使用假设教学数据，非市场收益。运行后出现的指标仅用于理解流程。",
                          "Synthetic mode uses hypothetical teaching data, not market returns. Its metrics illustrate the workflow only."))
        st.info(tr("在左侧选择数据和参数，然后点击「运行模拟」。调整参数本身不会启动训练。",
                   "Choose data and settings on the left, then click Run simulation. Changing a setting alone does not start training."))
        return

    context = st.session_state.get("hf_result_context") or {}
    render_data_source(result)
    st.caption(tr("当前展示的是上次已运行的参数：", "Displayed results use the last executed settings: ")
               + f"{context.get('benchmark', '—')} · h={context.get('horizon', '—')} · seed={context.get('seed', '—')}"
               + f" · {context.get('cost_bps', '—')} bps"
               + tr(" · 单股上限 ", " · position cap ") + f"{context.get('max_weight', 0):.0%}"
               + tr(" · 风险预算 ", " · risk budget ") + f"{context.get('target_vol', 0):.0%}"
               + tr("；修改左侧参数后需重新点击运行。", ". Click Run again to apply changes on the left."))
    render_model_status(result)

    overview, prediction_tab, details = st.tabs([tr("收益与风险", "Returns and risk"),
                                                tr("预测与权重", "Predictions and weights"),
                                                tr("运行信息", "Run details")])
    with overview:
        render_metrics(result)
        render_curves(result)
    with prediction_tab:
        render_predictions_and_weights(result)
    with details:
        st.subheader(tr("运行提示", "Run warnings"))
        warnings = result.get("warnings") or []
        if warnings:
            for warning in warnings:
                st.warning(str(warning))
        else:
            st.caption(tr("引擎未返回额外提示；这不构成策略有效性的证明。", "The engine returned no additional warnings; this does not establish strategy validity."))
        with st.expander(tr("参数与可复现信息", "Settings and reproducibility metadata")):
            st.json({"settings": context, "lineage": result.get("lineage") or {}})
        st.download_button(tr("下载本次 JSON 结果", "Download this JSON report"),
                           data=st.session_state["hf_result_json"], file_name="alpha-simulation-report.json",
                           mime="application/json", use_container_width=True)
        st.caption(tr("下载内容为指标、曲线、预测、参考权重与运行说明，不包含训练模型。",
                      "The download includes metrics, curves, predictions, reference weights and metadata, not trained models."))


if __name__ == "__main__":
    main()
