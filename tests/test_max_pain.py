"""Standard-library-only mathematical and scope-failure checks."""
import copy
from fractions import Fraction
import itertools
import json
import random
import unittest

from research.max_pain import (MaxPainError, compute_max_pain, distance_to_frozen_interval,
                              loss_at_price, make_hand_snapshot, make_teaching_snapshot,
                              freeze_target, evaluate_frozen_target, target_migration, loss_at_prices)


class MathematicalCases(unittest.TestCase):
    def test_unique_global_minimum(self):
        chain = make_hand_snapshot([("CALL", 90, 1), ("CALL", 100, 1), ("PUT", 100, 1), ("PUT", 110, 1)])
        result = compute_max_pain(chain)
        self.assertEqual(result["minimizer"], {"lower": "100", "upper": "100", "lower_inclusive": True,
                                             "upper_inclusive": True, "upper_unbounded": False, "kind": "point"})
        self.assertEqual(result["minimum_loss"], "2000")
        self.assertEqual(loss_at_price(chain, 95), "2500")

    def test_flat_minimum_retains_every_price_between_strikes(self):
        chain = make_hand_snapshot([("CALL", 90, 1), ("PUT", 110, 1)])
        result = compute_max_pain(chain)
        self.assertEqual((result["minimizer"]["lower"], result["minimizer"]["upper"]), ("90", "110"))
        for x in (90, 91, 99.5, 100, 109, 110):
            self.assertEqual(loss_at_price(chain, x), result["minimum_loss"])
        self.assertGreater(Fraction(loss_at_price(chain, 89)), Fraction(result["minimum_loss"]))
        self.assertGreater(Fraction(loss_at_price(chain, 111)), Fraction(result["minimum_loss"]))

    def test_zero_oi_strikes_do_not_truncate_flat_minimum(self):
        chain = make_hand_snapshot([("CALL", 90, 1), ("PUT", 100, 0), ("PUT", 110, 1)])
        result = compute_max_pain(chain)
        self.assertEqual(result["minimizer"]["upper"], "110")

    def test_calls_only_positive_oi_has_domain_boundary_flat_interval(self):
        chain = make_hand_snapshot([("CALL", 90, 1), ("CALL", 110, 2), ("PUT", 100, 0)])
        result = compute_max_pain(chain)
        self.assertEqual((result["minimizer"]["lower"], result["minimizer"]["upper"]), ("0", "90"))
        self.assertEqual(result["minimum_loss"], "0")

    def test_puts_only_positive_oi_has_unbounded_halfline(self):
        chain = make_hand_snapshot([("PUT", 90, 1), ("PUT", 110, 2), ("CALL", 100, 0)])
        result = compute_max_pain(chain)
        self.assertEqual(result["minimizer"]["lower"], "110")
        self.assertIsNone(result["minimizer"]["upper"])
        self.assertTrue(result["minimizer"]["upper_unbounded"])
        self.assertEqual(loss_at_price(chain, 1000000), "0")

    def test_zero_strike_domain_boundary(self):
        chain = make_hand_snapshot([("CALL", 0, 2), ("PUT", 10, 1)])
        self.assertEqual(compute_max_pain(chain)["minimizer"]["lower"], "0")
        self.assertEqual(compute_max_pain(chain)["minimizer"]["upper"], "0")

    def test_zero_strike_put_is_flat_over_entire_nonnegative_domain(self):
        result = compute_max_pain(make_hand_snapshot([("PUT", 0, 1)]))
        self.assertEqual(result["minimizer"]["lower"], "0")
        self.assertIsNone(result["minimizer"]["upper"])

    def test_no_contracts_is_unavailable(self):
        result = compute_max_pain(make_hand_snapshot([]))
        self.assertEqual(result["reason"], "no_contracts")
        self.assertIsNone(result["minimizer"])

    def test_all_zero_oi_does_not_fabricate_a_target(self):
        result = compute_max_pain(make_hand_snapshot([("CALL", 90, 0), ("PUT", 110, 0)]))
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["minimizer"])
        self.assertIsNone(result["minimum_loss"])

    def test_maximum_oi_is_not_max_pain(self):
        chain = make_hand_snapshot([("CALL", 90, 100), ("PUT", 100, 1), ("CALL", 110, 101)])
        self.assertEqual(compute_max_pain(chain)["minimizer"]["lower"], "90")
        self.assertEqual(max(chain["contracts"], key=lambda r: r["open_interest"])["strike"], 110)

    def test_common_multiplier_scales_loss_not_minimizer(self):
        rows = [("CALL", "90.25", 1), ("PUT", "110.75", 1)]
        small = compute_max_pain(make_hand_snapshot(rows, multiplier=10))
        large = compute_max_pain(make_hand_snapshot(rows, multiplier=100))
        self.assertEqual(small["minimizer"], large["minimizer"])
        self.assertEqual(Fraction(large["minimum_loss"]), 10 * Fraction(small["minimum_loss"]))

    def test_each_contract_multiplier_changes_weight_and_can_change_minimum(self):
        chain = make_hand_snapshot([("CALL", 90, 10), ("PUT", 110, 10)])
        chain["contracts"][0]["multiplier"] = 10
        result = compute_max_pain(chain)
        self.assertEqual((result["minimizer"]["lower"], result["minimizer"]["upper"]), ("110", "110"))
        self.assertEqual(result["minimum_loss"], "2000")

    def test_decimal_weights_preserve_exact_ties(self):
        chain = make_hand_snapshot([("CALL", "0.1", 3), ("PUT", "0.3", 1)], multiplier="0.1")
        chain["contracts"][1]["multiplier"] = "0.3"
        result = compute_max_pain(chain)
        self.assertEqual((result["minimizer"]["lower"], result["minimizer"]["upper"]), ("0.1", "0.3"))
        self.assertEqual(result["minimum_loss"], "0.06")

    def test_input_order_does_not_change_result(self):
        chain = make_hand_snapshot([("PUT", 110, 1), ("CALL", 90, 1), ("PUT", 100, 1)])
        first = compute_max_pain(chain)
        chain["contracts"].reverse()
        self.assertEqual(compute_max_pain(chain), first)

    def test_slope_prefix_losses_match_direct_payoffs(self):
        chain = make_hand_snapshot([("CALL", 90, 3), ("PUT", 95, 2), ("PUT", 110, 2), ("CALL", 110, 1)])
        for row in compute_max_pain(chain)["slope_table"]:
            self.assertEqual(row["loss"], loss_at_price(chain, row["strike"]))
            self.assertGreaterEqual(Fraction(row["slope_right"]), Fraction(row["slope_left"]))

    def test_exhaustive_small_chains_match_direct_global_candidates(self):
        # 3**6 =729 exact chains, including boundary minima and flat intervals.
        templates = [(right, strike) for strike in (0, 10, 20) for right in ("CALL", "PUT")]
        for interests in itertools.product(range(3), repeat=6):
            chain = make_hand_snapshot([(right, strike, oi) for (right, strike), oi in zip(templates, interests)])
            result = compute_max_pain(chain)
            if not any(interests):
                self.assertEqual(result["status"], "unavailable")
                continue
            lo = Fraction(result["minimizer"]["lower"])
            hi = Fraction(result["minimizer"]["upper"]) if result["minimizer"]["upper"] is not None else None
            target_loss = Fraction(result["minimum_loss"])
            for x in (0, 5, 10, 15, 20, 25):
                loss = Fraction(loss_at_price(chain, x))
                self.assertGreaterEqual(loss, target_loss)
                self.assertEqual(loss == target_loss, x >= lo and (hi is None or x <= hi))

    def test_json_safe_and_unknown_timestamps_remain_unknown(self):
        result = compute_max_pain(make_hand_snapshot([("CALL", 90, 1), ("PUT", 110, 1)]))
        json.dumps(result, allow_nan=False)
        self.assertFalse(result["point_in_time_timing_verified"])
        for field in ("query_time", "retrieved_at", "vendor_updated_at", "oi_effective_date", "available_at"):
            self.assertIsNone(result["metadata"][field])


class InvalidScopeCases(unittest.TestCase):
    def setUp(self):
        self.chain = make_hand_snapshot([("CALL", 90, 1), ("PUT", 110, 1)])

    def test_missing_oi_never_becomes_zero(self):
        self.chain["contracts"][0]["open_interest"] = None
        with self.assertRaisesRegex(MaxPainError, "not zero"):
            compute_max_pain(self.chain)

    def test_missing_multiplier_has_no_100_default(self):
        del self.chain["contracts"][0]["multiplier"]
        with self.assertRaises(MaxPainError):
            compute_max_pain(self.chain)

    def test_missing_authoritative_multiplier_source_rejected(self):
        self.chain["contracts"][0]["multiplier_source"] = ""
        with self.assertRaisesRegex(MaxPainError, "Authoritative multiplier_source"):
            compute_max_pain(self.chain)

    def test_adjusted_or_unverified_contracts_rejected(self):
        for field, value in (("adjusted", True), ("adjusted", None), ("standard_linear_verified", False),
                             ("deliverable_kind", "cash_and_stock_basket"), ("terms_source", None)):
            chain = copy.deepcopy(self.chain)
            chain["contracts"][0][field] = value
            with self.assertRaises(MaxPainError):
                compute_max_pain(chain)

    def test_completeness_flags_are_required_not_inferred(self):
        for flag in ("complete_chain", "pagination_complete", "no_visible_truncation", "terms_scope_verified"):
            chain = copy.deepcopy(self.chain)
            chain[flag] = None
            with self.assertRaisesRegex(MaxPainError, flag):
                compute_max_pain(chain)

    def test_common_expiry_is_not_enough_without_common_settlement_reference(self):
        self.chain["common_settlement_reference_verified"] = False
        with self.assertRaisesRegex(MaxPainError, "common payoff currency"):
            compute_max_pain(self.chain)

    def test_unknown_times_cannot_be_labelled_verified_point_in_time(self):
        self.chain["point_in_time_timing_verified"] = True
        with self.assertRaisesRegex(MaxPainError, "requires known"):
            compute_max_pain(self.chain)

    def test_known_time_must_be_utc_not_naive_or_unknown_timezone(self):
        self.chain["vendor_updated_at"] = "2026-11-23T07:00:00"
        with self.assertRaisesRegex(MaxPainError, "explicit UTC"):
            compute_max_pain(self.chain)

    def test_expected_contract_count_must_reconcile(self):
        self.chain["listed_standard_contract_count"] = 3
        with self.assertRaisesRegex(MaxPainError, "Contract count"):
            compute_max_pain(self.chain)

    def test_rights_coverage_must_include_both_sides(self):
        self.chain["rights_coverage"] = ["CALL"]
        with self.assertRaisesRegex(MaxPainError, "Both CALL and PUT"):
            compute_max_pain(self.chain)

    def test_mixed_expiries_and_underlyings_rejected(self):
        for field, value in (("expiry", "2027-01-15"), ("underlying", "OTHER")):
            chain = copy.deepcopy(self.chain)
            chain["contracts"][0][field] = value
            with self.assertRaisesRegex(MaxPainError, "Do not mix"):
                compute_max_pain(chain)

    def test_duplicate_contracts_are_not_double_counted(self):
        self.chain["contracts"][1]["contract_id"] = self.chain["contracts"][0]["contract_id"]
        with self.assertRaisesRegex(MaxPainError, "Unique"):
            compute_max_pain(self.chain)

    def test_negative_fractional_or_boolean_oi_rejected(self):
        for value in (-1, 1.5, True, "nan", "1.5"):
            chain = copy.deepcopy(self.chain)
            chain["contracts"][0]["open_interest"] = value
            with self.assertRaises(MaxPainError):
                compute_max_pain(chain)

    def test_nonfinite_or_nonpositive_multiplier_rejected(self):
        for value in (0, -1, float("inf"), "NaN", True):
            chain = copy.deepcopy(self.chain)
            chain["contracts"][0]["multiplier"] = value
            with self.assertRaises(MaxPainError):
                compute_max_pain(chain)

    def test_negative_or_missing_strike_rejected(self):
        for value in (-1, None):
            chain = copy.deepcopy(self.chain)
            chain["contracts"][0]["strike"] = value
            with self.assertRaises(MaxPainError):
                compute_max_pain(chain)

    def test_expiry_must_be_real_iso_date(self):
        self.chain["expiry"] = "2026-02-30"
        with self.assertRaisesRegex(MaxPainError, "expiry"):
            compute_max_pain(self.chain)

    def test_negative_settlement_domain_is_rejected(self):
        with self.assertRaisesRegex(MaxPainError, "nonnegative"):
            loss_at_price(self.chain, -1)


class FrozenTargetCases(unittest.TestCase):
    def time_audited_report(self):
        snapshot = make_teaching_snapshot("flat_interval")
        snapshot.update(point_in_time_timing_verified=True, query_time="2026-11-25T14:29:00Z",
                        retrieved_at="2026-11-25T14:29:05Z", available_at="2026-11-25T14:29:05Z",
                        oi_effective_date="2026-11-24")
        return compute_max_pain(snapshot)

    def target(self, price=120):
        return freeze_target(self.time_audited_report(), origin_price=price, decision_at="2026-11-25T14:30:00Z")

    def test_teaching_examples_are_explicitly_fictional_and_json_safe(self):
        for name in ("unique_point", "flat_interval", "max_oi_difference", "calls_halfline", "puts_halfline", "all_zero"):
            report = compute_max_pain(make_teaching_snapshot(name))
            self.assertEqual(report["underlying"], "TOY")
            self.assertEqual(report["source_kind"], "synthetic_teaching")
            json.dumps(report, allow_nan=False)

    def test_cannot_freeze_unknown_availability_or_not_yet_available_target(self):
        with self.assertRaisesRegex(MaxPainError, "Unknown point-in-time"):
            freeze_target(compute_max_pain(make_teaching_snapshot()), origin_price=120, decision_at="2026-11-25T14:30:00Z")
        with self.assertRaisesRegex(MaxPainError, "not available"):
            freeze_target(self.time_audited_report(), origin_price=120, decision_at="2026-11-25T14:29:00Z")

    def test_future_observations_are_gated_by_actual_availability(self):
        target = self.target()
        rows = [{"observed_at": "2026-11-25T14:35:00Z", "available_at": "2026-11-25T14:35:01Z", "price": 115},
                {"observed_at": "2026-11-25T14:40:00Z", "available_at": "2026-11-25T14:45:00Z", "price": 105},
                {"observed_at": "2026-11-25T14:30:00Z", "available_at": "2026-11-25T14:30:01Z", "price": 120}]
        result = evaluate_frozen_target(target, rows, evaluation_as_of="2026-11-25T14:40:00Z")
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["observations"][0]["distance"], "5")
        self.assertEqual(result["observations"][0]["distance_change_from_origin"], "-5")
        self.assertEqual({r["reason"] for r in result["excluded"]}, {"not_after_decision", "not_available_at_evaluation"})
        self.assertIsNone(result["first_close_inside_at"])

    def test_later_evaluation_uses_original_interval_and_reports_inside_separately(self):
        target = self.target(price=100)
        result = evaluate_frozen_target(target, [{"observed_at": "2026-11-25T14:35:00Z", "available_at": "2026-11-25T14:35:01Z", "price": 105}],
                                        evaluation_as_of="2026-11-25T15:00:00Z")
        self.assertTrue(result["started_inside"])
        self.assertEqual(result["observations"][0]["distance"], "0")
        self.assertEqual(result["first_close_inside_at"], "2026-11-25T14:35:00Z")
        self.assertEqual(result["minimizer"], target["minimizer"])
        json.dumps(result, allow_nan=False)

    def test_frozen_fingerprint_rejects_accidental_target_mutation(self):
        target = self.target()
        target["minimizer"]["upper"] = "200"
        with self.assertRaisesRegex(MaxPainError, "fingerprint"):
            evaluate_frozen_target(target, [], evaluation_as_of="2026-11-25T15:00:00Z")

    def test_future_observation_cannot_be_available_before_observation(self):
        with self.assertRaisesRegex(MaxPainError, "before its price observation"):
            evaluate_frozen_target(self.target(), [{"observed_at": "2026-11-25T14:35:00Z", "available_at": "2026-11-25T14:34:00Z", "price": 110}],
                                   evaluation_as_of="2026-11-25T15:00:00Z")

    def test_no_available_future_observation_has_explicit_empty_status(self):
        result = evaluate_frozen_target(self.target(), [], evaluation_as_of="2026-11-25T15:00:00Z")
        self.assertEqual(result["status"], "no_available_future_observations")

    def test_migration_is_separate_from_frozen_target_outcome_and_rejects_mixed_expiry(self):
        old = self.time_audited_report()
        snapshot = make_teaching_snapshot()
        snapshot["contracts"][1]["open_interest"] = 2
        new = compute_max_pain(snapshot)
        migration = target_migration(old, new)
        self.assertEqual(migration["lower_change"], "20")
        self.assertEqual(old["minimizer"]["lower"], "90")
        new["expiry"] = "2027-01-15"
        with self.assertRaisesRegex(MaxPainError, "cannot mix"):
            target_migration(old, new)

    def test_interval_distance_is_zero_inside_not_distance_to_arbitrary_midpoint(self):
        self.assertEqual(distance_to_frozen_interval(95, 90, 110), "0")
        self.assertEqual(distance_to_frozen_interval(80, 90, 110), "10")
        self.assertEqual(distance_to_frozen_interval(115, 90, 110), "5")

    def test_halfline_distance(self):
        self.assertEqual(distance_to_frozen_interval(500, 110, None), "0")
        self.assertEqual(distance_to_frozen_interval(100, 110, None), "10")

    def test_invalid_interval_rejected(self):
        with self.assertRaises(MaxPainError):
            distance_to_frozen_interval(100, 110, 90)

    def test_future_oi_changes_new_target_without_mutating_old_report(self):
        chain = make_hand_snapshot([("CALL", 90, 1), ("PUT", 110, 1)])
        frozen = compute_max_pain(chain)
        chain["contracts"][1]["open_interest"] = 2
        updated = compute_max_pain(chain)
        self.assertEqual(frozen["minimizer"]["lower"], "90")
        self.assertEqual(frozen["minimizer"]["upper"], "110")
        self.assertEqual(updated["minimizer"]["lower"], "110")


class BatchPayoffCases(unittest.TestCase):
    def test_all_existing_teaching_payoffs_match_single_price_without_changing_minimum(self):
        grid = [0, 89, 90, "95.25", 100, 105, 110, 111, 200]
        for example in ("unique_point", "flat_interval", "max_oi_difference", "calls_halfline", "puts_halfline", "all_zero"):
            snapshot = make_teaching_snapshot(example)
            before = compute_max_pain(snapshot)
            values = loss_at_prices(snapshot, grid)
            self.assertEqual(values, [Fraction(loss_at_price(snapshot, x)) for x in grid])
            self.assertTrue(all(isinstance(value, Fraction) for value in values))
            self.assertEqual(compute_max_pain(snapshot), before)

    def test_unsorted_duplicate_and_genuinely_rational_queries_preserve_exact_values_and_order(self):
        snapshot = make_hand_snapshot([("CALL", 0, 1), ("PUT", 1, 1)], multiplier=1)
        grid = [Fraction(4,3), 0, Fraction(1,3), Fraction(4,3), "0.25", 1]
        self.assertEqual(loss_at_prices(snapshot, grid), [Fraction(4,3),Fraction(1),Fraction(1),Fraction(4,3),Fraction(1),Fraction(1)])

    def test_random_exact_batch_matches_independent_direct_contract_oracle(self):
        generator = random.Random(71421)
        for _ in range(40):
            rows = [(generator.choice(("CALL", "PUT")), str(generator.randrange(0,1200)/10), generator.randrange(0,20)) for _ in range(30)]
            snapshot = make_hand_snapshot(rows, multiplier="12.5")
            grid = [Fraction(generator.randrange(0,500), generator.choice((1,2,3,7,10))) for _ in range(35)]
            before = copy.deepcopy(snapshot)
            expected = [sum((Fraction(oi)*Fraction("12.5")*max(price-Fraction(strike) if side=="CALL" else Fraction(strike)-price,0)
                             for side,strike,oi in rows),Fraction(0)) for price in grid]
            self.assertEqual(loss_at_prices(snapshot,grid),expected)
            self.assertEqual(snapshot,before)

    def test_batch_validates_snapshot_once_not_once_per_grid_price(self):
        from unittest.mock import patch
        from research import max_pain as module
        snapshot = make_teaching_snapshot()
        with patch.object(module,"_validated",wraps=module._validated) as validation:
            loss_at_prices(snapshot,[90,100,110,100])
            self.assertEqual(validation.call_count,1)

    def test_empty_queries_return_empty_after_snapshot_validation(self):
        self.assertEqual(loss_at_prices(make_teaching_snapshot(),[]),[])
        broken=make_teaching_snapshot()
        broken["contracts"][0]["open_interest"]=None
        with self.assertRaises(MaxPainError):
            loss_at_prices(broken,[])

    def test_empty_contracts_have_zero_payoffs_but_no_meaningful_target(self):
        snapshot=make_hand_snapshot([])
        self.assertEqual(loss_at_prices(snapshot,[0,100,Fraction(1,3)]),[Fraction(0)]*3)
        self.assertEqual(compute_max_pain(snapshot)["status"],"unavailable")

    def test_invalid_query_container_size_nonfinite_negative_and_boolean_fail(self):
        snapshot=make_teaching_snapshot()
        for value in (None,"prices.csv",(x for x in range(2)),[0]*100001):
            with self.assertRaises(MaxPainError):
                loss_at_prices(snapshot,value)
        for value in (None,True,float("nan"),float("inf"),"NaN",-1,Fraction(-1,3),Fraction(10**201)):
            with self.assertRaises(MaxPainError):
                loss_at_prices(snapshot,[100,value])


if __name__ == "__main__":
    unittest.main(verbosity=2)
