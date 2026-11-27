"""Inventory-accounting and source-safety checks using fictional side rows."""
import hashlib
import io
import json
import zipfile

import pytest

from research.cboe_mm_sample import (
    CboeSampleError, audit_open_close_rows, audit_tbt_rows, audit_tbt_sample,
    contract_key, difference_open_close_cumulative,
    gex_change_from_inventory_change, observed_mm_change,
)


def trade(**updates):
    row = {
        "transact_time": "2025-03-28 09:35:01.123456", "trading_dt": "2025-03-28",
        "underlying": "SPY", "osi_root": "SPY", "expire_date": "2025-03-28",
        "call_put_flag": "P", "strike_price": "560.0000", "size": "3", "price": "1.20",
        "side": "B", "capacity": "MarketMaker", "open_close": "C", "exec_id": "e1",
        "complex_exec_id": "", "session": "RTH",
    }
    row.update(updates)
    return row


def oc(**updates):
    row = {"quote_date": "2025-03-28", "underlying_symbol": "SPY", "option_symbol": "SPY",
           "expiration_date": "2025-03-28", "strike_price": "560.0000", "call_put_flag": "P",
           "mm_buy_qty": "2", "mm_buy_vol": "60", "mm_sell_qty": "5", "mm_sell_vol": "10"}
    row.update(updates)
    return row


def test_mm_buy_close_increases_net_inventory_independently_of_call_put():
    put = audit_tbt_rows([trade(open_close="C")])
    call = audit_tbt_rows([trade(call_put_flag="C", open_close="O")])
    assert observed_mm_change(3, 0) == 3
    assert put["observed_totals"]["sampled_observed_mm_signed_contracts"] == 3
    assert call["observed_totals"]["sampled_observed_mm_signed_contracts"] == 3
    for report in (put, call):
        assert report["inventory_q"] is None
        assert report["full_interval_delta_q"] is None
        assert report["net_inventory_gex"] is None
        assert report["calibrated_mm_probabilities"] is None


def test_two_mm_sides_cancel_and_closing_status_does_not_reverse_sign():
    result = audit_tbt_rows([trade(side="B", open_close="C"), trade(side="S", open_close="C")])
    assert result["observed_totals"]["mm_buy_contracts"] == 3
    assert result["observed_totals"]["mm_sell_contracts"] == 3
    assert result["observed_totals"]["sampled_observed_mm_signed_contracts"] == 0
    assert result["balanced_all_MM_groups_net_cancelled"] == 1
    assert result["observed_balanced_group_mm_presence_classes"]["both"] == 1


def test_missing_other_side_is_unknown_not_neither_or_non_mm():
    result = audit_tbt_rows([trade()])
    assert result["group_counts"]["missing_B_or_S_groups"] == 1
    assert result["observed_balanced_group_mm_presence_classes"] == {"counterparty_or_quantity_unknown": 1}
    assert result["counterparty_missing_means_non_MM"] is False


def test_real_sample_non_option_shape_is_quarantined_not_counted_as_contracts():
    result = audit_tbt_rows([
        trade(),
        trade(exec_id="stock", osi_root="", call_put_flag="", strike_price="0", expire_date="3006-01-01", size="100", side="T"),
    ])
    assert result["side_records"] == 2
    assert result["option_side_records"] == 1
    assert result["quarantined_instrument_side_records"] == 1
    assert result["quarantined_capacity_counts"] == {"MarketMaker": 1}
    assert result["side_counts"]["UNKNOWN"] == 1
    assert result["observed_totals"]["mm_buy_contracts"] == 3
    assert result["observed_totals"]["mm_unknown_side_contracts"] == 0


def test_unknown_option_side_and_capacity_are_not_silently_assigned():
    result = audit_tbt_rows([trade(side="T", size="7"), trade(exec_id="e2", capacity="dealer_guess", size="9")])
    assert result["observed_totals"]["mm_unknown_side_contracts"] == 7
    assert result["observed_totals"]["unknown_capacity_contracts"] == 9
    assert result["observed_totals"]["sampled_observed_mm_signed_contracts"] == 0


def test_decimal_contract_identity_preserves_adjusted_roots_and_tiny_strike_difference():
    assert contract_key("SPY", "20250328", "P", "560.0000") == contract_key("SPY", "2025-03-28", "P", "560")
    assert contract_key("SPY", "20250328", "P", "560.00000000000000001") != contract_key("SPY", "20250328", "P", "560")
    assert contract_key("1SPY", "20250328", "P", "560") != contract_key("SPY", "20250328", "P", "560")
    assert contract_key("SPY", "20250328", "P", "560.0000000000000000000000000000001") != contract_key("SPY", "20250328", "P", "560")


def test_exact_duplicate_side_records_fail_instead_of_doubling_observed_flow():
    with pytest.raises(CboeSampleError, match="exact_duplicate"):
        audit_tbt_rows([trade(), trade()])


def test_quote_position_observations_do_not_define_mm_or_aggressor_identity():
    rows = [
        trade(exec_id="e1", price="1.00", nbbo_bid="1.00", nbbo_ask="1.10"),
        trade(exec_id="e2", side="S", price="1.10", nbbo_bid="1.00", nbbo_ask="1.10"),
        trade(exec_id="e3", price="1.05", nbbo_bid="1.00", nbbo_ask="1.10"),
        trade(exec_id="e4", price="1.05", nbbo_bid="1.10", nbbo_ask="1.00"),
        trade(exec_id="e5", price="1.10", nbbo_bid="0", nbbo_ask="1.10"),
    ]
    result = audit_tbt_rows(rows)
    assert result["mm_quote_position_side_records"] == {
        "B_at_or_below_bid": 1, "S_at_or_above_ask": 1, "B_inside": 1, "B_invalid_nbbo": 2}
    assert result["quote_position_is_aggressor_truth"] is False
    assert sum(result["mm_quote_position_contracts"].values()) == 15


def test_date_and_contract_execution_keys_separate_same_execution_id():
    result = audit_tbt_rows([trade(), trade(strike_price="561", side="S")])
    assert result["execution_groups"] == 2
    assert result["group_counts"]["both_B_S_groups"] == 0


def test_unbalanced_sides_are_not_complete_four_class_labels():
    result = audit_tbt_rows([trade(), trade(side="S", size="2", capacity="Customer")])
    assert result["group_counts"]["unbalanced_B_S_groups"] == 1
    assert "buyer_only" not in result["observed_balanced_group_mm_presence_classes"]


def test_multi_record_mixed_capacity_group_is_not_a_two_counterparty_label():
    result = audit_tbt_rows([
        trade(size="1", capacity="MarketMaker"),
        trade(size="1", capacity="Customer"),
        trade(size="2", side="S", capacity="MarketMaker"),
    ])
    assert result["group_counts"]["balanced_B_S_groups"] == 1
    assert result["observed_balanced_group_mm_presence_classes"] == {"counterparty_or_quantity_unknown": 1}
    assert result["observed_totals"]["sampled_observed_mm_signed_contracts"] == -1


def test_date_without_event_clock_is_not_silently_interpreted_as_midnight():
    with pytest.raises(CboeSampleError, match="source_timestamp"):
        audit_tbt_rows([trade(transact_time="2025-03-28")])


def test_complex_groups_preserved_across_contracts_and_source_time_not_fabricated():
    result = audit_tbt_rows([trade(complex_exec_id="c1"), trade(exec_id="e2", strike_price="561", complex_exec_id="c1")],
                            received_at="2026-11-27T12:00:00-05:00")
    assert result["observed_complex_id_groups"] == 1
    assert result["complex_side_records"] == 2
    assert result["received_at"] == "2026-11-27T17:00:00Z"
    assert result["historical_first_available_at"] is None
    assert result["source_time_converted_to_utc"] is False
    assert result["contract_summaries"][0]["multiplier"] is None


@pytest.mark.parametrize("size", ["-1", "NaN", "Infinity", "1.5", "0"])
def test_bad_tbt_quantities_fail_closed(size):
    with pytest.raises(CboeSampleError):
        audit_tbt_rows([trade(size=size)])


def test_invalid_limits_missing_schema_and_duplicate_extra_csv_columns_fail():
    for params in ({"max_rows": True}, {"max_contract_rows": 5000}, {"underlyings": "SPY"}, {"underlyings": []}):
        with pytest.raises(CboeSampleError):
            audit_tbt_rows([trade()], **params)
    with pytest.raises(CboeSampleError, match="row_bound"):
        audit_tbt_rows([trade(), trade(exec_id="e2")], max_rows=1)
    with pytest.raises(CboeSampleError, match="schema"):
        audit_tbt_rows([{"size": "1"}])
    with pytest.raises(CboeSampleError, match="schema"):
        audit_tbt_rows([{**trade(), None: ["unexpected"]}])


def test_aggregated_output_has_no_raw_trade_price_or_execution_id_table():
    result = audit_tbt_rows([trade()], max_contract_rows=0)
    encoded = json.dumps(result)
    assert '"price"' not in encoded and '"exec_id"' not in encoded
    assert result["contract_summaries"] == []
    assert result["contract_summaries_truncated"] is True
    assert result["public_distribution_rights_verified"] is False


def test_open_close_uses_contract_volume_not_trade_count_and_keeps_unknown_q():
    result = audit_open_close_rows([oc()])
    assert result["sampled_observed_mm_signed_contracts"] == 50
    assert result["mm_buy_trade_count"] == 2
    assert result["mm_sell_trade_count"] == 5
    assert result["inventory_q"] is None
    assert result["full_interval_delta_q"] is None


def test_open_close_accepts_index_caret_and_refuses_duplicate_or_multi_snapshot_sum():
    assert audit_open_close_rows([oc(underlying_symbol="^SPX", option_symbol="SPX")])["series_snapshot_rows"] == 1
    with pytest.raises(CboeSampleError, match="duplicate"):
        audit_open_close_rows([oc(), oc()])
    with pytest.raises(CboeSampleError, match="one_snapshot"):
        audit_open_close_rows([oc(), oc(quote_date="2025-03-31")])


def test_open_close_negative_volume_and_missing_oi_not_silently_filled():
    with pytest.raises(CboeSampleError):
        audit_open_close_rows([oc(mm_buy_vol="-2")])
    result = audit_open_close_rows([oc()])
    assert result["net_inventory_gex"] is None
    assert "open_interest" not in result["contract_summaries"][0]


def test_cumulative_difference_preserves_negative_revision_instead_of_clipping():
    p = {"contract_key": "C1|SPY|2025-03-28|P|560", "trading_date": "2025-03-28", "session": "RTH",
         "snapshot_source_local": "2025-03-28 10:00:00", "mm_buy_contracts": 100, "mm_sell_contracts": 80}
    c = {**p, "snapshot_source_local": "2025-03-28 10:10:00", "mm_buy_contracts": 95, "mm_sell_contracts": 90}
    with pytest.raises(CboeSampleError, match="scope_required"):
        difference_open_close_cumulative(p, c)
    revised = difference_open_close_cumulative(p, c, same_contract_scope_verified=True)
    assert revised["buy_cumulative_difference"] == -5
    assert revised["net_cumulative_difference"] == -15
    assert revised["observed_interval_delta_q"] is None
    assert revised["revision_or_scope_diagnostic"] is True
    c["mm_buy_contracts"] = 110
    good = difference_open_close_cumulative(p, c, same_contract_scope_verified=True)
    assert good["observed_interval_delta_q"] == 0
    assert good["inventory_q"] is None
    with pytest.raises(CboeSampleError, match="session_reset"):
        difference_open_close_cumulative(p, {**c, "session": "GTH"}, same_contract_scope_verified=True)


def test_gex_helper_is_inventory_change_arithmetic_and_rejects_negative_gamma():
    result = gex_change_from_inventory_change(-3, spot=100, multiplier=100, gamma=".02")
    assert result["gex_change_1pct"] == -600
    assert result["net_inventory_gex"] is None
    assert result["contemporaneous_inputs_verified"] is False
    with pytest.raises(CboeSampleError):
        gex_change_from_inventory_change(3, spot=100, multiplier=100, gamma="-.02")


def test_zip_hash_and_traversal_safety(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("../TBT.csv", "x\n1\n")
    payload = data.getvalue()
    p = tmp_path / "sample.zip"
    p.write_bytes(payload)
    with pytest.raises(CboeSampleError, match="source_sha256"):
        audit_tbt_sample(p)
    with pytest.raises(CboeSampleError, match="unsafe_archive"):
        audit_tbt_sample(p, expected_sha256=hashlib.sha256(payload).hexdigest())
