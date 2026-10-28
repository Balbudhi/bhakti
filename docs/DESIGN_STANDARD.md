# Bhakti Design Standard

This is the maintained visual and interaction contract for the public library and song reader. It is derived from the approved homepage and song pages, not from a generic component system. New work must reuse this language before inventing another one.

## First principle: restraint

Bhakti is a reading and listening space, not a dashboard. The interface should recede until the listener asks for it.

- Prefer one quiet action over a visible action cluster.
- Reveal secondary operations in place and only on request.
- Preserve negative space, centered reading, and the existing text hierarchy.
- If an existing control shape, disclosure pattern, or typographic role can express the action, reuse it.
- A feature is not entitled to permanent chrome merely because it has multiple capabilities.

## Palette

The public surface has one ground and one ink:

- ground: `#6b0e16` (`--paper`, `--kh-bg`);
- ink: `#f4ead0` (`--ink`, `--kh-ink`);
- secondary information and hairlines are cream at reduced opacity.

The authoritative tokens are in `assets/site.css:1-7` and `assets/song.css:6-18`.

Rules:

- Do not introduce another red, accent color, gradient, or elevated card color for primary UI.
- Use opacity, space, type size, and a one-pixel cream rule for hierarchy.
- Do not add shadows to navigation, players, playlists, or persistent feature surfaces.
- A darker red or shadow is reserved for a tiny transient explanatory surface that must separate from text, such as the established word tooltip. It is not a general component style.

## Typography

There are three roles:

1. `Inter`: controls, labels, metadata, counts, and utility text.
2. `Cormorant Garamond`: devotional display text and literary English.
3. `EB Garamond`: IAST and catalogue/song titles where complete Latin Extended coverage matters.

See `assets/site.css:49-97`, `assets/site.css:328-339`, and `assets/song.css:14-18,148-190,436-461`.

Rules:

- Do not add another font family.
- Use weight and opacity sparingly; large devotional text is normally weight 400–500.
- Small UI labels may use uppercase or letter spacing, but public reading text should not.
- Titles and lyrics lead. Interface copy must not compete with them in size or weight.

## Layout and rhythm

- Library content uses the established centered 940px maximum; reader content uses the established centered reading column and responsive reader widths.
- Major regions are separated by space first, hairlines second, containers last.
- Repeated content is a calm vertical rhythm, not a grid of cards.
- Responsive work changes scale and available measure; it does not invent a different product on each device.

The current measures and breakpoints live in `assets/site.css:26-39,365-408` and `assets/song.css:27-34,546-658`.

## Controls and icons

- Reuse the established circular family: 34px desktop, 36px mobile, 42px tablet/monitor, and the existing TV scale.
- Primary touch targets must reach 44px through their visible size or an invisible hit area.
- Icons use a 24×24 coordinate system, `currentColor`, 1.6px stroke, round caps, and round joins unless they are filled Play/Pause transport glyphs.
- State changes should swap matched glyphs without moving or resizing the control.
- Keep controls in stable positions. Change their meaning/icon when the view changes rather than moving the control to another edge.

The persistent player stays outside the animated page stage. Anchor it from the
measured visible viewport bounds and its own rendered height; do not animate its vertical position
or let playlist transforms replace that anchor. Playlist and status placement use
the same viewport edge. Refresh bounds on viewport resize/pan and page restoration;
retain browser-tab magnification during pinch zoom (installed mobile PWAs use
the fixed-scale policy below). Cap the playlist below the top
safe area and above the player. Preserve safe-area padding, the existing audio node and
reading position through rotation; do not correct viewport bugs with guessed
keyboard offsets or forced scrolling. Verify portrait → landscape → portrait
both during playback and with the playlist open.

The shared player symbols are in `assets/player-icons.svg`; established control geometry is in `assets/song.css:36-99,304-380`.

## Control states and input methods

A highlight must describe a current state, never merely the last thing touched.
The same control family uses the same state rules in the library, reader and playlist.

| State | Appearance and lifetime |
| --- | --- |
| Resting | Existing quiet cream icon/hairline; transparent or ground-colored surface. |
| Hover | Subtle cream feedback only under `(hover: hover) and (pointer: fine)`. Apply this to parent-row hover and pseudo-elements too. Screen width does not identify an input device. |
| Pressed | Brief `:active` opacity or scale feedback while held; no layout movement, latched fill or delayed reset. Disabled controls never get this feedback. |
| Keyboard focus | A visible cream outline/edge independent of hover and selection, using `:focus-visible`. Keep DOM focus and native keyboard activation; never blur buttons to hide touch styling. |
| Selected | Persistent only while backed by actual state: filter `aria-pressed`, lyric-following state, linked word selection or current lyric. A selected tag remains selected after a tap. |
| Expanded | The disclosure trigger remains identifiable only while its region is open; closing removes that state even if the trigger still has focus. Keyboard focus may remain visible. |
| Playing / loading | Matched Play/Pause glyphs and truthful accessible action/busy labels follow the media controller. A command does not acquire a selected fill merely because it ran. |
| Disabled | Muted, non-actionable, excluded from hover/press decoration; native `disabled` where applicable. |

Pointer hover and keyboard focus are independent. Shared selector groups must not
accidentally put focus or real selection inside a hover-only media query. Avoid
sticky touch hover in JavaScript previews too: touch contact is not hover, including
on a device with a trackpad. Explicit tap/click remains the path to a selected meaning.
Suppress the browser's colored tap flash only on controls that supply their own
pressed/focus feedback. Small invisible hit areas must not overlap or be clipped.

### Transient surfaces and feedback

- Word meanings keep linked text highlighted exactly while the meaning is selected
  or previewed. Dismissal clears the popup, all linked highlights and its selection
  together; scrolling must not leave an invisible selection that takes two taps to reopen.
- Escape, outside interaction and leaving the page clear transient state. Reposition
  or dismiss on resize. Scrolling inside a scrollable meaning preserves that meaning;
  scrolling the surrounding page dismisses it.
- Preserve real filter/playlist state across navigation; do not preserve open menus
  or orphaned word highlights in cached pages.
- Action feedback is short, does not move content, and does not cover the control
  needed next. Empty and failure states explain a useful next action in plain language.
- Titles wrap, icon labels describe actions, and focus remains visible after
  rerender/removal. Disabled boundaries, empty queues and unavailable audio must stay
  understandable without relying on color alone.

## Disclosure

The default state shows only what is necessary for reading or the current playback action.

- Prefer one toggle that both opens and closes a disclosed region.
- Do not add a second close button when the initiating toggle remains visible.
- Do not add a title that merely repeats what the initiating icon already communicates.
- Prefer an integrated continuation of the page over a modal, drawer, floating card, dimmed backdrop, or toolbar.
- Small secondary actions belong in a small anchored popover. They must not expand the catalogue row or displace adjacent songs. This is an explicit exception to the preference for in-page disclosure: two contextual commands need a transient menu, not another page section.
- Catalogue rows get one quiet ellipsis, opening a two-action “Play next” / “Add to end” popover. Use the existing ground, cream hairline, small Inter labels and matched SVG icons; no title, backdrop, extra close button or shadow. Keep the menu inside the viewport and above the player; dismiss on outside click, Escape, focus leaving, scroll, navigation or action. Support arrow keys and restore focus appropriately. Tap/click remains sufficient; holding a song is not required.
- The compact, labeled Filter control shares the search row. Opening it reveals only four closely stacked, horizontally scrolling tag rows. Use “All subjects”, “All languages”, “All poets” and “All singers” reset tags to explain each row; no separate headings, accordion arrow, full-width disclosure bar or section spacing. Preserve selection, horizontal scroll and focus. Indicate active filtering on the control even when collapsed.
- Song tags remain quiet inline metadata. Previous, current and upcoming playlist occurrences stay together in order. Highlight the current row and expose `aria-current` without a visible “Current” label. Earlier and upcoming rows both offer Play and Remove in the same positions. Removing an earlier occurrence preserves the current occurrence and audio position. Clearing upcoming songs preserves current audio and prior entries.
- One circular repeat control stays in the player, beside the playlist toggle, including for a single song. Successive clicks cycle off → song → playlist → off. Use matched repeat arrows with a small central `1` for song repeat, a quiet selected fill for either enabled mode, and brief existing status feedback naming the mode. Accessible labels give the state and next action. Do not add a menu or another permanent label.
- Repeat belongs to the listening session and survives navigation and reload, but is not imposed on recipients of a shared playlist. Song repeat restarts the same occurrence at zero on natural completion; playlist repeat wraps the retained order to its first occurrence without growing or reshuffling it. Explicit Next bypasses song repeat and wraps only in playlist repeat. Failed media always advances forward without wrapping, so an unavailable playlist cannot loop indefinitely. A new shuffle session starts with repeat off.

### Choosing the right surface

Keep the established devotional typography, dedication, reading column and player
geometry as the baseline. A filter changes the catalogue and belongs beside
search; its choices may reveal compactly below it. An action on one song belongs
next to that song and floats temporarily without changing the list's geometry.
The full playlist is a listening view and keeps its existing responsive sheet /
right-panel behavior. Do not apply one disclosure pattern to all three simply
because it is easy to implement. Check both the closed and open compositions,
including the space occupied and whether the song titles remain dominant.

## Motion

Motion explains spatial relationships and then gets out of the way.

- Song → Library: Song exits right; Library enters from the left.
- Library → Song: Library exits left; Song enters from the right.
- Playlist reveal: on mobile and tablet, the playlist rises above the fixed player and temporarily owns the interaction. On desktop and TV, a non-modal content-width playlist enters from the right while the reading view pans left into the remaining space; the fixed player and song remain scrollable and interactive.
- During horizontal song or desktop-playlist transitions, the three lyric layers may use differential offsets no larger than 18px; Romanization travels farthest and settles first, while source and English remain quieter.
- Use `transform` (and opacity only when necessary), not per-frame width, height, margin, or positional layout animation.
- Target duration is 200–220ms with a restrained ease curve.
- `prefers-reduced-motion: reduce` must produce an immediate, complete state change.

The current implementation is in `assets/app.css` under `.app-stage`, `.queue-sheet`, and the four `app-view-*` keyframes.

## Interaction and accessibility

- Repeated mobile taps must not zoom the public library or reader. Apply
  `touch-action: manipulation` at the shared document root, preserving normal
  scrolling and browser pinch zoom. Installed mobile PWAs use a fixed scale
  viewport, including on iOS versions that ignore the double-tap CSS policy.
  Retain viewport width and safe-area settings. Do not cancel touch events or
  synthesize clicks: transport, lyric taps and the hidden five-tap entry must
  keep receiving their ordinary input. Desktop zoom remains unchanged.
- Owner access is completely hidden on mobile and desktop: open About with `?`,
  then tap/click its unchanged heading five times, with no timing requirement.
  Do not render an owner label, link, button, counter, hint or confirmation surface.
  Other clicks, Escape, backgrounding and page restoration reset partial taps.
  Use completed clicks, never holding or pointer-down activation. Suppress text
  selection on that heading; apply the shared zoom policy above.
  Alt/Option+Shift+O outside editable fields is the hidden keyboard alternative.
  The direct owner URL remains usable. Passkey verification protects private data.
- Tap/click is authoritative. Swipe, pull, and drag may be accelerators but never the only path.
- Drag reorder must have a keyboard equivalent on the same handle.
- Focus must be visible, return predictably after disclosure closes, and never be lost during a rerender.
- Labels describe the action and state (`Show playlist, 8 songs`, `Unlink lyrics from playback`), even when the visible control is icon-only.
- Media controls reflect actual media events and fulfilled/rejected `play()` promises.
- Keep visible Back 10 seconds and Forward 10 seconds controls beside Play/Pause.
  They preserve playback/paused state, clamp to the recording boundaries, and
  disable when duration is unknown. On mobile, place progress and elapsed/total
  time on one row above the stable transport controls so the scrubber and touch
  targets remain usable. Playlist Previous/Next retain their distinct track actions.
- Expose the same transport through system media controls: evidenced song/credit,
  playback state, position, Play/Pause, available Previous/Next and seeking. The
  operating system chooses the displayed controls and may supply a seek interval;
  use ten seconds when it supplies none. Seeking preserves the paused state.
- The progress track is a keyboard-accessible slider with an elapsed/total label.
  Arrow keys seek ten seconds, Page Up/Down one minute, and Home/End the boundaries.
  Unknown duration disables seeking. A buffering request can be cancelled; an
  explicit Play can retry unavailable audio without creating an automatic retry loop.
- Service-worker updates must not reload a document that has started listening,
  including while paused or backgrounded. Adopt the new document on a later normal
  load; an idle page may still update automatically.
- No destructive action is gesture-only.
- In a three-column Sanskrit name table, the visible English cell is already
  the meaning and must not be repeated in a tooltip. Devanāgarī and IAST may
  disclose one concise analysis line (members/root plus morphology); the
  English cell remains linked for bidirectional highlighting but opens no
  redundant hover surface. Ordinary lyric word tooltips remain meaning-only.

## Responsive acceptance

Every material UI change is checked in the Codex in-app Browser at:

- 390px mobile;
- tablet;
- desktop computer;
- TV / very large display.

At each size verify no horizontal overflow, readable measure, safe-area clearance,
reachable controls, stable player geometry, complete keyboard access, and the actual
transition—not only the final state. Also check long titles, expanded filters,
menus beside viewport/player edges, queue boundaries, empty search and failed media.

Input acceptance is separate from viewport acceptance. Exercise tap → release →
repeat, open → close while the trigger keeps focus, mouse enter → leave, Tab / Shift+Tab,
Enter / Space, Escape, scroll, resize and Back/Forward. Verify real selected states
persist while transient feedback clears. A narrow desktop browser is a layout test,
not proof of phone input behavior; record any unavailable device/input checks.
Check reduced motion, text enlargement, portrait/landscape and safe areas when the
available device supports them; do not claim an emulation the tools cannot perform.

## Anti-patterns

Reject a design that introduces any of these without an explicit revision to this standard:

- a second red or accent color;
- shadows on persistent feature surfaces;
- a dashboard, sidebar, or card grid for listening controls;
- multiple visible controls where one disclosed control is sufficient;
- headings, dividers, and close buttons that repeat an already-visible toggle;
- unrelated playlist paradigms beyond the approved bottom-sheet-to-right-panel responsive adaptation;
- moving player controls between slots across views;
- drag-only, hover-only, or swipe-only functionality;
- long or layout-triggering animations;
- UI copy that explains implementation metadata rather than helping the listener.

## Review gate

Before release, answer yes to all of these:

1. Does this reuse the one-ground/one-ink palette and existing type roles?
2. Is every permanently visible control necessary in the default state?
3. Did we reuse an established control shape and icon weight?
4. Is secondary functionality disclosed locally rather than presented as another surface?
5. Does motion clarify where the listener went, stay under 220ms, and reduce cleanly?
6. Are touch, keyboard, focus, media failure, and all four display classes verified?
7. Does the result still feel primarily like lyrics and listening rather than software controls?
