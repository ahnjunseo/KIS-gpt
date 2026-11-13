"""Reproduce interrupted reviews and ambiguous order cancellations offline."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from analysis_context import BAR_FIELDS, compact_context
from analysis_pipeline import freshness_issue, within_analysis_hours
from observation_store import ObservationStore
from order_reconciliation import KST, Ledger


class AnalysisRecoveryTests(unittest.TestCase):
    def test_dispatch_cutoff_can_close_while_preparing_inputs(self):
        preparing = datetime(2026, 1, 5, 14, 59, 59, tzinfo=KST)
        ready_to_send = preparing.replace(hour=15, minute=0, second=0)
        self.assertTrue(within_analysis_hours(preparing, cutoff="15:00"))
        self.assertFalse(within_analysis_hours(ready_to_send, cutoff="15:00"))
        self.assertTrue(within_analysis_hours(ready_to_send, cutoff="15:15"))
        self.assertFalse(within_analysis_hours(ready_to_send.replace(day=10)))

    def test_reopen_saved_observations_and_pair_with_fresh_market_data(self):
        day = "20260105"
        now = datetime(2026, 1, 5, 10, 15, tzinfo=KST)
        checkpoint = {
            "review_id": "demo-review",
            "reference_hash": "demo-reference",
            "observed_at": "2026-01-05T10:00:00+09:00",
            "created_at": time.time() - 900,
            "observations": [{"symbol": "DEMO-A", "note": "Review the next quote."}],
        }
        with TemporaryDirectory() as directory:
            db = Path(directory) / "observations.sqlite"
            ObservationStore(db, "demo", "paper").save_observations(day, checkpoint)

            # Simulate the final decision timing out and reopening the store.
            reopened = ObservationStore(db, "demo", "paper")
            saved = reopened.load_observations(day, "demo-reference", 1080)
            self.assertEqual(saved, checkpoint)
            self.assertIsNone(reopened.load_observations(day, "changed-reference", 1080))
            self.assertIsNone(reopened.load_observations(day, "demo-reference", 60))
            self.assertIsNone(reopened.load_observations("20260106", "demo-reference", 1080))
            other_mode = ObservationStore(db, "demo", "other-mode")
            self.assertIsNone(other_mode.load_observations(day, "demo-reference", 1080))
            other_scope = ObservationStore(db, "other-scope", "paper")
            self.assertIsNone(other_scope.load_observations(day, "demo-reference", 1080))

            candidate = {"received_at": now.timestamp() - 5, "indicators": {"last_bar": "101400"}}
            self.assertEqual(freshness_issue(candidate, now, now.timestamp()), "")
            stale = dict(candidate, received_at=now.timestamp() - 901)
            self.assertTrue(freshness_issue(stale, now, now.timestamp()))
            payload = {"saved_observations": saved, "candidates": {"DEMO-A": candidate}}
            self.assertEqual(compact_context(payload, subscription=True)["saved_observations"], saved)

            reopened.consume_observations(day, "different-review")
            self.assertEqual(reopened.load_observations(day, "demo-reference", 1080), saved)
            reopened.consume_observations(day, saved["review_id"])
            self.assertIsNone(reopened.load_observations(day, "demo-reference", 1080))

    def test_compact_bars_preserve_order_and_every_value(self):
        first = dict(zip(BAR_FIELDS, ("20260105", "100000", 100, 103, 99, 102, 10)))
        second = dict(zip(BAR_FIELDS, ("20260105", "100100", 102, 104, 100, 103, 20)))
        original = {"candidates": {"DEMO-A": {"recent_bars": [first, second]}}}
        compact = compact_context(original, subscription=True)
        rows = compact["candidates"]["DEMO-A"]["recent_bars"]
        self.assertEqual([dict(zip(BAR_FIELDS, row)) for row in rows], [first, second])
        self.assertEqual(len(compact["recent_bars_columns"]), len(BAR_FIELDS))
        self.assertEqual(original["candidates"]["DEMO-A"]["recent_bars"], [first, second])


class CancellationRecoveryTests(unittest.TestCase):
    def test_only_consistent_broker_records_release_the_prior_order(self):
        scope, symbol = "demo", "DEMO-A"
        original = {
            "odno": "000123", "pdno": symbol, "sll_buy_dvsn_cd": "01",
            "rmn_qty": "0", "tot_ccld_qty": "0", "cncl_cfrm_qty": "0",
        }
        cancel = dict(original, odno="000124", orgn_odno="123", ord_qty="2",
                      ord_unpr="0", rjct_qty="0")
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "orders.sqlite")
            ledger.reserve("sell", scope, symbol, "sell", 2, 100)
            ledger.state("sell", "ACCEPTED", "123")
            ledger.reserve("cancel", scope, symbol, "cancel", 0, 0, kind="cancel", broker_id="123")
            ledger.state("cancel", "CANCEL_REQUESTED", "123", receipt_id="124")

            self.assertEqual(ledger.reconcile(scope, [original], []), {})
            self.assertEqual(ledger.reconcile(scope, [original, cancel], [original]), {})
            self.assertEqual(ledger.reconcile(scope, [original, dict(cancel, odno="125")], []), {})
            self.assertEqual(ledger.reconcile(scope, [original, dict(cancel, ord_qty="1")], []), {})
            self.assertEqual(ledger.unresolved(scope)[0][6], "ACCEPTED")

            self.assertIn("123", ledger.reconcile(scope, [original, cancel], []))
            self.assertEqual(ledger.unresolved(scope), [])
            self.assertFalse(ledger.cancel_requested(scope, "123"))


if __name__ == "__main__":
    unittest.main()
