# Project Chats delivery contract

Owner-approved conversion of the existing Manager app in place. App id, data,
service and gateway route remain `wizard-manager`; display name is Project Chats.
The existing custom coordinator surface is explicitly retained by this brief;
worker conversations use the real hosted Chats thread via WizardApp.nav.openThread.
No Hermes, WAS or shell code changes.

## Shared components

- REUSE: WizardApp shared client, nav.openThread, Back, theme, voice admission,
  draft/update holds; existing Manager durable admission, relay, summary/dedupe,
  hidden-source suppression and native worker links.
- EXTEND: Manager SQLite rows with project_id; Space read-only preference adapter;
  WAS atomic preference item operation for worker membership; existing web view
  with list/detail navigation and project-local drafts/read positions.
- NEW: project/membership index and persisted per-project unread watermark.
  No second worker runtime, global transcript cache or duplicated shared canvas.
- Visual: existing Archimedes portrait; no new artwork. Appearance v1 tokens,
  transparent hosted canvas, opaque existing floating panels, dark standalone
  fallback; verify phone/desktop in shell on Nebula and Light before completion.

## State and authority

Each ordinary main-agent Space seeds one project, plus Unsorted. Preferences
are read from the server-owned ui-preferences.json without writing the file.
Space removal hides its project but keeps conversation data. Worker metadata
is title/state/activity only. Private agents, Messenger and recording ids are
excluded. Worker transcript retrieval is not part of routing.

Owner requests are relayed verbatim, with preceding project chat explicitly
marked untrusted context. Only the latest request authorizes work. No worker
text grants approval. New worker ids and WAS run idempotency keys are stable
across crashes. Worker membership and the routing receipt are committed in the
same transaction; Space filing has an idempotent durable outbox and readback.

New Ready responses for indexed workers produce a short summary and linked
update. The existing insertion cursor, event identity and unique delivery key
survive restart. Per-project unread counts only unread updates, not direct
answers or another project's history. Fetching/listing is not reading.

## Model

`MANAGER_MODEL` is the single model selection (default deepseek-v4-1-flash),
with `MANAGER_MODEL_URL` and the existing router credential supplied at runtime.
Effective-model confirmation remains mandatory. No paid provider is added.
Configured Sonnet availability and authorized app inference reachability must
be tested separately; a subscription catalogue alone is not a working route.

## Verification

Unit fixtures are isolated and labelled; never use their output as live proof.
Real QA must use a separate app DATA_DIR, hidden-before-first-message workers,
and source-scoped metadata projection if hidden sessions must be observed.
Keep authentic canonical worker response rows as evidence, never fabricate a
transcript. Browser suites and four shell screenshots run on forum.

Deployment: back up DATA_DIR before schema migration; preserve exact live
ancestry, merge through PR to main when checks pass, promote merged main,
restart wizard-manager.service and compare served assets to the merged tree.
