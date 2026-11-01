# Fast Project Chats loading

EXTEND existing project projection, integer cursor, native renderer and draft
store. No shell/WAS/Hermes edits or second chat implementation.

## API contract

- `GET /api/state?project_id=…` returns the latest <=50 visible chat messages,
  ascending. Ready history is projected to one current revision per worker.
  Message bytes are bounded near 24 KB (one large message is always retained).
- `before=<next_before>` pages older chat messages. `has_older` governs this
  direction. Scroll-up inserts before the visible anchor without jumping it.
- `after=<next_after>` is ONLY for forward polling. `has_more` drains changes,
  never history. Even an empty project keeps polling with `after=0` once loaded.
- `limit` is clamped to 1…50. The project-list screen requests only one message.
- Supply `visibility_revision` from the preceding response. Suppression IDs are
  omitted only when unchanged; omission means retain the prior suppression set.
  A newly restored source reloads the latest window, not every retained row.
- `/api/metadata?project_id=…&revision=…` supplies thread inventory, worker index
  and model receipt only when its content revision changes. It is separate from
  every state poll; the client checks at most once per ten seconds.
- Project preference reads are briefly cached (3 seconds for a local file);
  only the watcher refreshes remote preferences. State and metadata never wait
  for WAS. Metadata projection is cached for 2 seconds. Display-only canonical
  suppression is cached for <=1 second with DB/WAL-stat invalidation; actions
  and model calls ALWAYS revalidate through the original uncached check.
- Gzip is negotiated with Accept-Encoding, with Vary and compressed length.

## Browser contract

A separate per-project localStorage snapshot (latest 50, at most one day old)
paints synchronously before the first network request. It never overwrites the
separate unsent-draft record. Cached state cannot authorize sends or worker
navigation; fresh authoritative state is required. Snapshots retain the delta
cursor and the earliest cached history boundary. Broken/quota-full cache is a
cold open, not lost drafts. Project switches invalidate generations immediately;
old responses, retries, metadata and history cannot enter the new project.

One transient failure quietly retries after 500ms, then 1s; only three failures
show an actionable outage. Existing messages and drafts remain on screen.

## Evidence

Baseline curl: default state 775774 B / 0.365062s; Launch 105785 B / 0.354460s;
Apps 46978 B / 0.351726s. After consolidation, repeated heavy inventory still
made Launch ~51 KB / 0.345s. Candidate fast state: Launch 9824 B / 0.056363s;
default 26427 B / 0.065169s (uncompressed loopback HTTP).

Phone-width read-only live-source candidate (390x844, real shared client,
Nebula): cached Launch DOM 12.3ms, next animation frame 16.6ms, eight updates;
a deliberately rejected single fetch recovered without Try again or text loss.
Another check held the API for 2s and still painted cached messages in 18ms.
This is browser-emulation/hosted-proxy evidence, not physical tailnet latency.

Local tests cover complete older pagination with no gaps/duplicates, bounded
payloads, forward deltas, revision suppression, zero WAS calls and real HTTP
gzip round-trip. Forum-only browser cases cover latest-window loading,
scroll-up, cache-before-network, retained drafts, replacement order and retries.
The full Playwright gate is staged separately; local execution is not claimed.
