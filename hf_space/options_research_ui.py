"""Offline options-structure research page: audited metadata and TOY calculators.

No data fetching, private files, account access or execution is exposed here.
Every calculator requires an explicit action; language and navigation keep the
last executed teaching report unchanged. Observed metadata is never a price input.
"""
from __future__ import annotations

import copy
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from hf_space import ui_theme as ui


AUDIT = {
    "audited_at_utc": "2026-11-27T05:54:31Z",
    "source_kind": "observed_static_reference_metadata_only",
    "static_chains": [
        {"underlying": "SPY", "expiry": "2026-11-27", "contracts": 438,
         "source_updated_at": None, "retrieved_at": "2026-11-27T05:51:44.987780Z",
         "available_at": "2026-11-27T05:51:44.987780Z", "oi_effective_date": None,
         "oi_published_at": None,
         "sha256": "08652294898033a7e9149e2a1d25eb0b2798af152f6830ca912aa12808ae638f"},
        {"underlying": "QQQ", "expiry": "2026-11-27", "contracts": 514,
         "source_updated_at": None, "retrieved_at": "2026-11-27T05:52:05.352600Z",
         "available_at": "2026-11-27T05:52:05.352600Z", "oi_effective_date": None,
         "oi_published_at": None,
         "sha256": "0163d93893b97bbd05257f691a96137009011bd34b349f8f7bcd553cc5f76446"},
    ],
    "current_full_dynamic_chain": "NOT_OBTAINED",
    "historical_predictive_oos": "NOT_ESTIMABLE",
    "real_max_pain": "BLOCKED",
    "real_dealer_inventory": "NOT_IDENTIFIABLE",
    "read_only_request_counts": {"desktop_static_chains": 2, "desktop_contract_snapshots": 2,
                                "official_cboe_gets": 2, "snapshot_timeout_seconds": 20},
    "raw_market_data_download": False,
    "account_queries": 0, "orders": 0,
}

GEX_MODELS = {
    "fixed_call_put": ("B：Call正／Put负代理", "B: call-positive / put-negative proxy"),
    "prior_inventory": ("C：概率库存先验", "C: prior inventory scenario"),
    "unsigned_concentration": ("U：无符号集中度", "U: unsigned concentration"),
    "all_dealer_long": ("压力情景：全部做市商多头", "Stress: all dealer long"),
    "all_dealer_short": ("压力情景：全部做市商空头", "Stress: all dealer short"),
}
GEX_COLORS = ("#087f8c", "#6554a4", "#b67820", "#718096", "#aa5266")


def _remember(key):
    st.session_state["_saved_" + key] = copy.deepcopy(st.session_state[key])


def _input(kind, key, default, label, *, host=None, **kwargs):
    memory = "_saved_" + key
    if memory not in st.session_state:
        st.session_state[memory] = copy.deepcopy(st.session_state.get(key, default))
    st.session_state[key] = copy.deepcopy(st.session_state[memory])
    return getattr(host or st, kind)(label, key=key, on_change=_remember, args=(key,), **kwargs)


def run_demo_gex(**settings):
    """Only the core's explicitly fictional, complete example can reach this UI."""
    from hf_space.gex_scenarios import make_teaching_gex_contracts, run_gex_scenarios
    contracts = make_teaching_gex_contracts()
    spot = settings["spot"]
    grid = [spot * (0.7 + index * .01) for index in range(61)]
    report = run_gex_scenarios(contracts, spot=spot, price_grid=grid,
        prior_long_call=settings["prior_long_call"], prior_long_put=settings["prior_long_put"],
        dealer_fraction=settings["dealer_fraction"], iv_shift=settings["iv_shift"],
        complete_chain_verified=True, source_kind="synthetic_demo")
    return {"kind": "gex_teaching", "source_kind": "synthetic_demo", "underlying": "TOY",
            "inputs": copy.deepcopy(settings), "result": report,
            "claims": {"market_observation": False, "dealer_inventory_estimated_from_labels": False,
                       "confidence_interval": False, "orders_submitted": False}}


def run_demo_max_pain(**settings):
    from research.max_pain import compute_max_pain, distance_to_frozen_interval, loss_at_prices, make_teaching_snapshot
    snapshot = make_teaching_snapshot("flat_interval")
    template = snapshot["contracts"][0]
    rows = []
    for side, strike, oi in (("CALL", settings["call_strike"], settings["call_oi"]),
                             ("PUT", settings["put_strike"], settings["put_oi"])):
        row = copy.deepcopy(template)
        row.update(contract_id=f"TOY-EXPLICIT-{side}", underlying="TOY", option_type=side,
                   strike=strike, open_interest=oi, multiplier=settings["multiplier"],
                   multiplier_source="explicit fictional teaching contract specification",
                   terms_source="explicit fictional standard-linear teaching specification")
        rows.append(row)
    snapshot["contracts"] = rows
    snapshot["listed_standard_contract_count"] = len(rows)
    result = compute_max_pain(snapshot)
    minimizer = result.get("minimizer")
    distance = distance_to_frozen_interval(settings["spot"], minimizer["lower"], minimizer["upper"]) if minimizer else None
    top = max(settings["call_strike"], settings["put_strike"], settings["spot"]) * 1.25
    grid = sorted({0., settings["call_strike"], settings["put_strike"], settings["spot"],
                   *[top * index / 60 for index in range(61)]})
    losses = loss_at_prices(snapshot, grid)
    curve = [{"settlement_price": price, "loss": float(loss)} for price, loss in zip(grid, losses)]
    return {"kind": "max_pain_teaching", "source_kind": "synthetic_demo", "underlying": "TOY",
            "inputs": copy.deepcopy(settings), "result": result, "loss_curve": curve,
            "distance_to_minimizer": distance,
            "claims": {"market_observation": False, "OI_changes_with_spot": False,
                       "future_dynamic_target_known": False, "orders_submitted": False}}


def _save_demo(key, report):
    # The page has no observed data or arbitrary upload/URL input to serialize.
    if report.get("source_kind") != "synthetic_demo" or report.get("underlying") != "TOY":
        raise ValueError("Only the explicit TOY teaching report can be saved")
    saved = {key: copy.deepcopy(report[key]) for key in
             ("kind", "source_kind", "underlying", "inputs", "result", "loss_curve", "distance_to_minimizer", "claims") if key in report}
    encoded = json.dumps(saved, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    st.session_state[key + "_report"] = saved
    st.session_state[key + "_json"] = encoded


def _audit_tab(tr):
    st.subheader(tr("先确认我们实际上有什么数据", "Start with the Data Actually Observed"))
    st.caption(tr("以下是2026-11-27的固定审计记录，不是联网刷新后的实时行情。此页不读取本机文件、账户或API。",
                  "This is a fixed audit from 2026-11-27, not a live refresh. This page reads no local files, accounts or APIs."))
    unknown = tr("未知／未披露", "Unknown / not disclosed")
    rows = []
    for row in AUDIT["static_chains"]:
        rows.append({tr("标的", "Underlying"): row["underlying"], tr("到期日", "Expiry"): row["expiry"],
                     tr("静态合约数", "Static contracts"): row["contracts"],
                     tr("供方更新时间", "Provider update time"): unknown,
                     tr("接收时间UTC", "Received UTC"): row["retrieved_at"],
                     tr("本机首次可得UTC", "Locally available UTC"): row["available_at"],
                     tr("OI有效日", "OI effective date"): unknown,
                     tr("OI公布时间", "OI publication time"): unknown})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.write(tr("静态链包含合约、行权价、Call／Put、到期及标准／非标枚举；本次每手股数均见100。它不提供本次完整OI、IV或Greeks，也没有独立核实全部调整交付物。不能将新静态合约信息拼到旧行情后称作历史全链。",
                "The reference chains contain contracts, strikes, call/put sides, expiry and standard/non-standard flags; observed lot sizes were 100. They do not supply the current complete OI, IV or Greeks, and adjusted deliverables were not independently verified. Joining new references to old prices does not create a historical full chain."))
    evidence = [
        ("当前完整OI／IV／Greeks", "Current complete OI / IV / Greeks", "未取得：两次少量合约快照超时", "Not obtained: two small contract-snapshot requests timed out"),
        ("旧Cboe单点链", "Older Cboe single snapshots", "SPY 12706／QQQ 10810条；供方时间2026-11-23，时区、OI有效日及乘数未披露", "SPY 12,706 / QQQ 10,810 rows; provider timestamp 2026-11-23, with timezone, OI effective date and multiplier undisclosed"),
        ("历史合约OI归档", "Historical contract OI archive", "仅32份合约、一个观察日；不足以回测", "Only 32 contracts on one observation date; insufficient for backtesting"),
        ("做市商身份／开平仓", "Dealer identity / open-close", "不可识别；BUY／SELL不是参与者或开平标签", "Not identifiable; BUY/SELL is not a participant or open-close label"),
        ("近期异动覆盖", "Recent unusual-activity coverage", "仅供方筛选样本；不是完整逐笔或全市场库存", "A vendor-selected sample, not a complete tape or market inventory"),
        ("新的Cboe查询", "Fresh Cboe requests", "SPY／QQQ各一次GET，均403，未重试", "One GET each for SPY / QQQ; both returned 403, without retries"),
    ]
    st.dataframe(pd.DataFrame([{tr("数据", "Data"): tr(zh, en), tr("实际边界", "Observed limit"): tr(dzh, den)}
                               for zh, en, dzh, den in evidence]), hide_index=True, use_container_width=True)
    st.info(tr("真实历史增量预测：NOT_ESTIMABLE；真实自建Max Pain／GEX：BLOCKED；做市商真实库存：NOT_IDENTIFIABLE。教学计算器不改变这些状态。",
               "Historical incremental prediction: NOT_ESTIMABLE. Real self-computed Max Pain / GEX: BLOCKED. Actual dealer inventory: NOT_IDENTIFIABLE. Teaching calculators do not change these statuses."))
    st.caption(tr("updated_at是供方计算更新时间；不能替代OI有效日、公布时间或研究中真正可得时间。未知值保持未知。",
                  "updated_at is a vendor calculation/update time. It cannot replace OI effective date, publication time or actual research availability. Unknown values stay unknown."))
    st.markdown(tr("**后续有界审计：2026-11-27 12:08—12:09美东**", "**Later bounded audit: 2026-11-27 12:08–12:09 ET**"))
    st.write(tr("订阅basic后，8份所选合约成功返回OI／IV／Greeks；两到期日共2118份静态合约，4合约共400条最近成交。它们不是完整动态链或连续历史。盘口仍缺源时间，部分逐笔／接收时间有时钟差异，不能据此做严格历史报价匹配。",
        "After subscribing to basic quotes, 8 selected contracts returned OI/IV/Greeks; two expiries contain 2,118 static contracts, with 400 recent prints across 4 contracts. This is not a full dynamic chain or continuous history. Books lack source timestamps and some print/receipt clocks disagree, preventing a verified historical quote join."))
    st.caption(tr("免费Cboe旧日分类样本另在本机核验；不是上述moomoo成交的同期MM标签。两者同日逐笔标签匹配仍为0，当前净库存q未知。",
        "Free Cboe historical capacity samples are audited separately on the local computer. They are not contemporaneous MM labels for these moomoo prints. Same-date cross-source labeled print matches remain zero, and current net inventory q is unknown."))
    with st.expander(tr("来源指纹与请求范围", "Source Fingerprints and Request Scope")):
        st.json(AUDIT)
        st.caption(tr("只展示安全汇总与哈希；不含原始期权链、文件路径、凭据或账户。", "Safe aggregates and hashes only; no raw option chain, file paths, credentials or accounts."))


def _model_table(tr):
    specs = [
        ("A", "不使用GEX的基线", "Baseline without GEX", "波动、趋势、时段、事件", "Volatility, trend, time of day, events", "尚无样本外指标", "No out-of-sample score yet"),
        ("B", "固定Call正／Put负", "Fixed call-positive / put-negative", "明确符号假设的对照", "A declared sign-assumption comparison", "不是实际库存", "Not actual inventory"),
        ("C", "概率库存先验", "Prior inventory", "改变净多概率与做市商份额", "Vary net-long prior and dealer share", "无标签校准，非置信区间", "No label calibration; not a confidence interval"),
        ("D", "有MM标签的库存递推", "MM-labeled inventory updates", "本机可核分类样本买减卖；存量另需初仓与覆盖", "Local classified samples support side accounting; stock needs starting inventory and coverage", "抽样流不识别完整净库存", "Sampled flow does not identify complete net inventory"),
        ("U", "无符号集中度", "Unsigned concentration", "研究绝对Gamma聚集", "Study absolute gamma concentration", "无对冲方向，不称净GEX", "No hedge direction; not net GEX"),
    ]
    st.dataframe(pd.DataFrame([{tr("模型", "Model"): key, tr("定义", "Definition"): tr(zh, en),
        tr("可以研究", "Can study"): tr(czh, cen), tr("不能声称", "Cannot claim"): tr(nzh, nen)}
        for key, zh, en, czh, cen, nzh, nen in specs]), hide_index=True, use_container_width=True)


def _gex_tab(tr):
    _model_table(tr)
    st.latex(r"GEX_{1\%}=0.01\,S^2\sum_i q_i M_i\Gamma_i")
    st.latex(r"q_i=(2p_i-1)\,f_i\,OI_i")
    st.caption(tr("本页定义美元Gamma名义敞口；上涨1%时股票对冲名义变化约为−GEX。负GEX不预测涨跌方向，单位也不冒充供应商图表的未披露口径。",
                  "This page defines dollar gamma exposure; a +1% move implies an approximate stock-hedge notional change of −GEX. Negative GEX does not forecast direction, and this unit is not claimed to match an undisclosed vendor convention."))
    st.warning(tr("以下仅为虚构TOY的欧式固定IV教学情景，与上面的SPY／QQQ审计没有数据连接。极端全多／全空是压力情景，不是同等可能的真相。",
                  "The following are fictional TOY European fixed-IV scenarios, disconnected from the SPY / QQQ audit above. All-long / all-short extremes are stress scenarios, not equally likely truths."))
    a, b = st.columns(2)
    spot = _input("number_input", "options_gex_spot", 100., tr("TOY假设现价", "TOY hypothetical spot"), host=a, min_value=10., max_value=1000., step=1.)
    level = _input("number_input", "options_gex_reference_level", 105., tr("独立示意集中位", "Separate illustrative concentration level"), host=b, min_value=1., max_value=2000., step=1.)
    distance = (spot - level) / spot
    st.caption(tr("相对示意位置：", "Relative illustrative position: ") + f"{distance:+.2%} · " +
        (tr("集中位在现价下方", "level below spot") if distance > 0 else tr("集中位在现价上方", "level above spot") if distance < 0 else tr("与现价相同", "level equals spot")) +
        tr("。Call／Put侧集中位均可能在现价上方或下方；本输入不是moomoo墙位，也不改变库存。", ". Either call- or put-side concentration can lie above or below spot. This input is not a moomoo wall and does not change inventory."))
    with st.expander(tr("概率先验与IV敏感性", "Inventory-Prior and IV Sensitivity")):
        pc = _input("slider", "options_gex_pc", .6, tr("Call净多概率先验", "Call net-long prior"), min_value=0., max_value=1., step=.05)
        pp = _input("slider", "options_gex_pp", .35, tr("Put净多概率先验", "Put net-long prior"), min_value=0., max_value=1., step=.05)
        fraction = _input("slider", "options_gex_fraction", .5, tr("假设做市商份额", "Assumed dealer share"), min_value=0., max_value=1., step=.05)
        iv = _input("slider", "options_gex_iv_shift", 0., tr("IV绝对变动（小数）", "Absolute IV shift (fraction)"), min_value=-.1, max_value=.3, step=.01)
    if st.button(tr("运行TOY GEX教学情景", "Run TOY GEX teaching scenarios"), key="options_gex_run"):
        try:
            result = run_demo_gex(spot=float(spot), prior_long_call=float(pc), prior_long_put=float(pp),
                                  dealer_fraction=float(fraction), iv_shift=float(iv))
            _save_demo("options_gex", result)
            st.session_state["options_gex_error"] = False
        except Exception:
            st.session_state["options_gex_error"] = True
    if st.session_state.get("options_gex_error"):
        st.error(tr("本次教学情景未完成，请核对输入；没有替换为真实行情或其他结果。", "This teaching calculation did not complete. Check the inputs; no market data or replacement result was substituted."))
    report = st.session_state.get("options_gex_report")
    if report:
        st.caption(tr("图表仍为上次点击运行的TOY参数；改动输入后需再次运行。", "Charts retain the TOY settings from the last Run; run again after changing inputs."))
        core, figure, rows = report["result"], go.Figure(), []
        for (key, labels), color in zip(GEX_MODELS.items(), GEX_COLORS):
            model = core.get("models", {}).get(key, {})
            curve = model.get("curve") or []
            if curve:
                figure.add_trace(go.Scatter(x=[r["spot"] for r in curve], y=[r["gex"] for r in curve], name=tr(*labels), mode="lines", line=dict(color=color)))
            rows.append({tr("情景", "Scenario"): tr(*labels), tr("当期教学值", "Teaching current value"): model.get("current_gex"),
                         tr("采样根信息", "Sampled-root information"): json.dumps(model.get("roots") or {}, ensure_ascii=False)})
        figure.update_layout(template="plotly_white", height=360, margin=dict(l=10, r=10, t=32, b=10),
                             xaxis_title=tr("假设TOY价格", "Hypothetical TOY price"), yaxis_title=tr("教学敞口", "Teaching exposure"))
        st.plotly_chart(figure, use_container_width=True)
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        with st.expander(tr("到期日、互斥DTE桶与模型指纹", "Expiry, Disjoint DTE Buckets and Model Fingerprints")):
            st.caption(tr("0DTE单列，其余桶互斥；这些是同一TOY组合在本次假设现价下的贡献，不能平均各期值。", "0DTE is separate and remaining buckets are disjoint. These are contributions of the same TOY book at the last-run spot; do not average expiry values."))
            for field in ("expiry_contributions", "dte_contributions"):
                values = pd.DataFrame(core.get(field) or [])
                if not values.empty and "model" in values:
                    values["model"] = values["model"].map(lambda key: tr(*GEX_MODELS[key]))
                    st.dataframe(values, hide_index=True, use_container_width=True)
            st.caption(tr("自建无符号OI×Gamma集中峰，保留并列；不是供应商Call／Put Wall。", "Own unsigned OI×Gamma concentration peaks retain ties; they are not vendor Call / Put Walls."))
            st.json(core.get("own_concentration_peaks") or {})
            st.json(core)
        st.download_button(tr("下载TOY GEX教学JSON", "Download TOY GEX teaching JSON"), st.session_state["options_gex_json"],
                           file_name="toy-gex-teaching.json", mime="application/json", key="options_gex_download")
    st.write(tr("0DTE、1—2、3—7、8—30、31—90、>90为互斥桶。最近一期／30日／全部／排最近是重叠视图，不能再次相加。蓝线是条件情景曲线，不是价格轨迹；零点可能多个或没有，网格括根不等于精确找全零点。",
                "The 0DTE, 1–2, 3–7, 8–30, 31–90 and >90 buckets are disjoint. Nearest / 30-day / all / excluding-nearest views overlap and cannot be added again. A profile is a conditional scenario, not a price path. There can be multiple or no zero crossings; grid brackets do not establish every exact root."))
    st.caption(tr("结构性恰好抵消或极端价格下数值无法分辨，不等于找到了可交易的Gamma翻转价。", "Structural cancellation or numerical underflow at extreme prices does not establish a tradable gamma-flip level."))


def _max_pain_tab(tr):
    st.warning(tr("这是可编辑的虚构标准合约计算器。OI、乘数和完整范围由教学设定明确给出；它没有读取SPY／QQQ或任何实际期权持仓。", "This editable calculator uses fictional standard contracts. OI, multipliers and complete scope are explicitly supplied for teaching; no SPY / QQQ or real option positions are read."))
    st.latex(r"L_C(x)=\sum_C OI_i M_i(x-K_i)_+")
    st.latex(r"L_P(x)=\sum_P OI_i M_i(K_i-x)_+")
    st.latex(r"MP_e=\arg\min_{x\geq0}[L_C(x)+L_P(x)]")
    st.caption(tr("每一期单独求最小值集合；可能是点、平底区间或无界射线。不是最大OI行权价，不包含权利金，不把多个到期痛点平均为目标。调整合约需真实交付物，本页仅标准线性教学。",
                  "Minimize separately for each expiry; the solution may be a point, flat interval or unbounded ray. It is not the maximum-OI strike, excludes premiums and cannot be averaged across expiries. Adjusted contracts require actual deliverables; this page uses standard-linear teaching contracts only."))
    c, p = st.columns(2)
    call_strike = _input("number_input", "options_mp_call_strike", 100., tr("TOY Call行权价", "TOY call strike"), host=c, min_value=1., max_value=2000., step=1.)
    call_oi = _input("number_input", "options_mp_call_oi", 10, tr("Call OI（张）", "Call OI (contracts)"), host=c, min_value=0, max_value=100000, step=1)
    put_strike = _input("number_input", "options_mp_put_strike", 110., tr("TOY Put行权价", "TOY put strike"), host=p, min_value=1., max_value=2000., step=1.)
    put_oi = _input("number_input", "options_mp_put_oi", 10, tr("Put OI（张）", "Put OI (contracts)"), host=p, min_value=0, max_value=100000, step=1)
    multiplier = _input("number_input", "options_mp_multiplier", 100, tr("明确的教学合约乘数", "Explicit teaching contract multiplier"), min_value=1, max_value=1000, step=1)
    spot = _input("number_input", "options_mp_spot", 105., tr("只用于距离的TOY现价", "TOY spot used only for distance"), min_value=.01, max_value=2000., step=1.)
    if st.button(tr("计算TOY最大痛苦集合", "Calculate the TOY Max Pain set"), key="options_mp_run"):
        try:
            report = run_demo_max_pain(call_strike=float(call_strike), put_strike=float(put_strike),
                call_oi=int(call_oi), put_oi=int(put_oi), multiplier=int(multiplier), spot=float(spot))
            _save_demo("options_mp", report)
            st.session_state["options_mp_error"] = False
        except Exception:
            st.session_state["options_mp_error"] = True
    if st.session_state.get("options_mp_error"):
        st.error(tr("本次最大痛苦教学计算未完成，请核对输入；没有读取其他行情。", "The Max Pain teaching calculation did not complete. Check the inputs; no other prices were read."))
    report = st.session_state.get("options_mp_report")
    if report:
        st.caption(tr("显示上次运行的教学结果；更改输入须重新点击计算。", "Showing the last teaching result; calculate again after editing inputs."))
        core = report["result"]
        st.json({"source_kind": "synthetic_demo", "underlying": "TOY", "status": core.get("status"),
                 "minimizer": core.get("minimizer"), "minimum_loss": core.get("minimum_loss"), "reason": core.get("reason")})
        if report.get("distance_to_minimizer") is not None:
            st.metric(tr("现价到最小解集合的距离（价格单位）", "Spot distance to minimizing set (price units)"), report["distance_to_minimizer"])
        curve = report["loss_curve"]
        figure = go.Figure(go.Scatter(x=[r["settlement_price"] for r in curve], y=[r["loss"] for r in curve], mode="lines", name=tr("合计到期内在价值", "Total expiry intrinsic value")))
        minimizer = core.get("minimizer") or {}
        lower, upper = minimizer.get("lower"), minimizer.get("upper")
        if lower is not None:
            if upper is None:
                figure.add_vrect(x0=float(lower), x1=curve[-1]["settlement_price"], fillcolor="#087f8c", opacity=.15, line_width=0)
                st.caption(tr("最小解向右无界；阴影只画到有限视窗边界，不代表上界。", "The minimizing ray is unbounded to the right; shading ends at the finite viewport, not at a solution boundary."))
            elif float(upper) > float(lower):
                figure.add_vrect(x0=float(lower), x1=float(upper), fillcolor="#087f8c", opacity=.15, line_width=0)
            else:
                figure.add_vline(x=float(lower), line_dash="dot", line_color="#087f8c")
        figure.add_vline(x=report["inputs"]["spot"], line_dash="dash", line_color="#718096",
                        annotation_text=tr("TOY现价", "TOY spot"))
        figure.update_layout(template="plotly_white", height=340, margin=dict(l=10, r=10, t=30, b=10),
                             xaxis_title=tr("假设结算价", "Hypothetical settlement price"), yaxis_title=tr("教学合计价值", "Teaching total value"))
        st.plotly_chart(figure, use_container_width=True)
        st.caption(tr("默认例子的平底区间保留全部最小解，不能擅取中点。固定OI、乘数及合约范围时，改变现价只改变距离，不改变此最小解集合；未来更新OI后的动态目标目前不可得。",
                      "The default flat interval retains every minimizer; do not silently choose its midpoint. With OI, multipliers and contract scope fixed, changing spot changes distance but not this minimizer set. Future targets after OI updates are unavailable."))
        with st.expander(tr("教学参数与分段斜率审计", "Teaching Inputs and Piecewise-Slope Audit")):
            st.json({"inputs": report["inputs"], "result": core})
        st.download_button(tr("下载TOY最大痛苦教学JSON", "Download TOY Max Pain teaching JSON"), st.session_state["options_mp_json"],
                           file_name="toy-max-pain-teaching.json", mime="application/json", key="options_mp_download")


def _design_tab(tr):
    st.subheader(tr("先积累可得快照，再检验增量", "Archive Available Snapshots Before Testing Incremental Value"))
    steps = [
        ("冻结时点", "Freeze observability", "保存原始时间、接收时间、OI有效日／公布时间及研究可得时间；未知值不补。完整期权链、Greeks、交付物和覆盖共同验收。", "Retain source, received, OI-effective/publication and research-availability times. Leave unknowns unknown. Verify complete chains, Greeks, deliverables and coverage together."),
        ("比较A→B/C→墙→痛点→期限", "Compare A → B/C → walls → Max Pain → expiry", "A含近期波动、IV、趋势、量／价差、时段及事件；逐项增加特征。墙、GEX、痛点共享OI，不作独立证据投票。", "A includes recent volatility, IV, trend, volume/spreads, time and events. Add features incrementally; walls, GEX and Max Pain share OI and are not independent votes."),
        ("预注册15／30／60分钟标签", "Pre-register 15 / 30 / 60-minute labels", "主要预测波动、振幅和延续／反转；方向单测。Walk-forward按时间分割，purge重叠标签，按交易日／标的／到期簇评估不确定性。", "Prioritize volatility, ranges and continuation/reversal; test direction separately. Walk forward in time, purge overlapping labels, and evaluate uncertainty by session, underlying and expiry clusters."),
        ("冻结MP_t0及匹配对照", "Freeze MP_t0 and matched controls", "比较ATM、整数价、最大OI价及匹配现价距离的水平；冻结起点目标与后来OI更新形成的目标迁移分别分析，不能平均各期痛点。", "Compare ATM, round-number, max-OI and distance-matched levels. Separate the frozen initial target from later OI-driven target migration; never average expiry-specific pain levels."),
        ("加入可实现成本及淘汰门槛", "Include feasible costs and a rejection rule", "逐腿Bid／Ask、费用、滑点及覆盖；若效果只靠某种库存先验、事后参数或少数极端日，降级为观察结构。完全留出期及前瞻模拟通过之前不接执行。", "Include per-leg bid/ask, fees, slippage and coverage. Downgrade to structural observation if gains depend on one inventory prior, hindsight parameters or a few extremes. Require a held-out period and forward simulation before execution."),
    ]
    for index, (zh, en, dzh, den) in enumerate(steps, 1):
        st.markdown(f"**{index}. {tr(zh, en)}**")
        st.write(tr(dzh, den))
    st.info(tr("当前没有样本外基线成绩、回测净值、胜率或统计置信区间；历史增量预测状态为NOT_ESTIMABLE。情景范围仅表达假设敏感性。", "There are no out-of-sample baseline scores, backtest equity, win rates or statistical confidence intervals yet. Historical incremental prediction is NOT_ESTIMABLE. Scenario ranges express assumption sensitivity only."))
    st.caption(tr("研究框架来自已有Gamma／墙位／最大痛苦草案，作为待检验假设使用；文内的策略示意不是执行指令或已验证结果。", "The existing gamma/walls/Max Pain research draft supplies hypotheses to test. Its strategy examples are neither execution instructions nor validated results."))
    st.markdown(tr("官方接口与定义：", "Official interfaces and definitions: ") +
        "[GEX](https://open.moomoo.com/api/quote/derivatives/option-gamma-exposure) · "
        "[Max Pain](https://open.moomoo.com/api/quote/derivatives/quote-option-max-pain) · "
        "[Option chain](https://open.moomoo.com/api/quote/derivatives/option-chain) · "
        "[OIC Gamma](https://www.optionseducation.org/advancedconcepts/gamma)")


def run_demo_inventory_update(*, delta_q, q0_lower, q0_upper):
    """A conditional TOY accounting example, independent of exchange samples."""
    from research.dealer_methods import initial_inventory_sensitivity
    result = initial_inventory_sensitivity(delta_q, q0_lower=q0_lower, q0_upper=q0_upper,
        inventory_scope="TOY_one_contract", flow_scope="TOY_one_contract",
        assume_no_other_changes=True)
    return {"kind": "inventory_teaching", "source_kind": "synthetic_demo", "underlying": "TOY",
        "inputs": {"delta_q": delta_q, "q0_lower": q0_lower, "q0_upper": q0_upper},
        "result": result, "claims": {"market_observation": False,
            "dealer_inventory_estimated_from_labels": False, "confidence_interval": False,
            "orders_submitted": False}}


def _inventory_methods_tab(tr):
    from research.dealer_methods import method_catalog
    st.subheader(tr("持仓方向：方法、证据和当前可运行范围", "Inventory Direction: Methods, Evidence and Availability"))
    st.write(tr("把此前讨论的方法放在一起，区分固定符号、流量识别、库存估计和尾部风险。每种方法的可运行状态取决于实际数据；研究框架不等于已经拟合的模型。",
        "Compare the discussed methods across sign assumptions, observed flow, inventory estimation and tail risk. Availability depends on actual data; a research framework is not a fitted model."))
    catalog = method_catalog(language="zh" if tr("zh", "en") == "zh" else "en")
    st.dataframe(pd.DataFrame([{
        tr("方法", "Method"): row["label"], tr("状态", "Availability"): row["status_label"],
        tr("用途", "Purpose"): row["description"],
        tr("边界", "Limit"): " ".join(row["limitations"]),
    } for row in catalog]), hide_index=True, use_container_width=True)
    with st.expander(tr("各方法所需字段与原文", "Required Fields and Original Sources")):
        for row in catalog:
            st.markdown("**" + row["label"] + "**")
            st.caption(", ".join(row["required_fields"]))
            for source in row["evidence"]:
                st.markdown("[" + tr("原始来源", "Original source") + "](" + source + ")")
    st.info(tr("免费Cboe样本的解析和真实MM侧会计在本机独立运行。本公开页不读取或上传该样本，不展示其逐合约行情／净流；外部数据及派生展示许可另行验收。",
        "The free Cboe sample parser and observed MM-side accounting run separately on the local computer. This public page does not load or upload those samples or display their contract data/flows. External-data and derived-display licensing need separate acceptance."))
    st.latex(r"\Delta q_{\mathrm{trade}}=Q_{\mathrm{MM,buy}}-Q_{\mathrm{MM,sell}}")
    st.latex(r"q_t=q_0+\sum\Delta q_{\mathrm{trade}}+\mathrm{adjustments}")
    st.write(tr("买平也增加净库存；卖平也减少净库存。买卖双方同属目标MM群体时相抵。Call和Put的普通多头Gamma均为正，贡献符号由净库存决定；MM净买Put不自动表示其存量已净多，也不自动看涨或看跌。",
        "Buying to close also increases net inventory; selling to close decreases it. Two MM sides cancel within the target group. Ordinary long calls and puts both have positive gamma: inventory determines the contribution sign. Net put buying does not establish a net-long stock of puts or a bullish/bearish forecast."))
    with st.expander(tr("TOY：同样的净买入，为什么可能仍然净空？", "TOY: Why Can Net Buying Leave Inventory Net Short?")):
        st.caption(tr("以下输入完全是假设。仅在初仓范围、同一合约和无遗漏／其他调整假设下计算情景区间；不是统计置信区间。",
            "These inputs are entirely hypothetical. Compute a scenario range conditional on the stated starting range, same contract and no missing flow/other adjustments; this is not a confidence interval."))
        delta = _input("number_input", "options_inventory_delta", 30., tr("TOY MM买减卖（张）", "TOY MM buys minus sells (contracts)"), min_value=-100000., max_value=100000., step=10.)
        low = _input("number_input", "options_inventory_q0_low", -200., tr("TOY初始净库存下界", "TOY starting-inventory lower bound"), min_value=-100000., max_value=100000., step=10.)
        high = _input("number_input", "options_inventory_q0_high", 200., tr("TOY初始净库存上界", "TOY starting-inventory upper bound"), min_value=-100000., max_value=100000., step=10.)
        if st.button(tr("运行TOY库存变化示例", "Run TOY inventory update"), key="options_inventory_run"):
            try:
                report = run_demo_inventory_update(delta_q=float(delta), q0_lower=float(low), q0_upper=float(high))
                _save_demo("options_inventory", report)
                st.session_state["options_inventory_error"] = False
            except Exception:
                st.session_state["options_inventory_error"] = True
        if st.session_state.get("options_inventory_error"):
            st.error(tr("库存区间输入无效，请检查上下界；没有推断真实库存。", "Invalid inventory-range inputs: check the bounds. No real inventory was inferred."))
        if st.session_state.get("options_inventory_report"):
            st.caption(tr("显示上次点击运行的假设；切换语言和修改参数不重算。", "Showing the last-run assumptions; language and input changes do not recalculate."))
            st.json(st.session_state["options_inventory_report"])
    st.markdown("[Cboe TBT](https://datashop.cboe.com/enhanced-us-options-trade-by-trade-execution-detail) · "
        "[Cboe Open-Close](https://datashop.cboe.com/cboe-options-open-close-volume-summary)")


def render_options_research_page(tr):
    st.markdown("<div class='alpha-eyebrow'>" + tr(*ui.STUDIES["options"]["group"]) + "</div>", unsafe_allow_html=True)
    st.title(tr("期权结构研究：GEX与最大痛苦", "Options Structure: GEX & Max Pain"))
    ui.study_meta(tr, "options")
    st.write(tr("区分实际观测、库存假设和可检验预测；先看数据边界，再运行明确标记的TOY教学计算。", "Separate observations, inventory assumptions and testable prediction. Check the data limits, then explicitly run labeled TOY calculations."))
    st.caption(tr("离线研究页；不联网取数、不读取私人文件、不连接券商或提交订单。", "Offline research page: no data fetching, private-file access, brokerage connection or orders."))
    tabs = st.tabs([tr("数据审计", "Data audit"), tr("持仓方向方法", "Inventory methods"), tr("GEX情景", "GEX scenarios"),
                    tr("最大痛苦计算器", "Max Pain calculator"), tr("实验设计", "Experiment design")])
    for tab, render in zip(tabs, (_audit_tab, _inventory_methods_tab, _gex_tab, _max_pain_tab, _design_tab)):
        with tab:
            render(tr)
