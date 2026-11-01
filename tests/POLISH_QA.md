# Project Chats polish regression gate

The changes extend the existing app renderer, native context dialog and composer.
REUSE: WizardApp Appearance/Back, the existing thread resolver and safe Markdown
renderer, and opaque shared panel roles. No shell, Hermes, WAS, schema or runtime
changes. No new worker actions or source fetches.

## Behaviour

- Each Ready update has one message paragraph. A meaningful structured ask is
  plain text, not a second paraphrase appended to an older stored summary. If the
  summary already contains that ask, its prose stays intact. Empty asks and
  “Nothing needed” keep the summary. When the ask replaces a stored summary,
  the original remains readable as plain text under **Original project update**
  in the existing context sheet. No stored rows are rewritten.
- The jump pill occupies a reserved composer row, outside the conversation's
  scroll rectangle. Bottom padding alone cannot prevent overlap while reading
  the middle of history. The same isolation holds with a taller composer and
  enlarged jump text. Jumping to latest removes the extra row without moving
  the latest message out of view.
- `needs_you`, `needs_approval`, `needs_input`, and `check` use the shared accent
  plus heavier text in both chips and the context sheet. Neutral/resolved results
  do not retain this emphasis. The close control has no native border or shadow;
  keyboard `:focus-visible` retains a two-pixel accent ring.

## Existing frontend failures corrected

1. The outer app fills the desktop host (1440px in that fixture), as intended
   since removal of the old 640px cap. The empty-view test now acknowledges both
   scoped polite live regions: the conversation announcer and worker report.
2. Orb targeting uses the actual **Reply in this project** action, asserting that
   it closes the context dialog before opening another chip. There was no
   production dialog-close bug: an open modal intentionally blocks other chips.
3. Hosted source navigation opens the chip and then **Open full thread**. The
   exact native canonical ID and retained draft assertions are unchanged.

All original 43 registered cases remain (38 Playwright frontend + 5 thread-link
unit cases). Four added browser cases cover one-message rendering/inert actions,
phone and desktop jump clearance, and live Nebula/Light accents/keyboard focus.
The complete staged command therefore registers **47 cases** (42 + 5), not a
filtered subset. Registration counting is not a claim that Playwright passed.

## Appearance fixture correction after the first forum run

The `polish-18dca45` run timed out in the new appearance case before any color
assertion. Both its pinned shared client and the current `wizard-ux` client set
`data-color-scheme`, but only after validating **all 14** Appearance v1 color
roles. The fixture omitted `canvas`, `chrome`, `overlay`, `surface`,
`surface-raised`, `accent-soft`, `on-accent`, and `reader-surface`; the extra
opaque `panel` roles do not replace those required roles. This was an invalid
test payload, not a different attribute name or an app accent bug.

The corrected fixture sends the complete payload through the real shared
client, waits for its revision-specific ACK, and retains the actual
`data-color-scheme` wait. Accent assertions now check the exact expected RGB
values for both schemes rather than comparing two controls that might both
remain on the fallback. No app-local appearance implementation was added.
The branch was rebased onto main `ec8f65e` (including the Sonnet backend change).
The case count stays 47; a fresh complete forum run is still required.

## Verification and release hold

Locally required:

```
python3 -m unittest discover -s tests
node --test tests/thread-links.test.cjs
node --check web/app.js
node --check tests/frontend.test.cjs
python3 app/build_view.py
python3 app/package.py --check
```

The full browser suite must run on forum against the immutable staged git tree,
with the real pinned shared `core/app-client.js` and `core/chat-kit.js`, the prior
`run-forum-tests.py` pattern, manifest hash verification, and retained evidence.
Run both `tests/frontend.test.cjs` and `tests/thread-links.test.cjs` with no name
filter. Merge and deployment are blocked until the complete runner passes.

Manual screenshots use a labelled synthetic read-only hosted preview, actual
Appearance host/client and Nebula/Light palette tokens. Inspect phone-sized
(390x844) and wide desktop (1440x900) views and open sheets. Live switching must
preserve the same app document, open dialog and unsent draft. This is hosted-proxy
layout proof, not physical-device or live-worker acceptance. No private-agent,
Messenger or recording content is used.
