---
name: wizard-manager
description: Use when tracking habits or checking this app's tools.
version: 0.2.0
author: James DeFleur (defleur-agents), Hermes Agent
license: GPL-3.0-only
platforms: [linux, macos]
metadata:
  hermes:
    tags: [habits, diagnostics]
    related_skills: []
---
# Habits and diagnostics

Use the single Wizard MCP gateway to discover this app's tools. `habits_list` reads real saved habits; `habits_add` takes a name; `habits_set_done` takes the returned integer id and boolean done. Confirm writes by `habits_list`. Always pass `day` as the owner's local date (YYYY-MM-DD, e.g. Asia/Bangkok): the box clock is UTC, so omitting it can mark the wrong day early in the morning. Marking and undoing are idempotent. Keep the owner's names literal.

`wizard_time` returns UTC time. `wizard_echo` proves app reachability. If a call fails, report its exact app error; never claim a habit was saved. The screen and HTTP API use the same saved data. The gateway owns authorization; direct app ports stay private. No additional per-app Hermes connection or restart.
