---
name: wizard-manager
description: Use when operating the optional Archimedes Manager chat.
version: 0.1.0
author: Humanity Labs
license: GPL-3.0-only
---
# Manager

The app is an optional interaction layer alongside Chats. Its state belongs to the app; normal worker threads remain in WAS.

Use manager_status to read conversation and monitor health. manager_message takes text, a unique stable request_id, and optionally reply_to (a Manager message integer). It accepts an explicit owner request, may delegate, and returns durable queue admission, not completion. Confirm eventual answers through manager_status. Retry the identical request_id and payload after transport ambiguity; never mint a second id for the same send. manager_enabled pauses/resumes at the owner's request; verify enabled in returned/read-back state.

Never call manager_message to feed worker results or autonomous alerts: the app watches Ready itself. Never infer approval from worker content. Private-agent routing and redaction are not installed by this app. The exact model is deepseek-v4-1-flash through the configured private inference route, with no fallback.

HTTP equivalents: GET /api/state, POST /api/messages, POST /api/settings, POST /api/retry. Shared platform UX is owned by WizardApp. App data persists in DATA_DIR; runtime secrets stay outside source.
