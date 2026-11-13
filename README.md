# KIS GPT

KIS GPT explores request-driven AI analysis for domestic equities using market-data conventions from Korea Investment & Securities (KIS). This repository contains offline components and synthetic tests from the project. It runs with Python's standard library.

## Design

The original application replaced fixed-interval AI runs with requests triggered by fresh analysis inputs. A structured response contract separates a model's proposal from any execution path. Candidate routing prioritizes existing holdings and a bounded watch list, then rotates through the remaining candidates. Market observations preserve their original timestamps.

The request scheduler serializes access to a paced I/O lane. Urgent work is prioritized, while an ordinary analysis request receives a turn after a bounded run of foreground requests. Request deadlines and cancellation are checked while waiting. After a rate limit, the scheduler increases the interval and returns toward its baseline after sustained successful responses.

The application checks its analysis cutoff both before collecting data and before sending it. A review with no open positions first records short observations about each candidate, then requests a final decision. If the final response is interrupted, the next review can reopen the saved observations and use them with fresh quotes. Checkpoints are limited to the same scope, mode, date and reference version, and expire after a bounded period. The compact payload represents minute bars as rows with shared column names while preserving their time, price and volume fields.

An order cancellation can appear as a separate broker record while the original order lacks a terminal flag. The ledger checks the original order, linked cancellation and outstanding-order view before clearing the previous order. Missing or conflicting evidence keeps the order unresolved.

| Module | Responsibility |
| --- | --- |
| `analysis_contract.py` | Model instructions and structured response schemas |
| `analysis_context.py` | Compact payloads that preserve minute-bar values |
| `analysis_pipeline.py` | Candidate selection, bounded news context, cutoff and freshness checks |
| `market_context.py` | Completed-bar and observed intraday summaries |
| `market_math.py` | Finite-number and price-tick helpers extracted for the offline snapshot |
| `observation_store.py` | Persist, reopen and consume candidate observations |
| `order_reconciliation.py` | Reconcile broker-supplied order and cancellation records in a local ledger |
| `request_scheduler.py` | Pacing, priority, cancellation, and rate-limit recovery |
| `transport_diagnostics.py` | Allowlisted response metadata and bounded request history |

## Run the offline example and tests

Use Python 3.10 or newer. From the repository root:

```sh
python demo.py
python -m unittest -v
```

The example routes fictional candidates and drops a stale snapshot. The tests use temporary SQLite files and synthetic inputs to check request cutoffs, checkpoint recovery, preservation of bar data, and cancellation reconciliation with missing or conflicting evidence. The repository has no broker or AI client, requires no credentials, and places no orders. These tests verify component behavior and do not measure trading performance.

## Archive note

This repository is a source snapshot of previously developed work, published for documentation and review.
