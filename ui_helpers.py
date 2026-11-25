"""Language selection at the presentation boundary; stored records stay untouched."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as raw_st


EN = {
    "初始等权买入持有": "Initial equal-weight buy and hold", "基准，不训练": "Benchmark, no training",
    "相同网络 MSE 对照": "Same-network MSE control", "ADNN 平滑 IC 机制": "ADNN smooth-IC mechanism",
    "论文机制复现": "Paper mechanism study",
    "独立比较相同网络的 MSE 与同日横截面平滑 IC 损失；只研究论文的一项机制，不是 ADNN 完整复现，也不属于 DDPM 增强实验。": "An independent comparison of MSE and same-date cross-sectional smooth-IC loss with the same network. This studies one paper mechanism, not the full ADNN system or the DDPM augmentation experiment.",
    "尚无论文机制实验结果。主研究结果不受影响。": "No paper mechanism results yet. The main research results remain available.",
    "原始排序分数用于 Rank IC；只有经独立验证期校准成相对收益后，才能与成本阈值比较并转换仓位。": "Use raw ranking scores for Rank IC. Calibrate them to excess returns on a separate validation period before comparing with cost thresholds or sizing positions.",
    "论文范围、校准与复现差异": "Paper scope, calibration and reproduction differences",
    "训练目标记录": "Training objective records",
    "当前测试期，所有有记录的预测模型平均 Rank IC 均为负，尚未显示正向排序优势。净值变化需结合市场暴露与基准分析。": "All recorded prediction models have negative mean Rank IC in this test period, showing no positive ranking edge. Interpret equity changes alongside market exposure and benchmarks.",
    "ADNN 原论文": "ADNN source paper", "独立验证期收益校准": "Return calibration on separate validation data",
    "校准斜率限制为非负；若斜率为0，收益预测成为常数，校准后的 Rank IC 可为空。这不改变原始分数的 Rank IC。": "The calibration slope is constrained to be nonnegative. If it is zero, return forecasts are constant and calibrated Rank IC can be undefined; raw-score Rank IC is unchanged.",
    "MSE 与负平滑 IC 的量纲和目标不同，分别绘图，不能按数值高低比较两个模型。": "MSE and negative smooth IC have different scales and objectives. They are plotted separately; do not compare models by the numeric level of these losses.",
    "训练步": "Training step", "训练目标": "Training objective",
    "排序到交易的检查": "From ranking to trading",
    "校准后预测是否为常数": "Constant calibrated forecast",
    "本次两个模型的校准斜率均为0，收益预测退化为常数；校准后 Rank IC 未定义。校准预测未过成本门槛，组合保持现金、没有交易。原始 Rank IC 略为正不等于建议买入。": "Both models have zero calibration slopes in this run, yielding constant return forecasts and undefined calibrated Rank IC. Forecasts fail the cost threshold, so both portfolios stay in cash with no trades. A slightly positive raw Rank IC is not a buy recommendation.",
    "缩放前年化波动": "Annual volatility before scaling", "缩放后年化波动": "Annual volatility after scaling",
    "风险缩放系数": "Risk scale", "估计年化波动": "Estimated annual volatility",
    "Ridge 基线": "Ridge baseline", "MLP 深度学习": "MLP deep learning",
    "MLP 重采样对照": "Resampled MLP control", "条件 DDPM 增强 MLP": "Conditional DDPM + MLP",
    "实验已完成": "Experiment completed", "数据暂不可用": "Data unavailable",
    "历史样本不足": "Insufficient history", "实验失败": "Experiment failed",
    "在项目目录的终端中运行。采集与训练由你主动启动，页面只读取结果：": "Run these commands in a terminal inside the project directory. You start collection and training explicitly; this page only reads saved results:",
    "数据不足或接口失败时，先处理报告中的原因；页面不会用随机行情补出收益。": "Resolve the reported data or API issue first. Missing returns are never replaced with random market data.",
    "日频股票研究 · moomoo 数据优先 · 所有边界按完整美东交易日处理": "Daily equity research · moomoo data preferred · boundaries use completed US Eastern market sessions",
    "固定原型股票池不等于历史时点股票池；当前研究仍有生存者偏差风险。复权OHLC是成交价近似，分红口径以本次运行报告为准。": "The fixed prototype universe is not a point-in-time historical universe and may have survivorship bias. Adjusted OHLC approximates execution prices; consult this run's dividend treatment.",
    "示例研究股票池，尚未确认是你的持仓名单。": "Example research universe; your actual holdings have not been confirmed.",
    "修改 config.json 后，已有结果不会随之改变；需要重新运行实验才能评价新设定。": "Changing config.json does not change saved results. Rerun the experiment to evaluate new settings.",
    "报告尚未记录质量检查，不能据此推断数据已通过验证。": "No quality checks were recorded. This does not establish that the data passed validation.",
    "只比较同一测试日的实际记录。DDPM增强与普通MLP、重采样对照分别配对；不把更多训练样本本身的作用算成生成模型的独有优势。": "Pair actual records from the same test date. Compare DDPM augmentation with both ordinary and resampled MLPs to separate generation from the effect of more training samples.",
    "需要条件 DDPM 增强模型与至少一个对照模型在相同测试日的 Rank IC。当前记录不足。": "Paired Rank IC requires DDPM-augmented MLP and at least one control on common test dates. There are not enough records yet.",
    "同一模型同一日期出现重复 IC；先检查实验输出，暂不汇总成对增量。": "Duplicate model/date IC records were found. Check the experiment output before summarizing paired differences.",
    "模型有记录，但没有可配对的共同测试日。": "Model records exist, but there are no common test dates to pair.",
    "这是描述统计，没有置信区间或显著性结论。相邻五日标签会重叠，日期之间可能相关；需要额外的分块检验与多种子实验。": "Descriptive statistics only; no confidence interval or significance claim. Overlapping multi-day labels can induce serial dependence. Block-based tests and multiple seeds require separate experiments.",
    "指标来自保存的运行报告；小样本正收益或正 IC 不能证明策略已具有可交易优势。": "Metrics come from the saved run. Positive returns or IC in a small sample do not establish a tradable edge.",
    "没有可绘制的预测或组合结果。数学原理页可独立查看。": "No prediction or portfolio series is available to plot. The mathematics page remains available.",
    "请选择完整的开始和结束日期。": "Select both a start and an end date.",
    "这些控件仅改变图表范围；顶部指标仍是整次运行的指标，不会重新训练或执行策略。": "These controls change the chart view only. The metrics above still describe the full run. No model is trained and no strategy is executed.",
    "至少选择一个模型后查看图表。": "Select at least one model to view charts.",
    "所选范围没有有效 Rank IC；未给未知日期填零。": "There is no valid Rank IC in this range. Missing dates are not filled with zero.",
    "**历史价量 → DL / GenAI 预测分数 → 入选与仓位约束 → 风险缩放 → 数量与订单草稿**": "**Historical price/volume → DL / GenAI forecast → selection and constraints → risk scaling → quantities and order drafts**",
    "分数是模型预测的持有期相对收益，排序不等于成交指令。现金和风险限制在生成数量之前生效。": "Scores predict holding-period excess returns; a ranking is not an execution instruction. Cash and risk constraints apply before quantities are calculated.",
    "暂无决策记录。先完成真实数据采集与实验；不会展示示例仓位冒充当前结果。": "No decision record yet. Collect real data and complete an experiment first. Example holdings are not shown as current results.",
    "决策模型的训练状态为失败，暂不展示该模型的仓位与订单。请检查运行输出。": "The decision model failed training. Its weights and orders are withheld; check the run output.",
    "仅为独立模拟账户的订单草稿。参考价来自完整日K，状态为草稿且 requires_requote=true；页面不会读取真实持仓或提交订单。": "Drafts for an independent simulated portfolio only. Reference prices are completed daily closes; drafts require fresh quotes (requires_requote=true). This page does not read real holdings or submit orders.",
    "报告未提供该信号日的逐股分数，留空显示；没有拿其他日期的预测替代。": "Per-symbol scores for this signal date were not recorded. They remain blank; forecasts from other dates are not substituted.",
    "本次未记录目标股票权重；可能是所有分数均未通过入选阈值。原因以风险诊断为准。": "No target equity weights were recorded. Scores may not have passed the selection threshold; consult the risk diagnostics.",
    "本次没有订单草稿。目标与现有模拟数量一致、未过阈值或低于最小交易额，都可能不产生订单。": "No order drafts this time. An unchanged simulated position, a failed threshold, or a trade below the minimum value can result in no order.",
    "BUY / SELL 表示模拟数量差的方向；成交价、可买数量和现金需在执行前重新核对。草稿不等于已发送或已成交。": "BUY / SELL is the direction of a simulated quantity change. Recheck prices, buying capacity and cash before any future execution. A draft is neither submitted nor filled.",
    "只读本机研究结果 · 无订单提交功能": "Read-only local research · no order submission",
    "自己的策略研究工作台": "Your strategy research workspace",
    "训练失败，未用其他模型替代其结果。": "failed training; its results were not replaced by another model.",
    "顶层必须是 JSON 对象。": "must contain a top-level JSON object.",
    "尚未生成 ": "Not generated yet: ", "读取 ": "Reading ", " 失败：": " failed: ",
    "暂无可用的": "No available records for ", "记录。": ".",
    "**数据来源：**": "**Data source:**", "**数据区间：**": "**Data period:**",
    "**返回的标的：**": "**Returned symbols:**", "**本次运行配置**": "**Run configuration**",
    "**项目配置**": "**Project configuration**", "**运行与数据版本**": "**Run and data lineage**",
    "股票池：": "Example research universe: ", "；基准：": "; benchmark: ",
    "预测和调仓跨度：": "Forecast and rebalance horizon: ", " 个交易日；种子：": " trading sessions; seed: ",
    "DDPM 增强 − ": "DDPM augmentation − ", " 日滚动平均 Rank IC": "-observation rolling mean Rank IC",
    "股票目标权重合计：": "Total target equity weight: ", "；剩余现金权重：": "; residual cash weight: ",
    "（按目标权重计算）。": " (calculated from target weights).", "运行：": "Run: ",
    "数据": "Data", "状态": "Status", "共同交易日": "Common sessions", "数据标的数": "Symbols returned",
    "尚无实验结果": "No experiment yet", "未记录": "Not recorded", "质量检查": "Quality checks",
    "当前研究设定": "Research settings", "配置与数据追溯": "Configuration and lineage",
    "尚无完整结果。": "No complete results yet.", "尚无完整实验。": "No complete experiment yet.",
    "GenAI 的成对增量": "Paired GenAI increment", "比较": "Comparison", "共同日期数": "Paired dates",
    "平均 ΔRank IC": "Mean ΔRank IC", "增量为正的日期占比": "Share of positive increments",
    "每日 ΔRank IC": "Daily ΔRank IC", "实验结果": "Research results", "研究结果": "Research results",
    "模型": "Model", "训练状态": "Training status", "训练记录与失败原因": "Training records and failures",
    "查看范围": "Chart view", "显示模型": "Models", "图表日期": "Date range",
    "每日横截面 Rank IC": "Daily cross-sectional Rank IC", "滚动 IC 窗口（有效观测日）": "Rolling IC window (observations)",
    "SPY 基准": "SPY benchmark", "含成交成本的账户权益": "Account equity after transaction costs",
    "历史峰值以来的回撤": "Drawdown from previous peak", "现金比例与真实换手记录": "Cash weights and realized turnover",
    "训练参数与模型状态": "Training settings and model status", "因子到决策": "Factor to decision",
    "决策模型": "Decision model", "信号日期": "Signal date", "模拟组合金额": "Simulated equity",
    "标的": "Symbol", "同日预测分数": "Same-date forecast", "目标权重": "Target weight",
    "参考价": "Reference price", "目标金额": "Target notional", "分数到目标权重": "Forecast to target weights",
    "数量与订单草稿": "Quantities and order drafts", "入选、波动与风险缩放的完整数值": "Selection, volatility and risk scaling",
    "未记录风险诊断": "Risk diagnostics not recorded", "说明": "Note", "决策原始记录": "Raw decision record",
    "数学原理": "Mathematics", "重新读取结果": "Reload saved results",
}

COLUMNS = {
    "rank_ic_mean": ("平均 Rank IC", "Mean Rank IC"), "rank_ic_std": ("Rank IC 标准差", "Rank IC std. dev."),
    "raw_rank_ic_mean": ("原始分数平均 Rank IC", "Raw-score mean Rank IC"),
    "calibrated_rank_ic_mean": ("收益校准后平均 Rank IC", "Calibrated-return mean Rank IC"),
    "n_ic_dates": ("有效 IC 日期数", "Valid IC dates"), "n_test_rows": ("测试样本数", "Test rows"),
    "total_turnover": ("累计实际换手", "Total realized turnover"), "cagr": ("年化收益率", "CAGR"),
    "intercept": ("校准截距", "Calibration intercept"), "slope": ("校准斜率", "Calibration slope"),
    "fit_start": ("拟合开始日", "Fit start"), "fit_end": ("拟合结束日", "Fit end"),
    "fit_rows": ("拟合样本数", "Fit rows"), "fit_days": ("拟合日期数", "Fit dates"),
    "rmse": ("均方根误差", "RMSE"), "monotonic_nonnegative_slope": ("斜率非负约束", "Nonnegative slope constraint"),
    "rmse_decimal": ("收益校准均方根误差", "Return-calibration RMSE"),
    "flat_calibration": ("校准为常数", "Flat calibration"), "fit_label_end": ("拟合标签结束日", "Fit label end"),
    "trade_count": ("成交笔数", "Executed trades"),
    "cash": ("现金金额", "Cash"), "daily_return": ("单日收益", "Daily return"),
    "account_scope": ("账户范围", "Account scope"), "order_type": ("订单类型", "Order type"),
    "price_basis": ("参考价口径", "Price basis"), "capital_basis": ("权益口径", "Capital basis"),
    "independent_simulated_portfolio": ("独立模拟组合", "Independent simulated portfolio"),
    "REFERENCE_DRAFT": ("参考草稿", "Reference draft"),
    "last_completed_daily_close_reference": ("最后完整日K收盘参考价", "Last completed daily close reference"),
    "user_configured_simulated_equity": ("用户配置的模拟权益", "User-configured simulated equity"),
    "symbol": ("标的", "Symbol"), "side": ("方向", "Side"), "quantity": ("草稿数量", "Draft quantity"),
    "quantity_delta": ("有号数量差", "Signed quantity change"), "current_quantity": ("现有模拟数量", "Current simulated quantity"),
    "target_quantity": ("目标数量", "Target quantity"), "requested_target_quantity": ("原始目标数量", "Requested target quantity"),
    "reference_price": ("参考价", "Reference price"), "estimated_notional": ("预计成交金额", "Estimated notional"),
    "estimated_one_way_cost": ("预计单边成本", "Estimated one-way cost"), "target_weight": ("目标权重", "Target weight"),
    "status": ("状态", "Status"), "requires_requote": ("需重新报价", "Requires fresh quote"),
    "no_submit": ("禁止提交", "No submission"), "reference_only": ("仅供参考", "Reference only"),
    "as_of": ("信号日期", "Signal date"), "run_id": ("运行编号", "Run ID"),
    "date": ("日期", "Date"), "model": ("模型", "Model"), "equity": ("账户权益", "Equity"),
    "drawdown": ("回撤", "Drawdown"), "benchmark_equity": ("基准权益", "Benchmark equity"),
    "cash_weight": ("现金权重", "Cash weight"), "turnover": ("实际换手", "Realized turnover"),
    "annualized_return": ("年化收益", "Annualized return"), "cumulative_return": ("累计收益", "Cumulative return"),
    "total_return": ("累计收益", "Total return"), "sharpe": ("夏普比率", "Sharpe"),
    "sharpe_ratio": ("夏普比率", "Sharpe ratio"), "max_drawdown": ("最大回撤", "Maximum drawdown"),
    "mean_rank_ic": ("平均 Rank IC", "Mean Rank IC"), "rank_ic": ("Rank IC", "Rank IC"),
    "ic_mean": ("平均 IC", "Mean IC"), "ic_ir": ("IC 信息比率", "IC information ratio"),
    "annualized_volatility": ("年化波动率", "Annualized volatility"), "total_cost": ("累计成交成本", "Total transaction cost"),
    "BUY": ("买入草稿", "BUY draft"), "SELL": ("卖出草稿", "SELL draft"), "DRAFT": ("草稿", "Draft"),
    "success": ("成功", "Success"), "failed": ("失败", "Failed"),
}


def english() -> bool:
    return bool(raw_st.session_state.get("english", False))


def translate(value: Any, *, use_english: bool | None = None) -> Any:
    if not isinstance(value, str):
        return value
    chosen_language = english() if use_english is None else use_english
    if value.startswith("holdings."):
        return ("Holdings " if chosen_language else "持仓 ") + value.split(".", 1)[1]
    if value in COLUMNS:
        return COLUMNS[value][1 if chosen_language else 0]
    if not chosen_language:
        return value
    if value in EN:
        return EN[value]
    # Dynamic sentences combine translated authored fragments and data values.
    result = value
    for original in sorted(EN, key=len, reverse=True):
        if original in result:
            result = result.replace(original, EN[original])
    return result


def display_frame(frame: Any) -> Any:
    def localize(data: pd.DataFrame) -> pd.DataFrame:
        result = data.copy()
        result.columns = [translate(column) for column in result.columns]
        for column in result.select_dtypes(include=["object", "string"]).columns:
            result[column] = result[column].map(translate)
        return result
    if isinstance(frame, pd.DataFrame):
        return localize(frame)
    # Styler formatting is position based, so labels can change without losing formats.
    if hasattr(frame, "data") and isinstance(frame.data, pd.DataFrame):
        frame.data = localize(frame.data)
    return frame


class LocalizedUI:
    """Small proxy for authored labels; raw JSON keeps its exact audit fields."""

    def __init__(self, target: Any = raw_st):
        self.target = target

    @property
    def sidebar(self) -> "LocalizedUI":
        return LocalizedUI(self.target.sidebar)

    def __getattr__(self, name: str) -> Any:
        method = getattr(self.target, name)
        if name == "columns":
            return lambda *args, **kwargs: [LocalizedUI(column) for column in method(*args, **kwargs)]
        if name == "tabs":
            return lambda names, **kwargs: method([translate(value) for value in names], **kwargs)
        if name == "dataframe":
            return lambda frame, **kwargs: method(display_frame(frame), **kwargs)
        if name == "plotly_chart":
            def chart(figure, **kwargs):
                if figure.layout.title.text:
                    figure.layout.title.text = translate(figure.layout.title.text)
                for axis in (figure.layout.xaxis, figure.layout.yaxis):
                    if axis.title.text:
                        axis.title.text = translate(axis.title.text)
                for trace in figure.data:
                    if trace.name:
                        trace.name = translate(trace.name)
                return method(figure, **kwargs)
            return chart
        if name in {"title", "subheader", "header", "caption", "info", "warning", "error", "write", "markdown", "metric", "multiselect", "date_input", "slider", "expander", "radio", "button"}:
            def localized(*args, **kwargs):
                translated = tuple(translate(arg) for arg in args)
                for key in ("help", "placeholder", "label"):
                    if key in kwargs:
                        kwargs[key] = translate(kwargs[key])
                if "format_func" in kwargs:
                    formatter = kwargs["format_func"]
                    language = english()
                    kwargs["format_func"] = lambda value: translate(formatter(value), use_english=language)
                return method(*translated, **kwargs)
            return localized
        return method
