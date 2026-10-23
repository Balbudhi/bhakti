# Library and playlist repair — 23 October 2026

Outcome: a compact library and a continuous, replayable listening session using
the existing palette, type, player and responsive playlist layout.

## Acceptance and ownership

- `assets/library.js` owns search/filter selections and contextual song menus.
  A compact Filter control beside search reveals four tag rows without headings;
  descriptive reset chips explain each row. Closing preserves selections and
  scroll, with an active-filter count on the control. Song actions use a small
  anchored popover without moving rows. No-results searches explain recovery.
  The 390px initial view must show songs without scrolling.
- `assets/queue.js` owns ordered occurrence identity and the current index.
  Playing another song retains prior occurrences. Play next inserts immediately
  after current; Add to end appends; clearing removes only upcoming entries.
  History replay and Previous/Next move the cursor without losing list order.
- `assets/app.js` owns session persistence, media selection and playlist UI.
  Same-tab fresh navigation and reload restore the session. Shared URLs remain
  supported. Playback must follow actual media state. Queue edits must not
  pause/reload the current audio. The expanded playlist shows previous, current
  and upcoming occurrences in order, without the Played-count dropdown.
- Keep repeated-song occurrence identity, sharing, keyboard reorder, focus after
  rerenders, media failures and correct transport boundaries intact.

## Work order and checks

1. Inspect live 390px layout, contracts and actual state callers (done).
2. Derive regression cases before changing queue operations and library behavior.
3. Implement independent library and playlist slices; keep shared integration,
   documentation and release with the lead. No lyric, timing or source edits.
4. Independently review integrated changes. Exercise real browser operations,
   playback continuity, replay, navigation/reload and keyboard controls. Check
   390px, tablet, desktop and large-screen layouts and reduced motion.
5. Run focused JS tests, song UI contract checks and repository release audits;
   distinguish pre-existing content failures from this UI change. Publish only
   scoped files, then verify the deployed site.

## Media failure found during verification

The native browser reproducer is a missing `ekdant-gajvadan/audio.m4a`:
clicking Play leaves the old UI showing Pause at `0:00 / —:—`. A failed
`<source>` emits its own non-bubbling error; the prior app handled only the
audio element's error. This blocks truthful playback acceptance.

One reader playback owner will route main Play, Space, lyric seeks and queue
transport. It must allow native fallback selection, recognize exhausted sources
including errors before binding, keep unavailable audio paused, and advance
only when an actual failure interrupts requested playback. Idle preload must
never start another song. Reset/pause invalidate pending play and seek work;
removed source nodes and rejected stale promises cannot affect a new song.
Playing visuals follow native `playing` or fulfilled `play()`, not an optimistic
`play` event. Source URLs and content remain outside this repair.

## Evidence so far

- Independent review found and closed sharing's catalogue-size occurrence cap
  and the global Space shortcut stealing native button/summary activation.
- Queue state/sharing, retained-history, keyboard-handler, library filtering and
  search suites pass. Meaningful history/sharing/keyboard regressions failed
  before their fixes.
- Native browser: Play next/append retain audio; Clear upcoming preserved
  running time `20.911834 → 20.9558`, current song and history. Reload and a bare
  homepage navigation restored the queue. Replay, Next, keyboard reorder and
  removal focus were checked. Space opens Filters without pausing.
- 390px library first-row top is 404px, compared with 617px before repair;
  three complete songs fit the first screen. No horizontal document overflow
  at 390, 820, 1440 or 1920px. Playlist remains a sheet below desktop and a
  non-modal right panel on desktop; full titles wrap instead of truncating.
- All 74 line seeks across Koī Hor Nahī Hai Merā and Bolo Lakṣmī Māt Kī Jay!
  reach their retained starts in the native browser. This is interaction
  verification, not a new first-syllable listening audit.
- Clean committed-catalogue audit: 265 ready, zero migration failures. Local
  audio-quality audit: no errors. Intro trim audit: 111 checked, no failures.
  Python compilation and whitespace checks pass.

- Final media controller passed independent review and event/promise tests.
  Native browser checks confirm: a missing source stays paused after Play;
  a failing first source falls back to a working second source; idle failure
  stays at song 1; explicit Play skips it once to song 2. Clear upcoming kept
  that successful playback running `4.565885 → 4.608914` seconds. All 74 lyric
  seeks were rerun through the new controller and passed.
- A real shared link with 266 occurrences against 265 catalogue songs opens;
  all 266 distinct occurrence IDs survive reload. Opening a second song in a
  fresh standalone session retains the first song in history.
- The old UI contract suite has exactly the same 267 failure identities on the
  untouched baseline and release candidate; no new failure was introduced.
- Reduced-motion CSS and the reorder guard are source-reviewed; the available
  browser tooling does not emulate an OS reduced-motion preference.

Completed: release `dbb69c32` was pushed to `main`; the subsequent main commit
`a3366b3f` includes this release and GitHub Pages run `40002915596` succeeded.
The first deployment run was superseded by that concurrent content commit.
Production checks verified the versioned
assets, 390px first-row position of 404px with no overflow, Play next/append,
Next reaching actual playback (`readyState=4`, time advancing), and retained
history/current position after reload. Only scoped UI files and asset-version
changes were staged; unrelated song and pipeline work was preserved.

## Further work, separate from this UI release

- The live probe covered 407 distinct declared sources. Six return 404:
  `neelkanth-mahadev-dayalu`, `mahadeva-vishambar`, `jaagiye-raghunath-kunwar`,
  `shri-ramachandra-kripalu-bhajman`, `ekdant-gajvadan`, and
  `jayati-jayati-shri-ganesh`. Publish their verified original listener assets
  and update the manifest through the existing media-release workflow.
- Repair stale `test_song_ui_contract.py` assumptions about asset-version
  prefixes and generated-page equality. The pre-change committed checkout
  already has 267 failures; the version-prefix assertion alone fails on every
  current song. Do not treat that noise as a passing gate.
- Consider persistent listening history across browser sessions, with an
  explicit reset action. This repair preserves the existing same-tab session
  and shared-link model; it does not introduce cross-device storage.

## Compact controls refinement

Completed: compact controls released in `df3a5e35`; GitHub Pages run
`40005315826` succeeded. Live 390px checks confirmed versioned assets, tag-only
filters, the anchored popup, both queue commands and no horizontal overflow. The design
standard now distinguishes search filters, contextual actions and the playlist;
it preserves the established palette, typography, dedication and player.

- Filter opens only four closely stacked horizontal tag rows at all sizes.
- Play next / Add to end use one anchored menu, bounded by viewport and player.
- Outside click, focus leaving, Escape, scroll, resize, navigation and command
  selection dismiss it; arrows navigate, Tab leaves, focus returns as needed.
- Regression cases cover navigation dismissal and a trigger behind the player;
  both reproduced failures before the fixes.

Verification: 17 focused JS tests pass; independent review has no remaining
material findings. Native mobile checks confirm both queue commands, retained
selection and Back/Forward dismissal. Expanded filters fit at 390, 820, 1440
and 1920px without document overflow. The 390px collapsed first row begins
at 347px. Contract audit: 265 ready, no problems; audio quality: no errors.
Release trim audit with retained private evidence: 104 checked, no failures.
The separate in-progress trim validator reports failures against local evidence;
that validator and content work are excluded from this UI release. Python
compilation and whitespace checks pass.

## Touch feedback and state consistency

Outcome: retain the approved appearance while removing sticky post-tap feedback
from player, playlist, reader and library controls. Current step: implement the
reviewed state rules and regression cases (done); publish the verified scoped assets.

1. Guard all public hover decoration in site/song/app CSS by input capability;
   keep selected/open/singing states outside that guard and keyboard focus distinct.
2. Prevent disabled command hover/press and give main Play an explicit focus ring.
3. Clear preface and reader word-preview highlights with their tooltip, including
   scroll, Escape and cached-view cleanup; retain interactive tooltip scrolling.
4. Verify state transitions in focused tests and the native in-app Browser; check
   390px, tablet, desktop and large-screen layouts, then exact release callers.

Independent review identified missing preface Escape/preview cleanup and reader
hover-preview scroll cleanup. New regressions reproduce those defects. The in-app
browser offers viewport resizing but no touch-input emulation; physical-phone
input remains a separate acceptance check, not implied by the 390px screenshot.

Verification: 36 focused JS tests pass, including red-before-fix cases for stale
highlights, hybrid touch and resize. Independent review found no remaining
blockers. Native browser checks cover preface dismissal/reopen, selected filters
versus keyboard focus, Play/playlist focus rings, repeated playlist open/close,
Skip reaching the last item, and disabled Skip retaining zero hover fill.
53 Jaya Jagdisha Hare line controls seek to their stored starts. All four layout
widths fit without document overflow; browser-parsed public CSS has zero unguarded
hover rules. Small circles retain their visible size with 44px hit areas.

Contract audit: 265 ready, no problems. Audio-quality audit: no errors. Python
compilation and whitespace checks pass. Trim audit: 104 checked; six failures
are byte-for-byte identical with unchanged baseline pipeline code (legacy review
validity / applied-interval mismatch), with no verified-untrimmed-material failures.
These evidence repairs remain separate from the UI release. Physical-phone touch
and OS reduced-motion behavior were not available to this browser; input guards,
pointer sequences and reduced-motion rules were checked without claiming device
emulation.
