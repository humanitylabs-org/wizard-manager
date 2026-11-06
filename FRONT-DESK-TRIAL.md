# Front desk trial (private, disposable branch)

REUSE: existing options dialog, switch, Appearance v1 styles, JSON plan validation,
durable jobs and Agent Service API. EXTEND: app-local settings and routing adapter.
NEW: receipt/owned-worker tables and read-only scorecard. No Hermes, Agent Service,
shell, public catalog or shared-main changes.

## Behaviour

`POST /api/settings {"front_desk_trial": true|false}` persists in this app's own
`manager.sqlite3`; default false. The existing `enabled` switch is independent.
The options label is **Front desk trial (DeepSeek + Hermes Lite)**.

OFF uses the unmodified `ProjectManager` planning and `HermesInference` Sonnet
route. Its only new response field is `front_desk_trial`; trial tables are inert.
Existing routing source files are not edited. Work already admitted in trial mode
retains its approved route/idempotency identity when retried after switching OFF.

ON calls only `deepseek-v4-1-flash` at the existing `MANAGER_MODEL_URL`, using
`WIZARD_ROUTER_KEY` without exposing it. The returned model must match. Failure
retains the request and shows a retryable error, never a model fallback. Existing
plan validation still rejects unknown actions/worker IDs.

The code-owned `PUBLIC_ALLOWED` default is `(coding, web_research)`. A latest
explicit imperative to ask/use Archimedes or the main agent can choose `hermes`.
Otherwise only those categories with no `PRIVATE_TOPICS` match in the actual
owner-supplied context may exit to `hermes`. Everything else uses `hermes-lite`.
Old requests, quoted requests and a model's privacy/worker fields do not approve
an exit. Policy is re-evaluated immediately before dispatch; existing chats on a
different agent are never reused across the boundary. Frozen pre-trial plans are
reclassified before being replayed in trial mode.

Briefs are constructed from original owner messages, not model prose or assistant
summaries. A plain reference check removes model-generated paths/URLs/IDs absent
verbatim from source. No new facts are invented. If later adding fetched facts,
add the actual fetched source to that same check, not a model's paraphrase.

Owned Lite runs are read only through their exact Agent Service receipts. No
private-agent directory is read. Completed results are summarized by DeepSeek,
visibility-checked, deduplicated, and returned to the app. Existing main-worker
Ready handling is reused. Existing shared nav.openThread agent options are reused.

## Receipts / scorecard

`front_desk_receipts` records coordinator and dispatch calls: exact coordinator
model, action/route, worker, privacy decision/reason, latency, reported tokens,
error class and canonical admitted session/run IDs. No prompts, key values or raw
exception strings are recorded. Dispatch token counts are unknown and zero;
scorecard totals are coordinator usage, not a claim about worker token usage.

```
python3 ops/front_desk_scorecard.py --since 24h
```

All scorecard connections are `mode=ro`. Lite's user-turn count is read only from
`~/.hermes/profiles/hermes-lite/state.db` (role/timestamp/count; no content).

## Release status / scope fence

Discovery on James's box found `wizard-manager.service` stopped, no Manager
container, no WAM installation (only the launcher.json tile), and HTTP 404 for
`/wizard-manager/` at both local gateways 8923 and 8928. The last configured
checkout is `3499a72eb8066fb7e967839b1644b3a5adc73b28`, used as this branch's
base; it is NOT claimed as an actively served live revision. The recorded old
private release path is the user systemd unit, port 8948, environment file
`~/.config/wizard-manager/runtime.env`, data in
`~/.hermes/data/apps/wizard-manager`. Shared gateway changes remain out of scope.

Do not promote to main or publish an app catalog release. Deployment cannot be
called complete until the owner app route is restored without shared core edits,
all existing tests pass, data backup/integrity checks pass, real OFF/ON routing
canaries pass, trial is left OFF, and phone/desktop Nebula/Light screenshots are
inspected. Tests use only isolated labelled fixtures, never live proof.

## App-only activation / rollback (after acceptance)

The existing unit can point to the named-branch worktree using a dedicated app-only
`~/.config/systemd/user/wizard-manager.service.d/90-front-desk-trial.conf`:

```ini
[Service]
WorkingDirectory=/home/telos/front-desk-trial
ExecStart=
ExecStart=/usr/bin/python3 /home/telos/front-desk-trial/app/server.py
```

Back up the whole app data directory and take a verified SQLite backup before
starting this candidate. Then `systemctl --user daemon-reload` and
`systemctl --user restart wizard-manager.service`. Read `/healthz` and `/api/state`
on port 8948 and the real app gateway before claiming success. Changing the unit
does not itself restore a missing gateway route.

Rollback: stop this app unit, remove **only** the trial drop-in, daemon-reload,
then restore its previous active/inactive state (it was inactive at discovery).
The original app ignores the additive trial tables. Restore the data backup only
if required for migration failure; do not overwrite owner messages created since.
A serving clone/remote and app-parity-gate PASS are required before any cutover.
