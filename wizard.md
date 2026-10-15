---
wizard: 0.2
id: wizard-manager
name: Manager
type: service
category: app
version: 0.2.0
summary: Reference app with a daily habit list, documented HTTP API, MCP and editable
  view source.
license: GPL-3.0-only
source: https://github.com/owner/wizard-manager
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
- diagnostics
- habit-tracking
system: false
uses: []
needs: []
health: /healthz
---

# Hello Wizard

The builder base: an API and MCP over the same stdlib service layer, with a vanilla view that calls only the API. Add a habit, mark today done, undo it; SQLite persists in app-data. Original time/echo MCP jobs are preserved.

PR24 API/view-source declarations are proposed. The candidate checks them in explicit proposal mode while preserving approved checker compatibility. app/Dockerfile builds from the repository root; the Runtipi compose inlines the exact source for portable installation without publishing an image. Re-run template packaging after source edits.
