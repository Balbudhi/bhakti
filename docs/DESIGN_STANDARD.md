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

The shared player symbols are in `assets/player-icons.svg`; established control geometry is in `assets/song.css:36-99,304-380`.

## Disclosure

The default state shows only what is necessary for reading or the current playback action.

- Prefer one toggle that both opens and closes a disclosed region.
- Do not add a second close button when the initiating toggle remains visible.
- Do not add a title that merely repeats what the initiating icon already communicates.
- Prefer an integrated continuation of the page over a modal, drawer, floating card, dimmed backdrop, or toolbar.
- Secondary actions may expand inline behind one quiet ellipsis; they must not become a permanently visible action bar.
- Catalogue rows get one small add-to-playlist control. Opening the row remains the path to the song; playlist order supplies “next.”

## Motion

Motion explains spatial relationships and then gets out of the way.

- Song → Library: Song exits right; Library enters from the left.
- Library → Song: Library exits left; Song enters from the right.
- Playlist reveal: the current view and fixed player lift together, exposing the playlist below.
- Use `transform` (and opacity only when necessary), not per-frame width, height, margin, or positional layout animation.
- Target duration is 200–220ms with a restrained ease curve.
- `prefers-reduced-motion: reduce` must produce an immediate, complete state change.

The current implementation is in `assets/app.css` under `.app-stage`, `.queue-sheet`, and the four `app-view-*` keyframes.

## Interaction and accessibility

- Tap/click is authoritative. Swipe, pull, and drag may be accelerators but never the only path.
- Drag reorder must have a keyboard equivalent on the same handle.
- Focus must be visible, return predictably after disclosure closes, and never be lost during a rerender.
- Labels describe the action and state (`Show playlist, 8 songs`, `Unlink lyrics from playback`), even when the visible control is icon-only.
- Media controls reflect actual media events and fulfilled/rejected `play()` promises.
- No destructive action is gesture-only.

## Responsive acceptance

Every material UI change is checked in the Codex in-app Browser at:

- 390px mobile;
- tablet;
- desktop computer;
- TV / very large display.

At each size verify no horizontal overflow, readable measure, safe-area clearance, reachable controls, stable player geometry, complete keyboard access, and the actual transition—not only the final state.

## Anti-patterns

Reject a design that introduces any of these without an explicit revision to this standard:

- a second red or accent color;
- shadows on persistent feature surfaces;
- a dashboard, sidebar, or card grid for listening controls;
- multiple visible controls where one disclosed control is sufficient;
- headings, dividers, and close buttons that repeat an already-visible toggle;
- a different playlist paradigm at each breakpoint;
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
