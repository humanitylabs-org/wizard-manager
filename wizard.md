---
wizard: 0.2
id: wizard-manager
name: Manager
type: service
category: app
version: 0.1.0
summary: An optional Archimedes conversation that delegates work and brings back concise Ready updates.
license: GPL-3.0-only
source: https://github.com/humanitylabs-org/wizard-manager
runtime:
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
uses: []
needs: []
health: /healthz
---

# Manager

An optional personal chat with Archimedes, alongside ordinary Chats. DeepSeek Flash answers briefly, delegates substantial requests through Wizard Agent Service (WAS), and compresses new Ready responses into linked updates. The module owns its conversation, dispatch receipts and delivery deduplication. WAS and Hermes remain unchanged.

The app is an opt-in private trial. Disabling pauses monitoring and new model/dispatch calls; existing worker threads continue independently. Reading an update never clears the source thread's Ready/read state. Only an explicit owner request authorizes a handoff or reply.

Configure MANAGER_WAS_URL, MANAGER_MODEL_URL and WIZARD_ROUTER_KEY in runtime environment. The required model is deepseek-v4-1-flash; no fallback. DATA_DIR holds SQLite state. Runtime URLs, host/origin allowlists and secrets are deployment settings, not bundled user data. The host gateway serves the shared WizardApp client.

Private-agent routing and automated redaction are future capabilities. This version uses ordinary WAS worker sessions only.
