# Hidden source projection acceptance

A source's canonical `hidden` state is a revocation, not a title heuristic. Existing retained assistant cards, cached thread names, model context and pending Ready events must respect it. Ordinary archives and user-authored turns remain. No diagnostic/message rows are deleted.

Implementation uses the existing opt-in read-only canonical Ready adapter for bounded metadata batches; installations without that adapter use bounded background supported WAS detail reads with expiring, fail-closed receipts. State polls never contact WAS or models. A source failure suppresses assistant updates reversibly, not permanently. The source projection is capped at 10,000 distinct sources. Incremental responses include a complete suppression snapshot and raw pagination cursor; the client removes stale cards/metadata and can replay recovered rows without replacing unaffected nodes or losing drafts.

## Focused checks

- Hidden after ingestion, including restart: no Ready model call or publication; retained diagnostics survive.
- Hidden during summary: no result publication.
- Hidden history, cached inventory and queued replies: omitted/rejected before use.
- Old frozen relay envelopes: canonical source IDs are rechecked without rewriting idempotent payloads.
- Hidden-before-ingestion canonical adapter filters remain covered by ReadySource tests.
- Ordinary archive retention and original user messages remain visible.
- Temporary canonical or WAS failure: fail closed; recovery restores eligible cards.
- Fully suppressed 1,000-row page: raw cursor progresses to later genuine messages.
- Already-open frontend: removal, stored reply-title cleanup, preserved draft/user-node identity, unhide replay in order, reload and no writes.
- Existing Back, read watermark, scroll return, orb receiver and inline-link suites remain green.

## Remote receipt

Full suite on the external-volume worker, Python 3.12 + Node 22 / Chrome:

- `python3.12 -m unittest discover -s tests -v`: **91 passed**.
- `node --test tests/frontend.test.cjs tests/thread-links.test.cjs`: **34 passed, 1 skipped**. The pre-existing skipped case requires an optional private historical-text fixture; synthetic inline-name tests passed.
- `python3.12 app/package.py --check`: **14 packaged files match**.
- Frontend tests used the current deployed shared app-client, not an old core fixture.

`ops/qa-hidden-sources.cjs` is read-only installed-shell acceptance for phone and desktop. Set `QA_ORIGIN`, `QA_OUT`, `PLAYWRIGHT_MODULE`, `CHROMIUM_EXECUTABLE`; mutations are intercepted, assets and API reads are not substituted. Private browser screenshots and live source identifiers belong only in operator evidence, not this repository.

An iframe still executing a pre-release JavaScript bundle cannot interpret the new suppression contract; its normal reopen/reload loads this implementation. No forced reload of an owner's unsaved draft is attempted. Tabs running this implementation revoke cards on their next poll.
