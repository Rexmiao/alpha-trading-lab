"""Offline safety and interpretation checks; no broker/network is exercised."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/audit_moomoo_option_data.py"
SPEC = importlib.util.spec_from_file_location("moomoo_option_audit", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class QuoteAuditTests(unittest.TestCase):
    def test_host_rejects_remote_and_credential_urls(self):
        for host in ("https://example.com", "http://127.0.0.1@evil.example", "http://user:secret@localhost:22222",
                     "http://127.0.0.1:22222/accounts", "http://127.0.0.1:22222?key=secret", "file:///tmp/quote"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                audit.local_host(host)

    def test_host_accepts_explicit_loopback(self):
        for host in ("http://127.0.0.1:22222", "http://localhost:22222", "http://[::1]:22222/"):
            self.assertEqual(audit.local_host(host), host)

    def test_invalid_ports_fail_closed(self):
        for host in ("http://localhost:80", "http://localhost:99999", "http://localhost:wrong"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                audit.local_host(host)

    def test_only_quote_commands_are_allowed(self):
        forbidden = {"get-acc-list", "position-list-query", "accinfo-query", "place-order", "modify-order",
                     "order-list-query", "deal-list-query", "listen", "unlock-trade"}
        self.assertFalse(forbidden & audit.ALLOWED)

    def test_excess_or_unapproved_symbols_rejected_before_credential_access(self):
        for symbols in (("SPY", "QQQ", "NVDA"), ("SPY", "SPY"), ("AAPL",)):
            with self.subTest(symbols=symbols), patch.object(audit, "credential") as key:
                with patch("sys.stderr"), self.assertRaises(SystemExit):
                    audit.main(["--symbols", *symbols])
                key.assert_not_called()

    def test_non_object_json_preserves_safe_failure(self):
        for payload in (None, [], [1], 1, "secret"):
            data, error = audit.quote_envelope(json.dumps(payload).encode(), b"", 0)
            self.assertIsNone(data)
            self.assertEqual(error["code"], "INVALID_RESPONSE_SHAPE")
            self.assertNotIn("secret", str(error))

    def test_malformed_success_body_is_rejected(self):
        for s2c in (None, [], "quotes"):
            data, error = audit.quote_envelope(json.dumps({"ret_type": 0, "s2c": s2c}).encode(), b"", 0)
            self.assertIsNone(data)
            self.assertEqual(error["code"], "INVALID_RESPONSE_SHAPE")

    def test_stderr_business_error_is_not_logged(self):
        data, error = audit.quote_envelope(b"", b'{"error":"invalid appkey SUPER_SECRET ret_type=-1 err_code=-1002"}', 1)
        self.assertIsNone(data)
        self.assertEqual(error, {"code": "AUTH_OR_PERMISSION", "ret_type": -1, "err_code": -1002})
        self.assertNotIn("SUPER_SECRET", str(error))

    def test_subscription_quota_is_not_missing_subscription(self):
        self.assertEqual(audit.safe_failure("subscription quota exceeded")["code"], "QUOTA_OR_RATE_LIMIT")

    def test_auth_denial_before_subscription_is_auth(self):
        self.assertEqual(audit.safe_failure("permission denied for subscription")["code"], "AUTH_OR_PERMISSION")

    def test_valid_empty_subscription_envelope(self):
        self.assertEqual(audit.quote_envelope(b'{"ret_type":0,"s2c":{}}', b"", 0), ({}, None))

    def test_optional_field_presence_does_not_invent_missing_paths(self):
        paths = audit.schema_paths({"ticker_list": [{"dir": "BUY"}, {"recv_time": 1.2}]})
        self.assertIn("ticker_list[].dir", paths)
        self.assertIn("ticker_list[].recv_time", paths)
        self.assertNotIn("ticker_list[].capacity", paths)

    def test_zero_missing_nan_and_bool_are_not_validated_greeks(self):
        rows = [{"option_ex_data": {"gamma": 0, "open_interest": 0}},
                {"option_ex_data": {"gamma": float("nan"), "open_interest": True}}, {}]
        observed = audit.numeric_presence(rows)
        self.assertEqual(observed["fields"]["gamma"], {"present": 2, "nonnull": 2, "finite": 1, "zero": 1})
        self.assertEqual(observed["fields"]["open_interest"]["finite"], 1)
        self.assertFalse(observed["independent_validity_verified"])

    def test_vendor_flow_does_not_become_mm_inventory(self):
        observed = audit.vendor_flow_summary([{"dir": "BUY", "volume": 10}, {"dir": "SELL", "volume": 4}])
        self.assertEqual(observed["signed_vendor_pressure_native"], 6)
        self.assertIsNone(observed["q"])
        self.assertIsNone(observed["mm_side_probability"])
        self.assertIsNone(observed["inventory_change_observed"])
        self.assertEqual(observed["calibration_status"], "NO_PARTICIPANT_LABELS")

    def test_neutral_and_unknown_flow_are_not_forced_into_sell(self):
        observed = audit.vendor_flow_summary([{"dir": "NEUTRAL", "volume": 9}, {"dir": "other", "volume": 5}])
        self.assertEqual(observed["signed_vendor_pressure_native"], 0)
        self.assertEqual(observed["neutral_or_unknown_volume_excluded"], 14)

    def test_missing_or_invalid_size_does_not_silently_become_zero(self):
        for size in (None, -1, True, float("inf")):
            observed = audit.vendor_flow_summary([{"dir": "BUY", "volume": size}])
            self.assertIsNone(observed["signed_vendor_pressure_native"])
            self.assertEqual(observed["unknown_size_rows"], 1)

    def test_volume_pressure_can_differ_from_trade_count(self):
        observed = audit.vendor_flow_summary([{"dir": "BUY", "volume": 20},
                                              {"dir": "SELL", "volume": 1}, {"dir": "SELL", "volume": 2}])
        self.assertLess(observed["direction_counts"]["BUY"], observed["direction_counts"]["SELL"])
        self.assertGreater(observed["signed_vendor_pressure_native"], 0)

    def test_nearby_pair_uses_observed_spot_and_explicit_partial_selection(self):
        def pair(strike):
            return {side: {"basic": {"security": {"code": f"SPY261127{letter}{strike * 1000}"}},
                           "option_ex_data": {"strike_price": strike}} for side, letter in (("call", "C"), ("put", "P"))}
        data = {"option_chain": [{"option": [pair(99), pair(100), pair(101)]}]}
        selected, method = audit.choose_pairs(data, 100.2)
        self.assertEqual(selected, ["US.SPY261127C100000", "US.SPY261127P100000"])
        self.assertEqual(method, "nearest_strike_to_observed_underlying_quote")

    def test_future_provider_times_are_flagged_without_repair(self):
        rows = [{"timestamp": 1795799344.473}, {"timestamp": 1795799344.0}]
        original = json.dumps(rows)
        observed = audit.clock_diagnostics(rows, "2026-11-27T17:09:04.400000+00:00")
        self.assertEqual(observed["provider_later_than_local_receipt_rows"], 1)
        self.assertAlmostEqual(observed["max_provider_minus_receipt_ms"], 73, places=2)
        self.assertFalse(observed["clock_alignment_verified"])
        self.assertFalse(observed["timestamps_repaired"])
        self.assertEqual(json.dumps(rows), original)

    def test_unknown_timestamp_unit_is_not_silently_converted(self):
        observed = audit.clock_diagnostics([{"timestamp": 1795799344473}, {"timestamp": None}],
                                           "2026-11-27T17:09:04.400000+00:00")
        self.assertEqual(observed["missing_or_invalid_timestamp_rows"], 2)
        self.assertIsNone(observed["max_provider_minus_receipt_ms"])


if __name__ == "__main__":
    unittest.main()
