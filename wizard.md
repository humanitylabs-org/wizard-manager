---
wizard: 0.2
id: wizard-manager
name: Manager
type: service
category: app
version: 0.1.0
summary: An optional Archimedes conversation that delegates work and brings back concise Ready updates.
license: MIT
source: https://github.com/humanitylabs-org/wizard-manager
runtime:
  package: source
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8799
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8799
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8799
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides:
- manager-chat
system: false
receives_voice_input: true
uses: []
needs: []
health: /healthz
---

# Manager

## Packaging

`runtime.package: source` runs the stdlib app directly from the pinned repository,
mounted read-only at `/app`, on a digest-pinned official multi-architecture Python image.
No custom image or embedded source payload is needed. `python3 app/package.py --check`
verifies the generated recipe; the Dockerfile remains available for development.
The App Manager must supply `APP_SOURCE_DIR` (wizard-app-manager#153); do not merge this
recipe until that support ships in a Wizard release. Root-owned app-data binds are writable
by running as root with all capabilities dropped, read-only root/source and no-new-privileges.

An optional personal chat with Archimedes, alongside ordinary Chats. DeepSeek Flash answers briefly, delegates substantial requests through Wizard Agent Service (WAS), and compresses new Ready responses into linked updates. The module owns its conversation, dispatch receipts and delivery deduplication. WAS and Hermes remain unchanged.

The app is an opt-in private trial. Disabling pauses monitoring and new model/dispatch calls; existing worker threads continue independently. Reading an update never clears the source thread's Ready/read state. Only an explicit owner request authorizes a handoff or reply.

Configure MANAGER_WAS_URL, MANAGER_MODEL_URL and WIZARD_ROUTER_KEY in runtime environment. The required model is deepseek-v4-1-flash; no fallback. DATA_DIR holds SQLite state. Runtime URLs, host/origin allowlists and secrets are deployment settings, not bundled user data. The host gateway serves the shared WizardApp client.

`MANAGER_READY_DB` explicitly enables a read-only Ready-event adapter for the ordinary agent's canonical SQLite message store. It reads retained per-response status markers by insertion ID (including compacted display history); WAS supplies the visible-session allowlist and active-state gate. No Hermes code, WAS code or source database is changed. This is required for full offline catch-up because the current WAS history response strips status markers. Configure only the ordinary agent store, never mount an entire Hermes home or a Private profile. This adapter is isolated behind `ReadySource` so a future generic WAS event feed can replace it.

Private-agent routing and automated redaction are future capabilities. This version uses ordinary WAS worker sessions only.
