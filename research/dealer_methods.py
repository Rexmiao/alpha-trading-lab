"""Research-method capabilities, not a trained dealer-inventory estimator.

The catalog is safe to ship without any market data. Availability describes the
implemented audit/scenario, never proof of inventory or predictive performance.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import math
from numbers import Real


METHOD_IDS = (
    "squeezemetrics", "layered_inventory_prior", "unsigned_concentration",
    "net_buying_pressure", "mm_capacity_flow", "demand_based_pricing",
    "latent_inventory", "complex_leg_reconstruction", "shadow_gamma",
)
CAPABILITY_IDS = frozenset({
    "scenario_engine", "toy_complete_chain", "vendor_aggressor_proxy",
    "mm_capacity_sample", "contract_identity", "execution_ids", "trade_quantity",
    "synchronized_quotes", "continuous_classified_flow", "known_initial_inventory",
    "nontrade_adjustments", "matched_moomoo_dates", "time_holdout_labels",
    "complex_execution_ids", "complete_complex_legs", "classified_position_book",
    "demand_model_identification", "calibrated_state_model", "validated_quote_rule",
    "point_in_time_iv_surface", "full_repricing_model",
})
DEFAULT_CAPABILITIES = frozenset({
    "scenario_engine", "toy_complete_chain", "vendor_aggressor_proxy",
})
_SCENARIO = ("scenario_engine", "toy_complete_chain")
_SAMPLE = ("mm_capacity_sample", "contract_identity", "execution_ids", "trade_quantity")


class DealerMethodError(ValueError):
    """Invalid method-catalog declaration or sensitivity input."""


def _language(language: str) -> str:
    if language not in {"en", "zh"}:
        raise DealerMethodError("language must be en or zh")
    return language


def _capabilities(values: Iterable[str] | Mapping[str, bool] | None) -> set[str]:
    if values is None:
        return set(DEFAULT_CAPABILITIES)
    if isinstance(values, Mapping):
        if any(type(value) is not bool for value in values.values()):
            raise DealerMethodError("Capability mapping values must be booleans")
        declared = set(values)
        enabled = {key for key, value in values.items() if value}
    else:
        if isinstance(values, (str, bytes)):
            raise DealerMethodError("capabilities must be a collection, not a string")
        try:
            declared = enabled = set(values)
        except TypeError as exc:
            raise DealerMethodError("capabilities must contain capability IDs") from exc
    if any(not isinstance(value, str) for value in declared) or not declared <= CAPABILITY_IDS:
        raise DealerMethodError("Unknown capability ID")
    return enabled


def _text(language: str, en: str, zh: str) -> str:
    return zh if language == "zh" else en


def method_catalog(language: str = "en", capabilities=None) -> list[dict]:
    """Return nine bilingual method rows with independent implementation gates.

    Passing data capabilities cannot turn an unimplemented estimator into a
    calibrated model. A sample enables observed-side audits, not full-interval
    inventory changes. Caller-declared capabilities are not independently audited
    by this metadata-only function.
    """
    language = _language(language)
    caps = _capabilities(capabilities)
    definitions = [
        ("squeezemetrics", "Fixed Call+/Put− baseline", "固定Call正／Put负基线",
         "inventory_assumption", _SCENARIO, "EXISTING_SCENARIO",
         ("open_interest", "call_put", "gamma", "multiplier"),
         "Assign all Call OI positive and Put OI negative under the declared convention.",
         "在声明口径下给Call OI正号、Put OI负号。",
         "The sign and allocation of all OI to MM are assumptions, not observed holdings.",
         "符号及全部OI归属MM都是假设，不是观测持仓。",
         ("assumed_signed_gex",),
         "https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf"),
        ("layered_inventory_prior", "Inventory-prior scenarios", "库存先验情景",
         "inventory_assumption", _SCENARIO, "EXISTING_SCENARIO",
         ("open_interest", "call_put", "gamma", "multiplier", "declared_prior"),
         "Existing scenarios vary Call/Put long fractions and the assumed dealer share.",
         "当前情景可调整Call／Put净多倾向和假设MM占比。",
         "These are uncalibrated inputs. Asset/DTE/moneyness layers and fitted MM probabilities are not implemented.",
         "参数未校准；asset／DTE／价内外分层及拟合MM概率尚未实现。",
         ("assumed_signed_gex",),
         "https://users.nber.org/~confer/2005/URCs05/pedersen.pdf"),
        ("unsigned_concentration", "Unsigned OI–Gamma concentration", "无符号OI–Gamma集中度",
         "structure_reference", _SCENARIO, "EXISTING_SCENARIO",
         ("open_interest", "gamma", "multiplier", "complete_chain"),
         "Locate exposure concentration without assigning MM ownership or side.",
         "不分配MM归属及方向，只定位敞口集中区域。",
         "Concentration is not signed dealer GEX, a calibrated wall, or proof of support/resistance.",
         "集中度不是带符号MM GEX、校准墙位或支撑阻力证据。",
         ("unsigned_concentration",),
         "https://www.optionseducation.org/advancedconcepts/gamma"),
        ("net_buying_pressure", "Net buying pressure / aggressor proxy", "净买压／主动流代理",
         "flow_proxy", ("vendor_aggressor_proxy",), "PROXY_ONLY",
         ("trade_price", "trade_quantity", "trade_time", "synchronized_bid_ask"),
         "Current moomoo audit preserves vendor BUY/SELL/NEUTRAL; a quote-rule study is a separate next step.",
         "当前moomoo审计保存供方BUY／SELL／NEUTRAL；报价规则研究为独立下一步。",
         "Aggressor direction does not identify MM side. Vendor labels are not independent truth; quote-rule NBP is not yet validated.",
         "主动方向不识别MM侧；供方标签不是独立真值，报价规则NBP尚未验证。",
         ("vendor_aggressor_flow",),
         "https://www.whaley.info/_files/ugd/1362e1_81f94ba850fb4ec4aea173770b355408.pdf"),
        ("mm_capacity_flow", "Exchange-classified MM buy/sell flow", "交易所分类MM买卖流",
         "observed_side_audit", _SAMPLE, "SAMPLE_AUDIT_READY",
         ("contract_identity", "side", "capacity", "size", "exec_id", "complex_exec_id"),
         "Sum signed quantities on observed MM sides; paired MM buy/sell sides cancel within the same group.",
         "对观测到的MM买卖侧数量求和；同群体MM双侧成交相抵。",
         "Partial side samples do not give complete interval flow or stock. Missing counterparties remain unknown; q0 and missing venues are unresolved.",
         "部分侧样本不是完整区间流或存量；缺对侧保留未知，初仓和缺失交易所未解决。",
         ("sampled_observed_mm_side_flow",),
         "https://datashop.cboe.com/enhanced-us-options-trade-by-trade-execution-detail"),
        ("demand_based_pricing", "Demand-based option-pricing framework", "需求驱动期权定价框架",
         "research_framework", ("classified_position_book", "demand_model_identification"), "BLOCKED",
         ("classified_positions", "option_demand", "hedging_risks", "pricing_inputs"),
         "Relate participant demand and unhedgeable risk to option prices; motivate product-specific priors.",
         "联系参与者需求、不可对冲风险和期权价格，为分产品先验提供依据。",
         "A pricing framework is not a unique inversion from public OI or IV to q. No inventory estimator is implemented here.",
         "定价框架不是公开OI或IV到q的唯一逆映射；此处没有已实现的库存估计器。",
         (),
         "https://users.nber.org/~confer/2005/URCs05/pedersen.pdf"),
        ("latent_inventory", "Bayesian / state-space inventory candidate", "Bayesian／状态空间潜在库存候选",
         "unimplemented_estimator", ("continuous_classified_flow", "known_initial_inventory",
                                    "nontrade_adjustments", "time_holdout_labels", "calibrated_state_model"), "BLOCKED",
         ("classified_flow", "initial_inventory_evidence", "coverage_gaps", "nontrade_adjustments", "available_at"),
         "A proposed latent-state design would propagate flow errors, missing activity and q0 uncertainty.",
         "候选隐状态设计传播流量误差、缺失活动和q0不确定性。",
         "No model has been fitted or calibrated. Unknown initial inventory cannot be identified merely by adding a filter.",
         "尚无拟合或校准；添加滤波器不能凭空识别未知初仓。",
         (), None),
        ("complex_leg_reconstruction", "Complex-execution / leg reconstruction", "组合执行／多腿重建",
         "unimplemented_reconstruction", ("complex_execution_ids", "complete_complex_legs", "contract_identity"), "BLOCKED",
         ("complex_exec_id", "leg_id", "contract_identity", "capacity", "side", "leg_quantity"),
         "Net the observed legs of a common execution before interpreting risk direction.",
         "先净额化同一组合执行的各腿，再解释风险方向。",
         "A complex ID alone does not prove all legs are present. Complete multi-leg reconstruction and validation are not implemented.",
         "只有组合ID不证明全部腿已齐；完整多腿重建和验证尚未实现。",
         (),
         "https://algoseek.com/wp-content/uploads/2026/10/ssrn-7330098.pdf"),
        ("shadow_gamma", "Full repricing / shadow-Gamma risk scenarios", "全情景重定价／Shadow Gamma风险情景",
         "risk_scenario", _SCENARIO, "EXISTING_SCENARIO",
         ("declared_inventory", "option_terms", "iv", "spot_grid", "time_shift"),
         "Existing BSM scenarios reprice Gamma across spot, parallel IV shifts and time under declared inventory.",
         "现有BSM情景在声明库存下，随股价、平行IV变化和时间重算Gamma。",
         "This is limited risk-scenario arithmetic, not the paper's full shadow-Gamma model, a fitted IV surface, or an inventory-direction estimator.",
         "这是有限风险情景计算，不是论文完整Shadow Gamma、拟合IV曲面或库存方向估计器。",
         ("conditional_repriced_gex",),
         "https://www.fma.org/assets/docs/Derivatives2025/Terstegge.pdf"),
    ]
    status_labels = {
        "EXISTING_SCENARIO": ("Existing teaching scenario", "现有教学情景"),
        "PROXY_ONLY": ("Existing vendor proxy only", "仅有供方代理"),
        "SAMPLE_AUDIT_READY": ("Observed-side sample audit ready", "观测侧样本可核验"),
        "BLOCKED": ("Not implemented / data gates unmet", "尚未实现／数据门槛未满足"),
    }
    rows = []
    for (method_id, en, zh, kind, requirements, ready_status, fields,
         action_en, action_zh, limit_en, limit_zh, outputs, source) in definitions:
        missing = [cap for cap in requirements if cap not in caps]
        # Data declarations cannot enable unimplemented estimators/frameworks.
        status = "BLOCKED" if missing else ready_status
        enabled_outputs = list(outputs) if status != "BLOCKED" else []
        rows.append({
            "id": method_id, "label": _text(language, en, zh), "kind": kind,
            "status": status, "status_label": _text(language, *status_labels[status]),
            "requirements": list(requirements), "missing": missing,
            "required_fields": list(fields),
            "description": _text(language, action_en, action_zh),
            "limitations": [_text(language, limit_en, limit_zh)],
            "outputs": enabled_outputs,
            "identifies": {"q": False, "complete_delta_q": False,
                           "observed_mm_side_flow": status == "SAMPLE_AUDIT_READY",
                           "calibrated_mm_probability": False},
            "inventory_is_observed": False, "calibration_status": "NOT_CALIBRATED",
            "execution_eligible": False, "evidence": [source] if source else [],
        })
    return rows


def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise DealerMethodError(f"{field} must be a finite real number")
    value = float(value)
    if not math.isfinite(value) or abs(value) > 1e15:
        raise DealerMethodError(f"{field} is outside the declared numeric range")
    return value


def _scope(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise DealerMethodError(f"{field} must explicitly identify contract/date/population/venue scope")
    return value


def initial_inventory_sensitivity(
    delta_q, *, q0_lower=None, q0_upper=None, inventory_scope: str,
    flow_scope: str, assume_no_other_changes: bool = False,
) -> dict:
    """Conditional q0 arithmetic; always leaves actual stock ``q`` unknown.

    The caller must explicitly declare a zero-other-change scenario before the
    supplied q0 endpoints can be shifted. Nothing here estimates missing flow,
    nontrade changes, confidence levels, or the probability of a scenario.
    """
    change = _number(delta_q, "delta_q")
    if _scope(inventory_scope, "inventory_scope") != _scope(flow_scope, "flow_scope"):
        raise DealerMethodError("Inventory and flow scopes differ; do not splice dates/contracts/venues")
    if type(assume_no_other_changes) is not bool:
        raise DealerMethodError("assume_no_other_changes must be a boolean")
    if (q0_lower is None) != (q0_upper is None):
        raise DealerMethodError("Both initial-inventory endpoints are required or both must be unknown")
    lower = upper = None
    if q0_lower is not None:
        lower = _number(q0_lower, "q0_lower")
        upper = _number(q0_upper, "q0_upper")
        if lower > upper:
            raise DealerMethodError("q0_lower must not exceed q0_upper")
    result = {
        "scope": inventory_scope, "declared_signed_change": change,
        "q0_lower": lower, "q0_upper": upper,
        "assume_no_other_changes": assume_no_other_changes,
        "q": None, "scenario_lower": None, "scenario_upper": None,
        "scenario_direction": "DIRECTION_UNKNOWN", "status": "NOT_IDENTIFIABLE",
        "range_kind": "conditional_scenario_not_confidence_interval",
        "calibrated_probability": None, "execution_eligible": False,
        "reason": "UNKNOWN_INITIAL_INVENTORY" if lower is None else "OTHER_CHANGES_NOT_BOUNDED",
    }
    if lower is None or not assume_no_other_changes:
        return result
    new_lower, new_upper = lower + change, upper + change
    if not math.isfinite(new_lower) or not math.isfinite(new_upper):
        raise DealerMethodError("Scenario inventory endpoints are not finite")
    direction = ("POSITIVE_SCENARIO_RANGE" if new_lower > 0 else
                 "NEGATIVE_SCENARIO_RANGE" if new_upper < 0 else
                 "ZERO_SCENARIO_RANGE" if new_lower == new_upper == 0 else "DIRECTION_UNKNOWN")
    result.update({"scenario_lower": new_lower, "scenario_upper": new_upper,
                   "scenario_direction": direction, "status": "SCENARIO_RANGE_ONLY",
                   "reason": "DECLARED_Q0_AND_ZERO_OTHER_CHANGE_SCENARIO"})
    return result
