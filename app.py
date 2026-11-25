"""Read-only local research viewer. No collection, training, or order execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from research.math_content import render_math
from ui_helpers import LocalizedUI, english

st = LocalizedUI(st)


ROOT = Path(__file__).resolve().parent
LATEST = ROOT / "runs" / "latest.json"
MODEL_NAMES = {
    "ridge": "Ridge 基线",
    "mlp": "MLP 深度学习",
    "mlp_resample": "MLP 重采样对照",
    "mlp_diffusion": "条件 DDPM 增强 MLP",
    "equal_weight_buy_hold": "初始等权买入持有",
    "rank_mse": "相同网络 MSE 对照",
    "rank_softic": "ADNN 平滑 IC 机制",
}
COLORS = {"ridge": "#64748b", "mlp": "#2563eb", "mlp_resample": "#d97706", "mlp_diffusion": "#0d9488", "equal_weight_buy_hold": "#9333ea", "rank_mse": "#2563eb", "rank_softic": "#0d9488"}
STATUS_NAMES = {
    "completed": "实验已完成",
    "data_unavailable": "数据暂不可用",
    "insufficient_data": "历史样本不足",
    "failed": "实验失败",
}


def read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, f"尚未生成 {path.name}。"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            return {}, f"{path.name} 顶层必须是 JSON 对象。"
        return value, None
    except (OSError, ValueError) as exc:
        return {}, f"读取 {path.name} 失败：{exc}"


def label(model: str) -> str:
    return MODEL_NAMES.get(str(model), str(model))


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def records(value: Any) -> pd.DataFrame:
    if isinstance(value, list) and value:
        return pd.json_normalize(value)
    return pd.DataFrame()


def series_frame(report: dict[str, Any], field: str, numeric: list[str]) -> pd.DataFrame:
    frame = records((report.get("series") or {}).get(field))
    if frame.empty or not {"date", "model"}.issubset(frame.columns):
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True).dt.tz_localize(None)
    for column in numeric:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return frame.dropna(subset=["date"]).sort_values(["model", "date"])


def failed_models(report: dict[str, Any]) -> set[str]:
    failures = set()
    for experiment in report.get("experiments") or []:
        if not isinstance(experiment, dict):
            continue
        training = experiment.get("training") or {}
        if experiment.get("status") == "failed" or (isinstance(training, dict) and training.get("status") == "failed"):
            failures.add(str(experiment.get("model")))
    return failures


def plot_lines(frame: pd.DataFrame, y: str, title: str, *, percent: bool = False) -> None:
    if frame.empty or y not in frame or not frame[y].notna().any():
        st.info(f"暂无可用的{title}记录。")
        return
    figure = go.Figure()
    for model, group in frame.groupby("model", sort=False):
        group = group.dropna(subset=[y])
        if group.empty:
            continue
        figure.add_trace(go.Scatter(
            x=group["date"], y=group[y], name=label(model), mode="lines",
            line={"color": COLORS.get(model), "width": 2},
        ))
    figure.update_layout(
        title=title, height=340, margin={"l": 16, "r": 16, "t": 48, "b": 20},
        hovermode="x unified", legend={"orientation": "h", "y": -0.2},
        xaxis_title=None, yaxis_title=None,
    )
    if percent:
        figure.update_yaxes(tickformat=".1%")
    st.plotly_chart(figure, use_container_width=True, theme="streamlit")


def run_help(reason: str | None = None) -> None:
    if reason:
        st.info(reason)
    st.markdown("在项目目录的终端中运行。采集与训练由你主动启动，页面只读取结果：")
    st.code("python run.py collect\npython run.py experiment\npython run.py all", language="powershell")
    st.caption("数据不足或接口失败时，先处理报告中的原因；页面不会用随机行情补出收益。")


def show_messages(report: dict[str, Any]) -> None:
    messages = report.get("warnings") or []
    if isinstance(messages, str):
        messages = [messages]
    for message in messages:
        st.warning(str(message))


def data_page(report: dict[str, Any], config: dict[str, Any], load_error: str | None) -> None:
    st.title("数据")
    data = report.get("data") or {}
    st.caption("日频股票研究 · moomoo 数据优先 · 所有边界按完整美东交易日处理")
    cols = st.columns(3)
    cols[0].metric("状态", STATUS_NAMES.get(report.get("status"), "尚无实验结果"))
    cols[1].metric("共同交易日", data.get("n_dates", "—"))
    symbols = data.get("symbols") or []
    cols[2].metric("数据标的数", len(symbols) if isinstance(symbols, list) else "—")
    if data:
        st.write("**数据来源：**", data.get("source", "未记录"))
        st.write("**数据区间：**", f"{data.get('start') or '未记录'} → {data.get('end') or '未记录'}")
        if symbols:
            st.write("**返回的标的：**", ", ".join(map(str, symbols)))
        groups = config.get('research_groups') or []
        if groups:
            st.subheader('Research themes' if english() else '研究主题')
            group_rows = [
                {('Theme' if english() else '主题'): group.get('label_en' if english() else 'label_zh', group.get('id')),
                 ('Count' if english() else '数量'): len(group.get('symbols', [])),
                 ('Symbols' if english() else '股票代码'): ', '.join(group.get('symbols', []))}
                for group in groups
            ]
            st.dataframe(pd.DataFrame(group_rows), use_container_width=True, hide_index=True)
            st.caption('Current research themes are not historical sector classifications or confirmed holdings.' if english() else '这些是当前研究主题，不是历史行业分类，也不代表已确认的实际持仓。')
        quality = data.get("quality")
        if isinstance(quality, dict) and isinstance(quality.get('coverage'), dict):
            coverage_rows = quality['coverage'].get('symbols') or []
            if coverage_rows:
                st.subheader('History coverage by stock' if english() else '逐股历史覆盖')
                fields = {
                    'symbol': 'Symbol' if english() else '股票代码',
                    'first': 'First usable session' if english() else '研究历史起点',
                    'last': 'Last session' if english() else '最后交易日',
                    'n_bars': 'Bars' if english() else '有效日K',
                    'usable_feature_rows': 'Feature rows' if english() else '特征样本数',
                    'labeled_rows': 'Labeled rows' if english() else '有答案的样本数',
                    'eligible': 'Coverage check passed' if english() else '历史预检通过',
                }
                frame = pd.DataFrame(coverage_rows)
                st.dataframe(frame[[key for key in fields if key in frame]].rename(columns=fields), use_container_width=True, hide_index=True)
                st.caption('IPO and business-restart boundaries are applied before feature calculation. No pre-IPO bars are fabricated.' if english() else '上市和业务重启边界在计算特征前生效，不填造上市前数据。')
        st.subheader("质量检查")
        if quality is not None:
            if isinstance(quality, list):
                st.dataframe(records(quality), use_container_width=True, hide_index=True)
            elif isinstance(quality, dict):
                st.json(quality, expanded=True)
            else:
                st.write(quality)
        else:
            st.info("报告尚未记录质量检查，不能据此推断数据已通过验证。")
        errors = data.get("errors") or []
        if isinstance(errors, str):
            errors = [errors]
        for error in errors:
            st.error(str(error))
    if load_error or report.get("status") != "completed":
        run_help(load_error or STATUS_NAMES.get(report.get("status"), "尚无完整结果。"))
    st.subheader("当前研究设定")
    if not config.get("universe_confirmed", False):
        if config.get('universe_kind') == 'thematic_research':
            st.info('Thematic research universe; your actual holdings are tracked separately.' if english() else '当前是主题研究股票池，实际持仓名单另行确认。')
        else:
            st.info("示例研究股票池，尚未确认是你的持仓名单。")
    portfolio = config.get("portfolio") or {}
    st.write(f"股票池：{', '.join(config.get('universe') or [])}；基准：{config.get('benchmark', 'SPY')}。")
    st.write(f"预测和调仓跨度：{config.get('horizon', '—')} 个交易日；种子：{config.get('seed', '—')}。")
    st.caption("固定原型股票池不等于历史时点股票池；当前研究仍有生存者偏差风险。复权OHLC是成交价近似，分红口径以本次运行报告为准。")
    with st.expander("配置与数据追溯"):
        st.markdown("**本次运行配置**" if report.get("config") else "**项目配置**")
        st.json(config)
        st.markdown("**运行与数据版本**")
        st.json({"run_id": report.get("run_id"), "created_at": report.get("created_at"), "lineage": report.get("lineage")})
    if portfolio:
        st.caption("修改 config.json 后，已有结果不会随之改变；需要重新运行实验才能评价新设定。")


def paired_genai(ic: pd.DataFrame) -> None:
    st.subheader("GenAI 的成对增量")
    st.caption("只比较同一测试日的实际记录。DDPM增强与普通MLP、重采样对照分别配对；不把更多训练样本本身的作用算成生成模型的独有优势。")
    needed = {"mlp_diffusion", "mlp", "mlp_resample"}
    available = set(ic["model"]) if not ic.empty else set()
    if "mlp_diffusion" not in available or not (available & {"mlp", "mlp_resample"}):
        st.info("需要条件 DDPM 增强模型与至少一个对照模型在相同测试日的 Rank IC。当前记录不足。")
        return
    actual = ic[ic["model"].isin(needed)].dropna(subset=["value"])
    if actual.duplicated(["date", "model"]).any():
        st.warning("同一模型同一日期出现重复 IC；先检查实验输出，暂不汇总成对增量。")
        return
    wide = actual.pivot(index="date", columns="model", values="value")
    delta_records = []
    summaries = []
    for baseline in ("mlp", "mlp_resample"):
        if baseline not in wide or "mlp_diffusion" not in wide:
            continue
        paired = wide[["mlp_diffusion", baseline]].dropna()
        if paired.empty:
            continue
        delta = paired["mlp_diffusion"] - paired[baseline]
        pair_name = f"DDPM 增强 − {label(baseline)}"
        summaries.append({"比较": pair_name, "共同日期数": len(delta), "平均 ΔRank IC": float(delta.mean()), "增量为正的日期占比": float((delta > 0).mean())})
        delta_records.extend({"date": date, "model": pair_name, "value": float(value)} for date, value in delta.items())
    if not summaries:
        st.info("模型有记录，但没有可配对的共同测试日。")
        return
    st.dataframe(pd.DataFrame(summaries).style.format({"平均 ΔRank IC": "{:.4f}", "增量为正的日期占比": "{:.1%}"}), use_container_width=True, hide_index=True)
    plot_lines(pd.DataFrame(delta_records), "value", "每日 ΔRank IC")
    st.caption("这是描述统计，没有置信区间或显著性结论。相邻五日标签会重叠，日期之间可能相关；需要额外的分块检验与多种子实验。")


def results_page(report: dict[str, Any], load_error: str | None, *, mechanism: bool = False) -> None:
    if not mechanism:
        st.title("实验结果")
    if load_error or report.get("status") != "completed":
        run_help(load_error or STATUS_NAMES.get(report.get("status"), "尚无完整实验。"))
    failures = failed_models(report)
    for model in sorted(failures):
        st.error(f"{label(model)} 训练失败，未用其他模型替代其结果。")
    experiments = [e for e in report.get("experiments") or [] if isinstance(e, dict)]
    if experiments:
        table = []
        for experiment in experiments:
            training_status = (experiment.get("training") or {}).get("status", experiment.get("status", "未记录"))
            if experiment.get("model") == "equal_weight_buy_hold":
                training_status = "基准，不训练"
            item = {"模型": label(experiment.get("model")), "训练状态": training_status}
            metrics = dict(experiment.get("metrics") or {})
            if "annualized_return" not in metrics and "cagr" in metrics:
                metrics["annualized_return"] = metrics["cagr"]
            for field in ("rank_ic_mean", "calibrated_rank_ic_mean", "rank_ic_std", "n_ic_dates", "total_return", "annualized_return", "sharpe", "max_drawdown", "total_turnover", "total_cost", "trade_count"):
                if field in metrics:
                    column = "raw_rank_ic_mean" if mechanism and field == "rank_ic_mean" else field
                    item[column] = metrics[field]
            table.append(item)
        metric_formats = {field: "{:.2%}" for field in ("total_return", "annualized_return", "cagr", "max_drawdown")}
        metric_formats.update({field: "{:.4f}" for field in ("rank_ic_mean", "raw_rank_ic_mean", "calibrated_rank_ic_mean", "rank_ic_std", "sharpe")})
        st.dataframe(pd.DataFrame(table).style.format(metric_formats, na_rep="—"), use_container_width=True, hide_index=True)
        st.caption("指标来自保存的运行报告；小样本正收益或正 IC 不能证明策略已具有可交易优势。")
        ic_means = [finite_number((entry.get("metrics") or {}).get("rank_ic_mean")) for entry in experiments if entry.get("model") not in failures]
        ic_means = [value for value in ic_means if value is not None]
        if ic_means and all(value < 0 for value in ic_means):
            st.warning("当前测试期，所有有记录的预测模型平均 Rank IC 均为负，尚未显示正向排序优势。净值变化需结合市场暴露与基准分析。")
    ic = series_frame(report, "ic", ["value"])
    equity = series_frame(report, "equity", ["equity", "drawdown", "benchmark_equity", "cash_weight", "turnover"])
    if not ic.empty:
        ic = ic[~ic["model"].isin(failures)]
    if not equity.empty:
        equity = equity[~equity["model"].isin(failures)]
    available = set(ic.get("model", [])) | set(equity.get("model", []))
    models = [key for key in MODEL_NAMES if key in available] + sorted(available - set(MODEL_NAMES))
    if not models:
        st.info("没有可绘制的预测或组合结果。数学原理页可独立查看。")
        if experiments:
            with st.expander("训练记录与失败原因"):
                st.json(experiments)
        return
    st.subheader("查看范围")
    widget_prefix = ("mechanism" if mechanism else "main") + str(report.get("run_id", ""))
    selected = st.multiselect("显示模型", models, default=models, format_func=label, key=widget_prefix + "_models")
    dates = pd.concat([frame["date"] for frame in (ic, equity) if not frame.empty])
    date_min, date_max = dates.min().date(), dates.max().date()
    chosen = st.date_input("图表日期", value=(date_min, date_max), min_value=date_min, max_value=date_max, key=widget_prefix + "_dates")
    if len(chosen) != 2:
        st.info("请选择完整的开始和结束日期。")
        return
    begin, end = pd.Timestamp(chosen[0]), pd.Timestamp(chosen[1]) + pd.Timedelta(days=1)
    def select_view(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        return frame[frame["model"].isin(selected) & frame["date"].ge(begin) & frame["date"].lt(end)].copy()
    ic_view, equity_view = select_view(ic), select_view(equity)
    st.caption("这些控件仅改变图表范围；顶部指标仍是整次运行的指标，不会重新训练或执行策略。")
    if not selected:
        st.info("至少选择一个模型后查看图表。")
        return
    if not ic_view.empty and "value" in ic_view:
        plot_lines(ic_view, "value", "每日横截面 Rank IC")
        window = st.slider("滚动 IC 窗口（有效观测日）", 5, 60, 20, 5, key=widget_prefix + "_rolling")
        rolling = ic.dropna(subset=["value"]).copy()
        rolling["value"] = rolling.groupby("model")["value"].transform(lambda values: values.rolling(window, min_periods=window).mean())
        plot_lines(select_view(rolling), "value", f"{window} 日滚动平均 Rank IC")
    else:
        st.info("所选范围没有有效 Rank IC；未给未知日期填零。")
    if not equity_view.empty:
        plotted = equity_view.copy()
        if "benchmark_equity" in plotted:
            benchmark = plotted[["date", "benchmark_equity"]].dropna().drop_duplicates()
            if not benchmark.duplicated("date").any():
                benchmark = benchmark.rename(columns={"benchmark_equity": "equity"})
                benchmark["model"] = "SPY 基准"
                plotted = pd.concat([plotted, benchmark], ignore_index=True)
        plot_lines(plotted, "equity", "含成交成本的账户权益")
        plot_lines(equity_view, "drawdown", "历史峰值以来的回撤", percent=True)
        with st.expander("现金比例与真实换手记录"):
            st.dataframe(equity_view, use_container_width=True, hide_index=True)
    if not mechanism:
        paired_genai(ic_view)
    with st.expander("训练参数与模型状态"):
        st.json(experiments)


def mechanism_page() -> None:
    st.title("论文机制复现")
    st.info("独立比较相同网络的 MSE 与同日横截面平滑 IC 损失；只研究论文的一项机制，不是 ADNN 完整复现，也不属于 DDPM 增强实验。")
    report, error = read_json(ROOT / "runs" / "rank_latest.json")
    if error:
        st.info("尚无论文机制实验结果。主研究结果不受影响。")
        st.code("python run.py rank", language="powershell")
        return
    st.caption("原始排序分数用于 Rank IC；只有经独立验证期校准成相对收益后，才能与成本阈值比较并转换仓位。")
    paper_url = (report.get("replication") or {}).get("paper_url")
    if isinstance(paper_url, str) and paper_url.startswith("https://"):
        st.markdown(f"[ADNN 原论文]({paper_url})")
    show_messages(report)
    results_page(report, None, mechanism=True)
    calibration = []
    chain = []
    for experiment in report.get("experiments") or []:
        entry = (experiment.get("training") or {}).get("calibration")
        if isinstance(entry, dict):
            calibration.append({"模型": label(experiment.get("model")), **{field: entry.get(field) for field in ("intercept", "slope", "fit_start", "fit_end", "fit_label_end", "fit_days", "rmse_decimal", "flat_calibration")}})
            metrics = experiment.get("metrics") or {}
            chain.append({"模型": label(experiment.get("model")), "raw_rank_ic_mean": metrics.get("rank_ic_mean"), "calibrated_rank_ic_mean": metrics.get("calibrated_rank_ic_mean"), "校准后预测是否为常数": entry.get("flat_calibration"), "trade_count": metrics.get("trade_count")})
    if calibration:
        st.subheader("独立验证期收益校准")
        st.dataframe(pd.DataFrame(calibration), use_container_width=True, hide_index=True)
        st.caption("校准斜率限制为非负；若斜率为0，收益预测成为常数，校准后的 Rank IC 可为空。这不改变原始分数的 Rank IC。")
        st.subheader("排序到交易的检查")
        st.dataframe(pd.DataFrame(chain), use_container_width=True, hide_index=True)
        threshold = finite_number(((report.get("config") or {}).get("portfolio") or {}).get("min_expected_excess"))
        threshold = threshold if threshold is not None else 0.002
        below_threshold = all(finite_number(row.get("intercept")) is not None and finite_number(row.get("intercept")) <= threshold for row in calibration)
        no_trades = all(finite_number(row.get("trade_count")) == 0 for row in chain)
        if len(calibration) == 2 and all(finite_number(row.get("slope")) == 0 for row in calibration) and below_threshold and no_trades:
            st.warning("本次两个模型的校准斜率均为0，收益预测退化为常数；校准后 Rank IC 未定义。校准预测未过成本门槛，组合保持现金、没有交易。原始 Rank IC 略为正不等于建议买入。")
    with st.expander("论文范围、校准与复现差异"):
        st.json({"replication": report.get("replication"), "paper_scope": report.get("paper_scope"), "calibration": report.get("calibration"), "lineage": report.get("lineage")})
    curves = report.get("training_curves")
    if curves:
        curves_frame = records(curves)
        if {"model", "step", "loss"}.issubset(curves_frame.columns):
            st.subheader("训练目标记录")
            st.caption("MSE 与负平滑 IC 的量纲和目标不同，分别绘图，不能按数值高低比较两个模型。")
            for model, group in curves_frame.groupby("model", sort=False):
                figure = go.Figure(go.Scatter(x=group["step"], y=group["loss"], name=label(model), mode="lines+markers"))
                figure.update_layout(title=label(model), xaxis_title="训练步", yaxis_title="训练目标", height=280, margin={"l": 16, "r": 16, "t": 40, "b": 40})
                st.plotly_chart(figure, use_container_width=True, theme="streamlit")
        else:
            with st.expander("训练目标记录"):
                st.json(curves)


def decision_page(report: dict[str, Any]) -> None:
    st.title("因子到决策")
    st.markdown("**历史价量 → DL / GenAI 预测分数 → 入选与仓位约束 → 风险缩放 → 数量与订单草稿**")
    st.caption("分数是模型预测的持有期相对收益，排序不等于成交指令。现金和风险限制在生成数量之前生效。")
    decision = report.get("decision") or {}
    if not decision:
        st.info("暂无决策记录。先完成真实数据采集与实验；不会展示示例仓位冒充当前结果。")
        return
    model = str(decision.get("model", "未记录"))
    if model in failed_models(report):
        st.error("决策模型的训练状态为失败，暂不展示该模型的仓位与订单。请检查运行输出。")
        return
    st.warning("仅为独立模拟账户的订单草稿。参考价来自完整日K，状态为草稿且 requires_requote=true；页面不会读取真实持仓或提交订单。")
    capital = finite_number(decision.get("capital"))
    cols = st.columns(3)
    cols[0].metric("决策模型", label(model))
    cols[1].metric("信号日期", str(decision.get("as_of") or "未记录"))
    cols[2].metric("模拟组合金额", f"{capital:,.2f}" if capital is not None else "未记录")
    diagnostics = decision.get("diagnostics") or {}
    if diagnostics:
        risk_columns = st.columns(3)
        before = finite_number(diagnostics.get("annual_vol_before_scale"))
        scale = finite_number(diagnostics.get("risk_scale"))
        after = finite_number(diagnostics.get("annual_vol_after_scale"))
        risk_columns[0].metric("缩放前年化波动", f"{before:.2%}" if before is not None else "未记录")
        risk_columns[1].metric("风险缩放系数", f"{scale:.4f}" if scale is not None else "未记录")
        risk_columns[2].metric("缩放后年化波动", f"{after:.2%}" if after is not None else "未记录")
    weights = decision.get("weights") or {}
    prices = decision.get("reference_prices") or {}
    predictions = records(report.get("predictions"))
    scores = decision.get("scores") or {}
    if not isinstance(scores, dict):
        scores = {}
    as_of = str(decision.get("as_of") or "")[:10]
    if not scores and not predictions.empty and {"date", "symbol", "model", "score"}.issubset(predictions.columns):
        matching = predictions[(predictions["model"] == model) & (predictions["date"].astype(str).str[:10] == as_of)]
        if not matching.duplicated("symbol").any():
            scores = matching.set_index("symbol")["score"].to_dict()
    rows = []
    for symbol, raw_weight in weights.items():
        weight = finite_number(raw_weight)
        price = finite_number(prices.get(symbol))
        asset_vol = finite_number((diagnostics.get("asset_annual_vol") or {}).get(symbol))
        rows.append({"标的": symbol, "同日预测分数": finite_number(scores.get(symbol)), "估计年化波动": asset_vol, "目标权重": weight, "参考价": price, "目标金额": capital * weight if capital is not None and weight is not None else None})
    if rows:
        st.subheader("分数到目标权重")
        frame = pd.DataFrame(rows).sort_values("目标权重", ascending=False)
        st.dataframe(frame.style.format({"同日预测分数": "{:.4%}", "估计年化波动": "{:.2%}", "目标权重": "{:.2%}", "参考价": "{:,.4f}", "目标金额": "{:,.2f}"}, na_rep="—"), use_container_width=True, hide_index=True)
        stock_sum = sum(finite_number(value) or 0 for key, value in weights.items() if str(key).upper() not in {"CASH", "__CASH__", "现金"})
        st.write(f"股票目标权重合计：{stock_sum:.2%}；剩余现金权重：{1-stock_sum:.2%}（按目标权重计算）。")
        if not scores:
            st.caption("报告未提供该信号日的逐股分数，留空显示；没有拿其他日期的预测替代。")
    else:
        st.info("本次未记录目标股票权重；可能是所有分数均未通过入选阈值。原因以风险诊断为准。")
    st.subheader("数量与订单草稿")
    orders = records(decision.get("orders"))
    if orders.empty:
        st.info("本次没有订单草稿。目标与现有模拟数量一致、未过阈值或低于最小交易额，都可能不产生订单。")
    else:
        st.dataframe(orders, use_container_width=True, hide_index=True)
        st.caption("BUY / SELL 表示模拟数量差的方向；成交价、可买数量和现金需在执行前重新核对。草稿不等于已发送或已成交。")
    with st.expander("入选、波动与风险缩放的完整数值", expanded=True):
        st.json(decision.get("diagnostics") or {"说明": "未记录风险诊断"})
    with st.expander("决策原始记录"):
        st.json(decision)


def main() -> None:
    st.set_page_config(page_title="Alpha Lab", page_icon="📈", layout="wide")
    st.sidebar.title("Alpha Lab")
    st.sidebar.caption("自己的策略研究工作台")
    st.sidebar.toggle("English", value=False, key="english")
    if st.sidebar.button("重新读取结果", use_container_width=True):
        st.rerun()
    report, load_error = read_json(LATEST)
    project_config, config_error = read_json(ROOT / "config.json")
    config = report.get("config") or project_config
    st.sidebar.caption("只读本机研究结果 · 无订单提交功能")
    if report.get("run_id"):
        st.sidebar.caption(f"运行：{report['run_id']}")
    if config_error:
        st.warning(config_error)
    show_messages(report)
    pages = st.tabs(["研究结果", "因子到决策", "数据", "数学原理", "论文机制复现"])
    with pages[0]:
        results_page(report, load_error)
    with pages[1]:
        decision_page(report)
    with pages[2]:
        data_page(report, config, load_error)
    with pages[3]:
        render_math(config, lang="en" if english() else "zh")
    with pages[4]:
        mechanism_page()


if __name__ == "__main__":
    main()
