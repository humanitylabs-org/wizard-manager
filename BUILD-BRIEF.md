# Optional Archimedes Manager trial

Owner: Archimedes, originating Wizard OS · Manager thread. User approved building a separate app, optional alongside Chats, with clean Opus-designed UX, Archimedes profile picture, and shared Wizard skins/app standard.

Consequential lane: new UI, persistent app state, runtime dependency and cross-thread dispatch. Hermes core and normal Chats unchanged; no WAS fork. Manager owns conversation, routing, summaries and dedupe; uses existing WAS APIs. Model must be Tinfoil deepseek-v4-1-flash, no fallback. Existing configured route is settings.json fast_router. Plain chat/status brief; substantial work queues real normal sessions; every new Ready assistant result gets compressed once, linked. Replies to updates route to the correct thread. Direct chat and Manager can run concurrently. Disable stops watcher and model calls, retains history and existing work. Startup initial inventory should not flood with old updates. No automatic approvals from worker content.

Acceptance:
1. Actual fast-model reply in persistent distinct chat; send/readback/restart/draft recovery.
2. Explicit substantive task dispatch via WAS, truthful accepted receipt and thread deep-link; Manager remains responsive.
3. Ready listener and one-per-response summary, restart/reconnect dedupe, source links, reply targeting; direct Chats and read state untouched.
4. Optional enable/disable round trip and no new model calls/dispatch while disabled.
5. Real Wizard shell UI with shared core client, transparent glass, fluid skins, phone/desktop, Back overlay/root, clean profile portrait.

Route: one standalone package from wam template, private trial install with separate service and state, no public catalog promotion. All commits immediately pushed on named feature branch. Sustained build/test/browser QA on Thales under /Volumes/ThalesMedia; source editing/services/lightweight probes on VPS. No guest image rebuild. Opus via first-party Claude CLI designs; Archimedes implements/integrates and verifies; fresh read-only reviewer before delivery.

First vertical slice: authenticated local app API -> configured DeepSeek Flash -> persisted reply -> app chat. Then WAS dispatch and listener. Source /home/telos/.wizard-os/dev/wizard-manager. Proof must be real API/model/worker output, no fabricated transcripts. Keep functional test data isolated and clearly labeled.
