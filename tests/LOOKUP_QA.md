# Manager thread lookup

## Behavior and boundaries

Previously `plan()` ranked only titles (top 25 plus 45 recent threads), then sent
one latest snippet per selected thread. A request buried in an unrelated title,
or supplied as a screenshot and discussed later by the assistant, was invisible.

Lookup/status requests now run read-only retrieval before the model plans its
reply. Ordinary greetings and fresh handoffs retain the fast path. Retrieval:

- Uses the canonical WAS snapshot inventory, keeping the existing main-agent,
  non-child, non-hidden, non-archived boundary and excluding private agents.
- Interleaves title/latest-snippet matches with recency, then reads projected
  `GET /api/sessions/<id>/messages?order=latest&limit=500&offset=...&include_compacted=true&view=wizard`.
- Uses `pagination.returned`, **not** filtered `data.length`, to advance pages.
  WAS can remove internal rows after upstream pagination. `shareable:false` on a
  **user** row does not make the user's request private; for assistant rows it
  excludes non-final/internal/tool activity from lookup evidence.
- Searches user text, attachment filenames, and final assistant discussion.
  Voice/dictation/transcription and tab/tabs vocabulary bridges improve recall;
  document-frequency weighting avoids verbose generic coding chats dominating.
- Prioritizes matching excerpts ahead of the old title list. Evidence includes
  canonical message IDs, roles, timestamps, and latest visible messages.
- Rechecks every selected exact ID through WAS before passing titles/excerpts to
  the model. A removed/private/failed detail read fails closed for that thread.
- Makes no upstream search call: WAS does **not** currently expose Hermes's
  `/api/sessions/search` route. Bypassing WAS or scanning the agent DB is forbidden.

Budgets: 96 candidate threads, 128 history-page requests, four pages/thread,
six concurrent reads, 500 upstream messages/page, 15 seconds for inventory plus
history, and up to 12 seconds for exact-ID visibility checks. The model sees at
most 70 threads, 12 with evidence, three matching excerpts and two latest visible
messages each. No persistent transcript index, dependency, schema, or model change.

Coverage/failure metadata is explicit. Even a complete lexical pass sets
`absence_proven:false`; the prompt forbids claiming nonexistence or non-delivery
from a missing match. Historical instructions remain untrusted context. Lookup
and status are reply actions, not new delegated investigations. A worker report
or preview is not proof of deployment. These are model instructions, not a claim
that lexical retrieval can guarantee semantic recall or that a model cannot err.

## Verification

Run sustained tests on the designated QA worker; keep evidence and scratch on
its external work volume. Set `QA_ROOT` to that isolated workspace.

```sh
cd "$QA_ROOT/source"
TMPDIR="$QA_ROOT/tmp" python3 -m unittest discover -s tests -v \
  > "$QA_ROOT/evidence/unit-final.log" 2>&1
CORE_CLIENT=/path/to/shared-core/app-client.js \
PLAYWRIGHT_MODULE=/path/to/playwright \
CHROMIUM_EXECUTABLE=/path/to/Chrome \
FRONTEND_EVIDENCE_DIR="$QA_ROOT/evidence/browser" \
node --test tests/frontend.test.cjs tests/thread-links.test.cjs \
  > "$QA_ROOT/evidence/browser.log" 2>&1
```

Verified on Thales: **71 Python tests passed**; browser/resolver suite **25 passed,
0 failed, 1 skipped** (optional private historical-snapshot test not supplied).
The new regression suite was first run against the old `plan()` behavior and
failed; `red.log` preserves the result.

`ops/lookup_plan_probe.py --out <private-evidence.json>` accepts private JSON on
stdin: `was`, `model_url`, `key`, and `cases` with `name`, `text`, and
`expected_evidence_ids`. Optional `was_host`/`model_host` preserve canonical Host
headers through SSH forwards. Do not log or persist credentials. The probe
allows only WAS GETs and the configured model request; it calls `plan()`, never
`process_job()` or dispatch, and asserts its isolated jobs remain queued.

Real configured `deepseek-v4-1-flash` replay on Thales: **4/4 passed**. Both exact
original Manager questions included the correct original thread's historical
evidence and returned `reply` with its correct source link. A nonsense-keyword
query qualified its negative result as incomplete; an injected inventory failure
reported unavailable lookup, not missing work. Historical titles/status changed
concurrently during the exercise, so private reports retain actual contexts and
model outputs rather than committing stale status claims. The run took about
19–23 seconds per live lookup over the SSH route, and about two seconds for the
injected-failure case. Some history reads hit the deadline; results disclosed
bounded coverage. Exact visibility checks all succeeded in the accepted run.

`ops/alias_plan_probe.py` also passed **24/24** real configured-model cases. Its
WAS lookup seam uses synthetic fixtures and never reaches real WAS. This guards
main-agent aliases, quoted/worker instructions, context freezing, missing
referents, and ordinary conversation against regressions.

## Integration (not performed by this branch)

Parent independently reviews and cherry-picks the pushed commit into the live
Manager integration line, then restarts its existing service using its existing
environment. No migration, dependencies, model/provider change, shell/orb change,
Android build, or VM-image rebuild is needed. After integration, replay the two
original questions in Manager and verify inline links navigate to the canonical
threads and no lookup creates a new delegated job. Deployment acceptance belongs
to the parent; this isolated branch has not been deployed.
