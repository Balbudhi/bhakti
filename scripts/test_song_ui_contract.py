#!/usr/bin/env python3
"""Static contract checks for every generated song shell."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SongUiContractTests(unittest.TestCase):
    def test_every_song_shell_has_one_pwa_and_reader_control_set(self) -> None:
        pages = sorted((ROOT / "songs").glob("*/index.html"))
        self.assertGreater(len(pages), 0)
        for path in pages:
            text = path.read_text(encoding="utf-8")
            with self.subTest(song=path.parent.name):
                self.assertEqual(text.count('name="theme-color"'), 1)
                self.assertEqual(text.count('rel="icon"'), 1)
                self.assertEqual(text.count('rel="apple-touch-icon"'), 1)
                self.assertEqual(text.count('rel="manifest"'), 1)
                self.assertEqual(text.count('class="song-home app-view-toggle"'), 1)
                self.assertEqual(text.count('id="appViewToggle"'), 1)
                self.assertEqual(text.count('id="apTime"'), 1)
                self.assertEqual(text.count('id="apElapsed"'), 1)
                self.assertEqual(text.count('id="apDuration"'), 1)
                self.assertRegex(text, r'song\.js\?v=contract-\d{8}-\d+')
                self.assertRegex(text, r'data\.js\?v=contract-\d{8}-\d+')
                self.assertRegex(text, r'pwa\.js\?v=contract-\d{8}-\d+')
                self.assertRegex(text, r'song\.css\?v=contract-\d{8}-\d+')
                self.assertEqual(text.count('id="songShare"'), 1)
                self.assertEqual(text.count('id="songSync"'), 1)
                self.assertEqual(text.count('player-icons.svg#icon-lock'), 1)
                self.assertEqual(text.count('player-icons.svg#icon-unlock'), 1)
                self.assertEqual(text.count('player-icons.svg#icon-home'), 1)
                self.assertEqual(text.count('player-icons.svg#icon-music'), 1)
                self.assertEqual(text.count('assets/queue.js'), 1)
                self.assertEqual(text.count('assets/app.js'), 1)
                self.assertEqual(text.count('assets/app.css'), 1)
                self.assertIn('family=EB+Garamond:wght@400;500', text)
                self.assertIn('name="apple-mobile-web-app-capable" content="yes"', text)
                self.assertEqual(text.count('class="song-meta"'), 1)
                self.assertNotIn('class="song-attrib"', text)
                self.assertNotIn('class="song-credit"', text)

    def test_seeking_is_bound_to_the_dedicated_control(self) -> None:
        script = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        self.assertIn('class="line-seek"', script)
        self.assertIn('const seekButton = event.target.closest?.(".line-seek")', script)
        self.assertIn('if (!seekButton) return;', script)
        self.assertIn('const elapsed = document.getElementById("apElapsed")', script)
        self.assertIn('const duration = document.getElementById("apDuration")', script)

    def test_song_controls_use_native_sharing_and_persistent_lyric_following(self) -> None:
        script = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        self.assertIn('LYRICS_FOLLOW_STORAGE_KEY = "bhakti:lyrics-follow-playback"', script)
        self.assertIn('localStorage.getItem(LYRICS_FOLLOW_STORAGE_KEY)', script)
        self.assertIn('localStorage.setItem(LYRICS_FOLLOW_STORAGE_KEY', script)
        self.assertIn('navigator.share({ title: document.title, url })', script)
        self.assertIn('navigator.clipboard?.writeText', script)
        self.assertIn('"Link copied"', script)
        self.assertIn('"bhakti:lyrics-follow-change"', script)
        self.assertIn('if (lyricsFollowPlayback)', script)

    def test_edition_selector_is_compact_and_persistent(self) -> None:
        script = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        data = (ROOT / "songs" / "hanuman-chalisa" / "data.js").read_text(encoding="utf-8")
        self.assertIn('class="edition-select"', script)
        self.assertIn('localStorage.setItem(`bhakti:text-edition:${location.pathname}`', script)
        self.assertNotIn("renderEditionNote", script)
        self.assertNotIn('class="edition-note"', script)
        self.assertIn('"editionNote"', data)
        self.assertIn('"label": "Common reading"', data)
        self.assertIn('"label": "Rāmabhadrācārya edition"', data)

    def test_homepage_preface_and_disclosure_follow_the_ui_contract(self) -> None:
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "assets" / "library.js").read_text(encoding="utf-8")
        self.assertIn('class="library-invocation-roman"', page)
        self.assertIn('class="preface-source preface-token"', page)
        self.assertIn('class="preface-word preface-token"', page)
        self.assertIn('preface-meaning preface-token', page)
        self.assertIn('>गायन-वादन</span>', page)
        self.assertIn('>कोटि-कोटि</span>', page)
        self.assertIn('>प्रणाम</span>।', page)
        self.assertIn('Countless</span>', page)
        self.assertIn('class="about-toggle"', page)
        self.assertIn('id="shuffleVisible"', page)
        self.assertIn('id="appViewToggle"', page)
        self.assertIn('id="songAudio"', page)
        self.assertIn('assets/queue.js', page)
        self.assertIn('assets/app.js', page)
        self.assertIn('AI-based transcription, timing, and translation pipeline', page)
        self.assertIn('<h2 id="aboutHeading">About these songs</h2>', page)
        self.assertIn('<p>These pages are produced by an AI-based transcription, timing, and translation pipeline.</p>', page)
        self.assertNotIn('please forgive', page.casefold())
        self.assertNotIn('corrections are welcome', page.casefold())
        self.assertIn('song.singer || song.credit', script)
        self.assertIn('song.singer || song.credit ? `<span class="credit">', script)
        self.assertIn('"all-subjects"', script)
        self.assertIn('"all-languages"', script)

    def test_credit_roles_pluralize_for_named_collaborators(self) -> None:
        script = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        pipeline = (ROOT / "scripts" / "bhakti_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('(?:&|and)', script)
        self.assertIn('`${role}s`', script)
        self.assertIn('["vocalist", "Vocalist"]', script)
        self.assertIn('["ensemble", "Recital"]', script)
        self.assertIn('def display_roles(', pipeline)

    def test_every_text_layer_uses_the_same_interactive_word_mapping(self) -> None:
        script = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        self.assertIn('linkedWord("ws"', script)
        self.assertIn('linkedWord("w"', script)
        self.assertIn('linkedWord("we"', script)
        self.assertIn('e.target.closest(".word-link")', script)
        self.assertIn('matchMedia?.("(hover: hover) and (pointer: fine)")', script)
        self.assertIn('if (hasRealHover)', script)

    def test_pwa_checks_for_releases_without_reloading_every_launch(self) -> None:
        client = (ROOT / "assets" / "pwa.js").read_text(encoding="utf-8")
        worker = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn('updateViaCache: "none"', client)
        self.assertIn('navigator.serviceWorker.addEventListener("controllerchange"', client)
        self.assertIn('now - lastCheck < 5 * 60 * 1000', client)
        self.assertIn('audioIsPlaying()', client)
        self.assertIn('fetch(event.request, { cache: "no-store" })', worker)
        self.assertIn('event.request.mode === "navigate"', worker)
        self.assertIn('cache.put(cacheKey, copy)', worker)
        self.assertIn('caches.match(cacheKey)', worker)
        self.assertIn('bhakti-shell-v18', worker)
        self.assertIn('/assets/queue.js', worker)
        self.assertIn('/assets/app.js', worker)

    def test_iast_uses_the_extended_garamond_face(self) -> None:
        song_css = (ROOT / "assets" / "song.css").read_text(encoding="utf-8")
        site_css = (ROOT / "assets" / "site.css").read_text(encoding="utf-8")
        self.assertIn('--kh-iast-serif: "EB Garamond"', song_css)
        self.assertIn('font-family: var(--kh-iast-serif)', song_css)
        self.assertIn('"EB Garamond", "Cormorant Garamond"', site_css)
        self.assertIn('overflow-wrap: anywhere', song_css)

    def test_top_controls_use_matched_lock_states_and_shared_player_icons(self) -> None:
        song_css = (ROOT / "assets" / "song.css").read_text(encoding="utf-8")
        pipeline = (ROOT / "scripts" / "bhakti_pipeline.py").read_text(encoding="utf-8")
        icons = (ROOT / "assets" / "player-icons.svg").read_text(encoding="utf-8")
        self.assertIn('background-color: var(--kh-bg);', song_css)
        self.assertIn('opacity: 1;', song_css)
        self.assertIn('top: max(8px, calc(env(safe-area-inset-top) - 16px));', song_css)
        self.assertIn('sync-icon-unlock', song_css)
        self.assertIn('player-icons.svg#icon-lock', pipeline)
        self.assertIn('player-icons.svg#icon-unlock', pipeline)
        for symbol in ('icon-lock', 'icon-unlock', 'icon-home', 'icon-music'):
            self.assertEqual(icons.count(f'id="{symbol}"'), 1)
        self.assertEqual(icons.count('stroke-width="1.6"'), 4)

    def test_catalogue_is_queue_ready_and_collision_free(self) -> None:
        import json
        import subprocess
        script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window.BHAKTI_SONGS));"
        raw = subprocess.run(
            ["node", "-e", script, str(ROOT / "data" / "songs.js")],
            check=True, text=True, capture_output=True,
        ).stdout
        songs = json.loads(raw)
        self.assertGreater(len(songs), 0)
        self.assertEqual(len({song["queueId"] for song in songs}), len(songs))
        for song in songs:
            self.assertRegex(song["queueId"], r"^[0-9a-f]{8}$")
            self.assertGreater(len(song["audioSources"]), 0)
            self.assertTrue(all(source.get("src") and source.get("type") for source in song["audioSources"]))

    def test_playlist_reveals_as_an_integrated_same_palette_region(self) -> None:
        app = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "assets" / "app.css").read_text(encoding="utf-8")
        queue = (ROOT / "assets" / "queue.js").read_text(encoding="utf-8")
        self.assertIn('queueSheet.setAttribute("role", "region")', app)
        self.assertIn('document.body.classList.add("queue-open")', app)
        self.assertIn('Queue.reorderUpcoming(queueState, orderedEntryIds)', app)
        self.assertIn('if (queueIsVisible(queueState)) url.searchParams.set("queue", Queue.encode(queueState))', app)
        self.assertIn('data-queue-drag=', app)
        self.assertIn('event.target.closest?.("[data-queue-drag]")', app)
        self.assertIn("const animateQueueReorder", app)
        self.assertIn("Math.abs(event.clientY - dragStartY) < 6", app)
        self.assertIn('body.queue-open .app-stage', css)
        self.assertIn('body.queue-open .audio-player', css)
        self.assertIn('@keyframes app-view-in-left', css)
        self.assertIn('@keyframes app-view-out-right', css)
        self.assertIn('@keyframes app-view-in-right', css)
        self.assertIn('@keyframes app-view-out-left', css)
        self.assertIn('background: var(--kh-bg, #6b0e16);', css)
        self.assertNotIn("box-shadow", css)
        self.assertNotIn("#5c0c13", css)
        self.assertNotIn("app-backdrop", app)
        self.assertNotIn("song-actions-menu", app)
        self.assertNotIn('aria-modal', app)
        self.assertNotIn('queue-sheet-header', app)
        self.assertNotIn('queue-sheet-footer', app)
        self.assertNotIn('queue-remove"', app)
        self.assertIn('bhakti:add-to-queue', app)
        self.assertNotIn('data-queue-action="tools"', app)
        for action in ("queue-play", "shuffle", "clear"):
            self.assertIn(f'data-queue-action="{action}"', app)
        self.assertNotIn('data-queue-action="share"', app)
        self.assertIn("player.append(queuePill)", app)
        self.assertNotIn("queue-inline-tools", app)
        self.assertIn(".queue-sheet-tools", css)
        self.assertIn("bottom: 0;", css)
        self.assertIn("queue-row-actions", app)
        self.assertIn("queue-row-remove", app)
        self.assertNotIn("queue-song-select", app)
        self.assertIn('data-queue-action="remove"', app)
        self.assertIn("queuePill.title", app)
        self.assertIn('role="group" aria-label="Playlist actions"', app)
        self.assertIn('event.target.closest("[data-queue-action]")', app)
        self.assertIn('handle || event.pointerType === "mouse"', app)
        self.assertIn('queueSheet.contains(event.target) || player.contains(event.target)', app)
        self.assertIn('event.stopPropagation();', app)
        self.assertIn("const reorderUpcoming", queue)

    def test_touch_words_do_not_inherit_hover_or_stale_focus_highlights(self) -> None:
        reader = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        css = (ROOT / "assets" / "song.css").read_text(encoding="utf-8")
        self.assertIn('root.addEventListener("pointerdown"', reader)
        self.assertIn('if (stickyWord) { deactivate(stickyWord); stickyWord = null; }', reader)
        self.assertIn('if (!w || !keyboardFocus) return;', reader)
        self.assertIn("@media (hover: hover) and (pointer: fine)", css)

    def test_design_standard_is_part_of_repository_authority(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        standard = (ROOT / "docs" / "DESIGN_STANDARD.md").read_text(encoding="utf-8")
        self.assertIn("docs/DESIGN_STANDARD.md", agents)
        self.assertIn("docs/DESIGN_STANDARD.md", readme)
        for heading in ("## Palette", "## Controls and icons", "## Motion", "## Anti-patterns"):
            self.assertIn(heading, standard)

    def test_mobile_player_stays_compact_and_integrates_the_queue_toggle(self) -> None:
        song_css = (ROOT / "assets" / "song.css").read_text(encoding="utf-8")
        app = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn("left: 0;\n  right: 0;\n  bottom: 0;", song_css)
        self.assertIn("padding: 10px 28px max(10px, env(safe-area-inset-bottom));", song_css)
        self.assertIn("padding: 10px 18px max(10px, env(safe-area-inset-bottom));", song_css)
        self.assertIn("player.append(queuePill)", app)

    def test_hosted_intake_is_owner_only_and_public_media_only(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "run-bhakti-intake.yml").read_text(encoding="utf-8")
        self.assertIn("if: github.actor == github.repository_owner", workflow)
        self.assertIn('if len(lines) > 50:', workflow)
        self.assertIn('parsed.scheme != "https"', workflow)
        self.assertIn('ipaddress.ip_address', workflow)
        self.assertIn('.is_global', workflow)
        self.assertIn('parsed.username or parsed.password', workflow)
        self.assertIn("BHAKTI_GEMINI_PROVIDER: openrouter", workflow)
        self.assertIn("scripts/publish_media_release.py", workflow)
        self.assertIn('default: "economy"', workflow)
        self.assertIn('command.append("--economy")', workflow)
        self.assertIn('BHAKTI_API_MAX_CONCURRENCY: "4"', workflow)
        self.assertIn('path in {"data/media.json", "data/songs.js"}', workflow)
        self.assertNotIn('"audio.m4a", "audio.mp3"', workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("repository_dispatch:", workflow)

    def test_composite_liturgy_source_notices_are_supported(self) -> None:
        script = (ROOT / "assets" / "song.js").read_text(encoding="utf-8")
        data = (ROOT / "songs" / "kakad-aarti" / "data.js").read_text(encoding="utf-8")
        self.assertIn("function renderSourceNotice", script)
        self.assertIn("adaptedSequenceIndices", script)
        self.assertIn('"title": "Kākaḍ Āratī"', data)
        self.assertIn('"sectionNotices"', data)
        self.assertIn('>Sai adaptation</span>', script)

    def test_hari_om_sharan_language_tags_follow_the_sung_text(self) -> None:
        aisa = (ROOT / "songs" / "aisa-pyar-baha-de-maiya" / "data.js").read_text(encoding="utf-8")
        garv = (ROOT / "songs" / "yeh-garv-bhara-mastak" / "data.js").read_text(encoding="utf-8")
        self.assertIn('"languages": [\n    "Hindi",\n    "Sanskrit"', aisa)
        self.assertEqual(aisa.count('"sourceLanguage": "sa"'), 2)
        self.assertIn('"languages": [\n    "Hindi"', garv)
        self.assertNotIn('"Sanskrit"', garv)


if __name__ == "__main__":
    unittest.main()
