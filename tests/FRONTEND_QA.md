# Manager frontend contracts

Run browser QA on the designated remote execution worker, never against the live Manager API.

```sh
node --check web/app.js
node --check tests/frontend.test.cjs
CORE_CLIENT=/path/to/real/shared/core/app-client.js \
PLAYWRIGHT_MODULE=/path/to/playwright \
CHROMIUM_EXECUTABLE=/path/to/Chromium \
FRONTEND_EVIDENCE_DIR=/path/to/evidence \
node --test tests/frontend.test.cjs
```

The suite uses Node's built-in test runner and Playwright 1.58.2 (test-only dependency). It launches a disposable loopback HTTP server. Every API route is intercepted with isolated in-memory fixtures; the static server rejects API requests. The actual shared `app-client.js` is supplied via `CORE_CLIENT`, not copied into this app. Chromium is an existing worker installation, not a new runtime dependency. The test harness's shared service and appearance payloads are explicitly fixtures.

## Verified fixture coverage

- Empty state, a centered 640px desktop column, 360px mobile, hosted transparent background and no duplicate hosted title.
- Ready text and structured `attention.ask` stay inert; no worker-generated approval controls. Explicit user replies may convey approval.
- Exact Ready-message reply targets; nonempty draft switching confirmation; overlay → target → core-root Back ordering.
- Durable API admission remains distinct from downstream delegation. Real stable-ID messages deduplicate; waiting jobs do not block subsequent composition.
- Acceptance preserves newer typing. Unknown sends persist their exact request key/payload across reload; Check again reconciles `user:`/`answer:` correlation without replay. Explicit Retry original uses the same message key/payload, never `/retry`.
- Failed admitted jobs use `/retry` only after fresh failed-state readback.
- Pause immediately gates new sends; the switch changes only with authoritative state. Unknown toggle outcomes remain gated until refreshed.
- Immediate draft write/readback, storage failure hold/send/navigation gating, invalid restored target handling, offline/reconnect without automatic replay.
- Touch Enter, explicit Ctrl+Enter, IME safety, modal focus/Escape, large text, long unbroken titles, internally scrolling multiline composer.
- Five appearance-name protocol fixtures preserve DOM identity, draft, selection, target and reading position. Unseen arrivals show the jump pill; history restore does not replay announcements.
- Pagination beyond 1000 messages before restored-target validation; anchor/offset restore; missing portrait monogram; unavailable-source retained text.

## Self-review notes

- Submission identity is frozen before the first POST and stored independently of the editable draft. Server messages, not optimistic bubbles, establish history and acceptance reconciliation.
- Messages are append-only by canonical integer ID. Jobs and control panels update separately; polling and appearance changes never replace the conversation DOM.
- Only backend-emitted `kind:delegation` plus source identity produces the accepted-work-thread receipt. A queued Manager job cannot produce that claim.
- Source anchors target `_top`; navigation is blocked if the draft cannot be saved. No app-level parent globals, root sentinel, local history router, theme persistence or copied system services.
- Review corrected initial connection-failure copy and aligned Ready portraits with card tops. The first test run also exposed a test-selector ambiguity between visible uncertainty text and its live-region announcement; the selector is now scoped, with no product change required for that test issue.

## Boundaries / integration acceptance

These are deterministic frontend fixtures, not live downstream-delivery proof. Parent integration owns real shell navigation, live skin palettes, physical mobile keyboard/screen-reader checks, gateway setup, backend concurrency/idempotency verification, and release.

Until canonical user messages expose `reply_to`, accepted-target labels use a bounded local compatibility map (300 entries). The UI already prefers a server-provided integer `reply_to` when present. Unavailable-source handling accepts an explicit `source_available:false`; a transient network failure is never translated into deletion. No request-lookup endpoint is assumed or needed for the existing job-ID reconciliation contract.
