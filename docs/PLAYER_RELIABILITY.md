# Player reliability

## Outcome and current work

Listeners can remove earlier playlist occurrences, repeat a song or playlist,
and operate playback from their phone's system media controls. Playback state,
seeking and update adoption must preserve the current listening session. Investigate
the reported iPhone Home Screen app cross-launch and floating player without
claiming that a plausible cause is a reproduced device failure.

Current step (2026-10-28): remove the rejected visible ±10-second controls and
restore the compact player geometry from `b3df7865`. Clear timed-seek Media Session
handlers so they do not compete with Previous/Next, retaining native scrubbing,
position state and queue-boundary checks. Preserve the separately shipped offline
cache normalization and deployment regression checks. Production handler tests and all four responsive layout checks pass. Browser
playback advances to a second song and returns to the first; paused scrubbing
remains paused. The 265-song contract audit and 20,540 ready/deferred lyric seeks
pass. The local audio audit passes 275 recordings; six historical trim-evidence
conflicts remain unchanged. Independent review found no blocking findings. The owner (iOS 26.3.1)
confirmed that manifest changes did not fix wrong-PWA title taps; that defect is
unresolved and must not be reported as fixed by this release.

## Interfaces and invariants

- `queue.js` owns ordered occurrences, cursor and session-local `repeat`:
  `off`, `one`, `all`. `advance(state, {reason})` distinguishes natural completion,
  explicit Next and failed media. Failures move forward without wrapping;
  song repeat keeps occurrence identity. Removing history shifts the cursor
  while preserving the current occurrence. Shared URLs exclude repeat preference.
- `app.js` owns the persistent audio node and queue-to-media transitions. Native
  completion calls `advance` with `ended`; explicit Next bypasses repeat-one.
  A same-occurrence repeat calls the playback controller at zero without loading
  sources or replacing the reading view.
- `song.js` owns playback intent, failure and seeking. Explicit retry may reselect
  sources once; automatic queue advancement must not become an unbounded retry.
  Buffering is distinguished from confirmed playback. The progress slider supports
  pointer, keyboard and assistive technology without changing pause state.
- The Media Session adapter receives the audio/controller and queue action callbacks.
  It exposes evidenced metadata, actual playback state, valid duration/position and
  Play/Pause/Previous/Next and seek-to-position commands. Interval seeking is
  explicitly disabled to keep native track navigation available. The operating
  system chooses the displayed controls; absent or partial APIs must not break
  in-app listening.
- PWA updates may reload an idle page but cannot reload a document that has started
  a listening session, even when subsequently paused or backgrounded.
- The visible viewport's height and offset remain in CSS pixels during zoom. Keep
  native magnification and anchor to that visible edge; do not inverse-scale controls.

## Implementation order and evidence

Queue and repeat semantics were specified and regression-tested before the UI caller
changed. Independent investigation then split into media controls, PWA lifecycle,
viewport diagnosis and audio/accessibility. Each owner writes focused tests before
its dependent implementation; the lead owns shared app integration and CSS.

Checks include queue persistence/sharing and boundaries; production completion routing
with the real playback controller and controlled media events; generated queue markup;
partial Media Session APIs; seek bounds/paused state; PWA update lifecycle; viewport
zoom/offset/restore cases; syntax, contract and audio-quality audits. Controlled media
events do not prove native decoding, Safari event ordering or background operation.

The catalogue-wide seek check runs the production renderer, delegated click handler
and playback controller for all 265 published songs: 10,270 occurrence buttons,
including 3,533 returning-reference occurrences and six lazily rendered readers.
All 20,540 ready/deferred-metadata seeks match their exact stored occurrence starts.
This verifies timestamp routing, not a fresh acoustic audit of first syllables.

In-app Browser checks covered 375/390px phones, 768px tablet, 1440px desktop,
1920px large display, 2560px geometry, and 844×390 landscape. Player bottoms match
the viewport and controls remain within their panels. These checks exposed and
fixed a large-display implicit grid column that clipped playlist controls.
Native audio completion restarted the same occurrence with repeat-one and wrapped
the last of two songs to the first with repeat-all. History removal preserved
the playing occurrence; paused keyboard seeking, repeat persistence after reload,
Escape focus return, Back navigation, empty search and expanded filters passed.
The real-CSS fixture passed all 24 supplied viewport/zoom/pan geometry assertions.
No browser console warnings/errors were recorded. Desktop viewport overrides and
supplied geometry do not emulate iPhone pinch input, safe-area hardware, background
media controls, or Safari's occasional stale viewport measurements.

## Unresolved observations

- The owner reconfirmed on 2026-10-28 that Now Playing title taps still open
  TimeCrystals. WebKit reports 267810, 318944 and 321673 remain open; the last
  reproduces across unrelated domains, so moving to another domain is not an
  evidenced cure. The [Media Session specification](https://www.w3.org/TR/mediasession/#user-interface-guidelines)
  exposes no action or target for title taps. The browser owns that routing.
  No additional JavaScript, manifest or service-worker fix is established.
- Both apps already have distinct origin-qualified manifest identities. TimeCrystals'
  inspected local installation code does not register a service worker. Its live site
  returned HTTP 406 during inspection. There is no evidence of a shared web storage or
  service-worker scope causing the reported cross-launch. The user confirmed the
  wrong-app launch happens through the Lock Screen / Control
  Center title, matching the reported platform failure rather than a direct Home
  Screen icon launch. WebKit reports
  [267810](https://bugs.webkit.org/show_bug.cgi?id=267810),
  [321673](https://bugs.webkit.org/show_bug.cgi?id=321673), and
  [318944](https://bugs.webkit.org/show_bug.cgi?id=318944) describe Now Playing
  title taps opening another installed PWA, even across unrelated domains.
  A fresh installation after adding explicit manifest ID helped one reporter;
  other reports persist after reinstall. Bhakti already has an explicit ID.
  This is a reported workaround, not a web-code guarantee. Apple also repaired
  stale native parent-app attribution in [WebKit PR 61189](https://github.com/WebKit/WebKit/pull/61189);
  its shipping iOS version was not established here. Prefer the Bhakti Home
  Screen icon over the affected Now Playing title-tap route.
- WebKit has reported stale visual viewport dimensions after keyboard/rotation changes.
  The zoom fallback in this app has a reproducible arithmetic error; fixing it does
  not establish that every reported unzoomed upward drift has the same cause. Capture
  layout, visual viewport and player bounds together before adding another heuristic.
- Existing broad UI tests fail on historical asset-version/generator/workflow assertions;
  comparison with HEAD found the same 271 failures before and after the repeat change.
  The content contract audit separately flags `kaise-lagaun-tumse-main-preet` metadata
  in already-dirty content work. Preserve that work rather than regenerate the library.
- Local quality audit passed 275 recordings. A live audit found six sole source
  URLs returning 404; their reviewed native AAC recordings exist locally. Restore
  hosting and project audio URLs only, preserving all lyric/translation/timing
  content. The trim audit still reports six historical evidence conflicts; none
  establishes a verified qualifying intro remaining unapplied. Keep those findings
  as content work rather than erase their evidence or claim the library is repaired.
