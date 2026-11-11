# KIS GPT

KIS GPT explores request-driven AI analysis for domestic equities using market-data conventions from Korea Investment & Securities (KIS). This repository contains the offline analysis and request-handling components. It runs with Python's standard library and includes a synthetic example.

## Design

The original application replaced fixed-interval AI runs with requests triggered by fresh analysis inputs. A structured response contract separates a model's proposal from any execution path. Candidate routing prioritizes existing holdings and a bounded watch list, then rotates through the remaining candidates. Market observations preserve their original timestamps.

The request scheduler serializes access to a paced I/O lane. Urgent work is prioritized, while an ordinary analysis request receives a turn after a bounded run of foreground requests. Request deadlines and cancellation are checked while waiting. After a rate limit, the scheduler increases the interval and returns toward its baseline after sustained successful responses.

| Module | Responsibility |
| --- | --- |
| `analysis_contract.py` | Model instructions and structured response schemas |
| `analysis_pipeline.py` | Candidate selection, bounded news context, and freshness checks |
| `market_context.py` | Completed-bar and observed intraday summaries |
| `market_math.py` | Finite-number and price-tick helpers extracted for the offline snapshot |
| `request_scheduler.py` | Pacing, priority, cancellation, and rate-limit recovery |
| `transport_diagnostics.py` | Allowlisted response metadata and bounded request history |

## Run the offline example

Use Python 3.10 or newer. From the repository root:

```sh
python demo.py
```

The example routes fictional candidates, drops a stale snapshot, and shows the schema fields accepted by the analysis boundary. The repository has no broker or AI client, requires no credentials, and places no orders. Transport diagnostics may include request identifiers when used in another application; keep generated logs local.

## Archive note

This repository is a source snapshot of previously developed work, published for documentation and review.
