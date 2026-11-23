# Library and playlist repair — 23 October 2026

## Letters, tag rows and view motion — 22 November 2026

Owner reports: some romanized vowels (notably `e`) carry odd marks or look much
larger than their neighbours; swiping the filter tags in the app is slow and clunky.

- **Letters.** The deployed fonts held no `ẽ` or candrabindu, and their declared
  ranges left out the combining tilde, so `ẽ`, `ā̃` and `m̐` were drawn whole in a
  larger system font (the source pages hid this by using Google's files). The fonts
  are rebuilt as one complete file per face (407 KB → 290 KB), preloaded; the tilde
  is raised clear of the macron, which EB Garamond overprinted. 64 readers stored
  ISO `ē`/`ō` in Indo-Aryan or Sanskrit lines; the reader now displays IAST `e`/`o`
  there and writes `a͠i`/`k͟h` as `aĩ`/`ḵẖ`. Three titles are corrected in data.
- **Tag rows.** In the installed shell (17 November) `.app-scroll` made no stacking
  context, so WebKit held the four rows as detached scroll-proxy nodes. `isolation:
  isolate` puts them back inside it; rows are paint boundaries that only move
  sideways, and each button is a 44px target without positioned or transformed
  layers. Measured in system WebKit, installed-shell mode, 390×844: proxy nodes
  4 → 0, layers 65 → 51, median rendered frame while swiping 3 ms → 1 ms.
- **View motion.** A song opened from a scrolled library slid in at the stage's
  top, out of sight, then jumped. The arriving view is offset to the place it will
  open at (mid-slide top −6000px → 0px from a library scrolled 6,000px).

Checks: `test_reader_romanization.js` covers every stored line (word links kept,
every displayed Latin character inside the one face); view-transition and shell
regressions; all workflow tests. The measurements are desktop WebKit, not a
physical iPhone; the owner's phone remains the final judge of the swipe.

## iPhone PWA silent playback — 15 November 2026

Outcome: the shared player must recover an unpaused but frozen media element,
preserve the current song/position, and offer a truthful Play action when recovery
cannot complete. Native resume must update the controller, too. Explicit pause,
OS pause and replacement cancel deferred work; backgrounding alone never pauses
healthy audio. No automatic queue skip for an interruption or loading timeout.

The user's exact device failure is not reproduced on desktop. WebKit reports
[323022](https://bugs.webkit.org/show_bug.cgi?id=323022) and
[295518](https://bugs.webkit.org/show_bug.cgi?id=295518) describe silent/frozen
HTML media after iOS backgrounding. Feature-detected Audio Session `playback`
type matches this music app; it is not proof of a device-specific cure.

Implementation order: establish controlled event/clock regressions, then add
session setup and progress monitoring to the existing controller in `song.js`.
Monitor only visible, requested, unpaused playback. Four seconds without progress
with playable data permits one pause/seek/play recovery; another frozen interval
or sixteen seconds loading leaves an explicit retry. Pause/reset/hidden pages
cancel timers. Healthy progress and a new user request reset the recovery budget.
Keep one timer per audio element and no background polling or retry loop.
Separately fix the confirmed view-transition ownership race in `app.js`.
Check controller/native resume/cancellation, existing player/queue/PWA tests,
all stored lyric seeks, real in-app browser media and responsive navigation,
independent review and scoped release audits. Physical iPhone interruption and
audibility confirmation remain distinct from deterministic and desktop evidence.

The owner also reports the player floating mid-screen until the iPhone PWA is
quit. A deterministic stale-sampling case reproduces in the bootstrap: a
foreground event reads a temporary positive height, the native viewport silently
settles, and ordinary document scrolling never refreshes the cached anchor.
Repair: cancel hidden/pending frame work, coalesce ordinary scroll/scrollend
refreshes, and resample actual bounds at 100/300/1000ms after pageshow, foreground,
orientation or focus dismissal. Stop those finite checks on hiding/restart; avoid
unchanged CSS writes. Preserve viewport coordinate/zoom semantics and audio.
This covers delayed measurements and abandoned frames, not proof that the
physical device's compositor or native viewport metrics are always correct.

Verified candidate: independent review found no material blockers. New frozen
playback/native-resume cases fail against the old controller; all nine new
viewport cases and the navigation reversal also failed before their fixes.
Controller, queue, repeat, keyboard, progress, Media Session, PWA update,
viewport (18 cases) and navigation tests pass. All 337 published songs pass
the content contract; 26,748 ready/deferred seeks cover their 13,374 occurrences.
In-app browser: all 74 line buttons across Koī Hor and Bolo Lakṣmī seek correctly;
native playback, pause retention, paused keyboard seeking, playlist controls,
navigation and empty search work. Final 390×844 ↔ 844×390, 820×1000, 1440×900,
1920×1080 checks have no horizontal overflow and zero player-bottom gap with
audio advancing. The real-CSS geometry fixture passes 26 checks, including
late restoration without another viewport event and ordinary-scroll recovery.
Python compilation, whitespace and public assembly pass. Offline shell test
passes all 12 actual index asset URLs. Audio quality reports no errors.
The retained trim audit checks 112 songs and reports six pre-existing evidence
issues, identical with production pipeline code; none reports verified
untrimmed material. No lyric, audio or timing changes are included.

Release is isolated from the busy checkout on current production `cc1cf903`;
only owned player/app code, regressions, this note, CI checks and shell v47 ship.
Physical iPhone interruption/audibility and persistent native viewport/compositor
misreporting remain unverified; this evidence does not establish flawlessness.

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
from player, playlist, reader and library controls. Completed in `95b78dce`; GitHub Pages run `40018122847` succeeded.
Live checks confirmed all five new asset versions, guarded hover rules, Skip/Pause,
disabled queue boundaries and playlist open/close.

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

## Player floating after phone rotation

User evidence: installed-iPhone screenshot shows the player across the middle
of scrolling lyrics; rotation is the suspected trigger. The existing player is
a body-level sibling of the animated stage, with no transformed ancestor.
The defect cannot be reproduced in the available desktop in-app browser.
WebKit reports [301172](https://bugs.webkit.org/show_bug.cgi?id=301172) and
[218983](https://bugs.webkit.org/show_bug.cgi?id=218983) describe related fixed-bottom drift and
rotation/keyboard viewport failures, but do not establish this device's cause.

Implemented: replace bottom-edge attachment with a top anchor at the dynamic
viewport height, translated by the player's own height. Keep the same DOM/audio
node and safe-area padding; no scroll resets, guessed keyboard offsets, polling
or VisualViewport compensation. The playlist and status use the same viewport
height, preserving existing reveal transforms. Remove unused positional easing
from the player so rotation updates immediately.

Verify player bottom == viewport bottom and playlist bottom == player top after
portrait/landscape cycles, scrolling in both directions, queue open/close, search
focus/blur and page navigation, at phone/tablet/desktop/large-screen sizes. Check
ongoing audio and hit targets. These checks establish normal-layout compatibility;
the affected iPhone must confirm the intermittent WebKit symptom is resolved.

Verified candidate: independent CSS review passed, including a feature-query
fallback for browsers without individual `translate`. The in-app browser measured
a zero-pixel player-bottom gap through repeated 390×844 ↔ 844×390 changes, then
820×1000, 1440×900 and 1920×1080. Open-playlist alignment stayed within 0.008px;
audio continued. Search focus/blur, library/song navigation, action status (44px
above player), scroll in both directions, open/close and all 39 lyric seeks on
Aisā Pyār Bahā De Maiyā passed. This is normal-layout verification, not reproduction
of the intermittent iOS bug.

Contract: 265 ready/no problems. Audio quality: no errors. Python compilation,
whitespace and player/queue JS checks pass. The trim audit retains the same six
legacy-evidence failures previously recorded (104 checked); no audio/content
changes are part of this patch.

Published as `2aae8777`; Pages deployment `40064228676` succeeded. The live
page loads `app.css?v=dock-20261023`. Live portrait → landscape → portrait
checks again measured zero player-bottom gap with uninterrupted playback.
Mobile screenshot: `/tmp/bhakti-ui-evidence/player-dock-live.png` (local evidence).
Remaining acceptance: confirm the intermittent symptom on the affected iPhone
after rotation; this desktop browser cannot reproduce that OS-level condition.

### Recurrence, October 24

The new phone screenshot shows both playlist and player displaced, with the
playlist tools behind the status bar. The CSS-only fix did not settle device
acceptance. Next repair: update the shared viewport bounds from the unzoomed
VisualViewport on resize/scroll and page restore/foreground events, falling back
to layout height when unavailable or pinch-zoomed. Keep document scroll, audio
and reader state untouched. Bound playlist height by the available space above
the player and below the top safe area; all overlay anchors share those bounds.

Check event-driven refresh with stale layout height, portrait/landscape return,
visual offsets, page restoration, fallback, zoom and transient invalid values.
Then verify actual layout/queue interaction in the in-app browser at phone,
tablet, desktop and large widths. Desktop checks cannot certify the affected
iPhone's compositor. No polling, guessed keyboard height or forced scrolling.

Implemented measured bounds and player ResizeObserver; the service-worker shell
advances to v39. Seven viewport-input regressions passed (previous bootstrap
failed all seven), plus existing queue/state/keyboard checks. The browser fixture
uses the production bootstrap/CSS with height 300, offset 120 and safe-top 44:
both phone and desktop layouts place the player bottom at 420, the capped sheet
at 164–320 and its toolbar fully inside. This is a deterministic input fixture,
not an iOS emulation. Independent design/test and implementation review found no
blocking defect.

Real-app in-app-browser checks: 390×844 → 844×390 → 390×844, tablet 820×1000,
desktop 1440×900, TV 1920×1080 and short 390×300. Settled player bottoms matched
viewport bottoms; playlist/player joins differed by at most 0.008px. Breakpoint
changes retain the existing reveal animation; measurements were repeated after
it settled. Playback continued, playlist scrolling reached 2532px without moving
the player/tools, Escape and the playlist trigger worked, and Home/search/song
navigation preserved the dock. All 23 Rāma Rasa line seeks landed within one
second of their rendered first-syllable start, with the player fixed at 844px.
Local screenshot: `/tmp/bhakti-ui-evidence/viewport-repair-local.png`.

The exact release snapshot (HEAD plus these UI files) passes the contract audit:
265 songs, zero problems; public-site assembly succeeds. The shared checkout has
unrelated ongoing song edits/intake and seven content-audit issues, excluded from
this release. Audio-quality audit has zero errors; Python compilation and diff
checks pass. Trim audit still reports the same six previously recorded evidence
failures (111 checked); this patch changes no media or timing data. Physical
iPhone confirmation remains open; normal browser checks cannot settle the
reported intermittent compositor failure.

## 17 November 2026 — performance repair

Outcome: ship responsive loading, library search, playlist interaction and long
readers without changing any recording, audio source/quality, lyric, gloss,
translation, timing, occurrence order or existing playback capability.

Current step: implementation and independent code review complete; rebased onto
release 0078868c to retain the separately published translation corrections.
Recheck the assembled artifact and deployment checks against that content, then
publish the scoped release to main and verify deployment and live resource bytes.
The owner explicitly authorized publication without the unavailable browser
checks ("Publish without"). Visual layout and device behavior remain unverified;
automated coverage does not replace that acceptance.

Design and ownership:
- Library: precompute immutable search forms; preserve phrase-first matching;
  reuse catalogue rows and one on-demand contextual menu. Keep all songs reachable.
- Reader: complexity-budgeted chunks with offscreen rendering containment;
  preserve complete text/accessibility and exact occurrence seeks. Avoid rebuilding
  the same mounted data; stop hidden-reader work, read media time once and use
  logarithmic lookup. No removal of content to meet performance budgets.
- Playlist: keyed updates rather than full-list replacement; defer offscreen
  layout, batch drag reads/writes and preserve keyboard movement/focus. Give
  titles stable readable measure and word wrapping. Full queue remains available.
- Loading: release-aware static caching, same-origin fonts with Latin Extended,
  lazy shuffle resources and worker computation preserving algorithm/order
  membership. Async shuffle results must not overwrite a newer queue operation.
- App integration: retain audio node and its native user-activation behavior;
  bounded recent-song data cache, no stale navigation commits or same-song reset.

Implementation order: review existing behavioral tests and add meaningful red
regressions for each owned module before its implementation; independent modules
can proceed together. Integrate async shuffle and reader visibility after module
interfaces are stable; release assembly follows all runtime integration.

Checks: exact audio/catalogue/song-data identity against the baseline; existing
queue/repeat/playback/media-session/PWA/navigation/filter suites; targeted tests
for search equivalence, keyed row identity, rendering/seek boundaries, cache
online/offline/update isolation and async shuffle races. Benchmark identical
365-song workloads. Run required Python contract, audio, trim and shuffle audits,
py_compile and diff checks. In-app browser checks cover 390px/tablet/desktop/TV,
long readers, line seeks, focus and queue controls when available. Record real
limitations; source harnesses do not establish phone frame times.

Verification recorded 17 November:
- Search/filter, playlist identity/focus/drag, player/media/PWA, async worker,
  reader, loading/navigation and release-integrity regression suites pass.
- Real DOM parsing covers all 365 songs and 14,324 lyric occurrences: 28,648
  exact ready/deferred seek checks, including returning refrains and overlaps.
- 366 assembled entrypoints have 5,122 matching resource hashes/SRI bindings;
  every original audio source and song-data byte is retained. No media is
  encoded, uploaded, replaced or reordered by this release.
- Native CacheStorage checks cover first-install offline, zero-network warm
  reads, old/new revisions, integrity failure, quota failure and failed install.
- Contract audit and shuffle-profile audit pass; Python compilation and scoped
  whitespace checks pass. The legacy UI static suite has the same pre-existing
  source-version, generator-drift and old hosted-intake assumptions as baseline;
  new behavioral checks exercise the actual assembled artifact instead.
- Audio audit was invoked but this isolated source worktree has no ignored local
  recordings, so it cannot reprobe their codecs. Trim audit has no local private
  review packets here. The complete source/data comparison establishes that this
  frontend-only change leaves those existing audio and timing artifacts intact.
- Identical 365-song Node workload: median pure search 11.805ms → 0.107ms;
  playlist repeat render in jsdom 63–77ms → 15–16ms. These are not phone frame
  times. Sundarakanda late-seek elements 18,548 → 4,272; full semantic text is
  now initially present, so its initial element count rises 1,723 → 4,225 while
  rich word links fall 1,324 → 311. Native find/layout needs browser acceptance.

## 18 November 2026 — installed iPhone player drift recurrence

Outcome: the player remains at the screen edge during scrolling and after page
restoration without changing audio, queue, lyrics or reading position. The four
owner screenshots show the player adjacent to the same lyric while its screen
position changes; this is consistent with a fixed-position compositor attachment
failure. The exact device trigger is not reproduced. The existing measured
VisualViewport/top/translate repair has not resolved the owner's symptom.
WebKit reports 218983, 301172 and 315992 document related standalone viewport and
fixed-element drift; they support the mechanism, not a claim of device proof.

Design: installed touch apps use a normal-flow, viewport-height shell with two
rows: a dedicated scrolling content region and the original player in normal
flow. No fixed/translated player or document scrolling is needed in this mode.
Mode selection is independent of width/rotation. Browser tabs and desktop apps
retain their established layout and zoom. CSS dynamic viewport height owns the
unfocused shell, so stale positive VisualViewport data cannot shorten it. While
an editable control is focused, measured visual bounds accommodate the keyboard.
Playlist/status are absolute siblings in this shell and use its measured height
and the actual player height. App navigation owns scroll reads/writes for its
scroll container; native lyric following must scroll only that container. Meaning
and menu dismissal observes descendant scrolling. Audio/source nodes retain identity.

Current step: implementation, independent review and automated release checks
complete; publish and verify live resources. Ten full-bootstrap DOM regressions
cover activation (including desktop exclusion), original audio/source parentage,
resting CSS independence from stale viewport measurements, editable focus/blur,
scroll restoration, actual karaoke/follow callers, and popup/playlist behavior.
The previous implementation fails the shell regressions. The exact Pages check
step passes, including all 365 readers' ready/deferred line seeks and integrity
checks across 366 entrypoints. Contract audit, Python compilation and whitespace
checks pass. Song data, media metadata and audio source declarations are unchanged.
Audio/trim audits were invoked: this isolated source checkout has no ignored local
recordings or private trim packets, so it cannot reprobe those existing artifacts. In-app Browser remains unavailable in
this chat. Prior owner authorization permits publication without it; physical
iPhone confirmation remains necessary to establish the intermittent defect is gone.
