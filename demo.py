"""Run a synthetic candidate-routing example without network access."""
from datetime import datetime, timedelta, timezone
import json

from analysis_contract import DECISION_SCHEMA
from analysis_pipeline import analysis_batch, freshness_issue


def main():
    now = datetime(2026, 1, 5, 10, 0, tzinfo=timezone(timedelta(hours=9)))
    universe = [{"symbol": label} for label in ("DEMO-A", "DEMO-B", "DEMO-C")]
    selected, _ = analysis_batch(universe, [], {}, limit=2)
    snapshots = {
        "DEMO-A": {"received_at": now.timestamp() - 20, "indicators": {"last_bar": "095900"}},
        "DEMO-B": {"received_at": now.timestamp() - 200, "indicators": {"last_bar": "095500"}},
    }
    fresh = [symbol for symbol in selected
             if not freshness_issue(snapshots[symbol], now, now.timestamp())]
    print(json.dumps({
        "selected_candidates": selected,
        "fresh_candidates": fresh,
        "response_fields": DECISION_SCHEMA["required"],
    }, indent=2))


if __name__ == "__main__":
    main()
