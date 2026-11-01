# Project Chats worker-update repair

REUSE/EXTEND: existing Ready ingestion, Sonnet hidden-WAS inference, project
projection, native context sheet, Appearance v1 client and thread resolver. No
shell, WAS or Hermes edits; no new capability implementation.

Each (project, source worker) has ONE visible Ready update. New immutable
revisions supersede older rows in the chat projection, move to the bottom, and
count as one unread worker. Original rows and exact reply targets are retained.
The Sonnet prompt receives the previous consolidated summary plus new output and
writes 1–2 short paragraphs with only the current ask. There is no fallback model.
A scan may update several workers independently; cross-worker narrative batching
is intentionally optional, not an extra message stream.

The sheet's **Earlier project updates** paginates retained summaries, newest
first, without opening a different worker. Membership and canonical visibility
are rechecked for each page. No row migration/deletion occurs.

Regression coverage: existing backlog collapse, one unread per source,
replacement/cursor behavior, previous-summary model input, updated ask, exact
paragraph retention, history pagination and hidden/cross-project denial. The
forum suite additionally checks replacement DOM order.

Phone screenshots are hosted-proxy read-only live-source acceptance (cloned app
DB; real pinned app-client and chat-kit; no watcher, sends disabled), Nebula and
Obsidian Light Appearance v1. This is not physical-phone or public-tailnet proof.
The live hostname was not resolvable from the tool browser.
