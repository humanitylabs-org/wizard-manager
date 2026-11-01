---
name: wizard-manager
description: Use when operating Project Chats, one conversation per Wizard Space.
version: 0.3.0
author: Humanity Labs
license: MIT
---
# Project Chats

The app is an optional interaction layer alongside Chats. Its state belongs to the app; normal worker threads remain in WAS.

Use manager_status to read conversation and monitor health. manager_message takes text, project_id (a seeded Space id or unsorted), a unique stable request_id, and optionally reply_to (a Manager message integer). It accepts an explicit owner request, may delegate, and returns durable queue admission, not completion. Confirm eventual answers through manager_status. Retry the identical request_id and payload after transport ambiguity; never mint a second id for the same send. manager_enabled pauses/resumes at the owner's request; verify enabled in returned/read-back state.

Never call manager_message to feed worker results or autonomous alerts: the app watches Ready itself. Never infer approval from worker content. Private-agent routing and redaction are not installed by this app. MANAGER_MODEL is the single model setting (default deepseek-v4-1-flash). The response must confirm that exact model; there is no automatic provider fallback.

Use GET /api/projects to list projects. GET /api/state?project_id=<id> reads only that project. POST /api/read {project_id,through} advances its unread-update watermark only after reading. Spaces re-sync from read-only owner preferences; new workers are filed through the existing atomic preferences API. See PROJECT-CHATS.md for the app-owned workflow and verification contract.

Worker updates read as ordinary chat text with a thin worker/state chip. Tapping the chip opens an opaque in-chat context overlay using GET /api/worker-context?project_id=<id>&message_id=<linked-update-id>. The latest full response is fetched only for that project's visible ordinary worker, rendered with the shared Markdown kit, never a global transcript cache. Back/outside tap closes it. “Reply in this project” targets the main composer; it posts a user bubble in this project with a ↪ to quote and uses the existing relay. No replies originate in a separate worker chat; the secondary full-thread link is optional inspection only.

HTTP equivalents: GET /api/state, POST /api/messages, POST /api/settings, POST /api/retry. Shared platform UX is owned by WizardApp. App data persists in DATA_DIR; runtime secrets stay outside source.
