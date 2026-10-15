# Operational queue status and lookup diagnostics

Global execution counts are not conversation search results. Manager now uses a
cheap vocabulary candidate filter followed by the configured model's semantic
intent decision. Read-only global queue/capacity questions call the Agent Service
health endpoint (the configured WAS prefix, without `/hermes`, plus `/health`).
The reply is rendered directly from validated `queue` fields; the model does not
invent counts. This path makes one bounded four-second health GET and no inventory
or message-history requests. Explicit thread reply handoffs keep their existing
routing semantics. Queue/concurrency development requests still use ordinary
planning and dispatch authorization.

All five fields are required: nonnegative integer `max_active`, `active`, `queued`,
and boolean `dispatch_paused`, `liveness_available`. Missing, malformed or failed
health reads return unavailable, never zero or cached totals. Active slots are
labelled as queue accounting, not proof of individual task progress. Unavailable
worker liveness and paused dispatch are explicit. No queue limit is changed.

History lookup retains at most eight diagnostic records (canonical session ID,
page offset, request timeout, elapsed time, exception class, failure category and
HTTP status when available). Exception messages/bodies/URLs are excluded. The
report distinguishes unread coverage and exhausted budgets from attempted reads
that failed; none establishes failed agent work. Coverage and diagnostics are
stored in the existing job plan, without another transcript cache or schema.

## Regression checks

Run on an isolated execution worker with temporary files on its work volume:

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
CORE_CLIENT=/path/to/current/shared/app-client.js \
PLAYWRIGHT_MODULE=/path/to/playwright \
node --test tests/frontend.test.cjs tests/thread-links.test.cjs
python3 app/package.py --check
```

The implementation was first tested against the old code: the operational tests
failed. The integrated candidate passed 79 Python tests and 32 browser/resolver
tests (one optional private snapshot test skipped). Browser checks use the current
shared client, including retained hosted-chat, orb and unread/return behavior.

`ops/lookup_plan_probe.py` supports `expect_queue`, `expect_not_queue`,
`simulate_health_failure`, and `expected_action` case fields in addition to its
existing history checks. It uses isolated storage and `plan()` only. Only WAS
reads and configured model calls are allowed; it checks that isolated jobs remain
queued and no assistant delivery is written. Reports include source hashes,
actual model IDs/outputs, observed health data and request paths. Keep the reports
private: history cases contain conversation evidence.

Real-model candidate cases covered the original combined running/queue/capacity
question, a concurrency paraphrase, injected health failure, explicit queue-fix
handoff, quoted queue-question wording and an actual bounded historical lookup.
All six passed with the configured model. The operational path required one model
classification and one health read, not a history scan. The live-history case
exposed an upstream HTTP 502 and deadline-limited reads; diagnostics report those
as retrieval failures, not failed work. These tests do not repair that upstream
history service or certify exhaustive history coverage.
