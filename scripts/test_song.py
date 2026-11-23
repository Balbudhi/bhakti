#!/usr/bin/env python3
"""song.txt is read exactly, mistakes are named, and duplicates are recognised."""
import tempfile
import unittest
from pathlib import Path

import song

GOOD = """title: Śiva Nāma
writer: Purandaradāsa
singer: Asha Rao & Uma Rao
composer: Uma Rao
languages: Sanskrit
subjects: Śiva
aliases: Shiva Nama

[r-1 refrain]
śiva | Śiva, the auspicious one | शिव
+nāma | name | नाम
japa | chant; second person imperative | जप
en: {2:Chant }{1:the name }{0:of Śiva.}
note: A compound: the name of Śiva.

order: r-1*2
"""


class SongText(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.original, song.WORK = song.WORK, Path(self.folder.name)
        self.addCleanup(lambda: setattr(song, "WORK", self.original))

    def compile(self, text):
        (song.WORK / "x").mkdir(exist_ok=True)
        (song.WORK / "x" / "song.txt").write_text(text)
        return song.compile_song("x")

    def rejected(self, text):
        with self.assertRaises(SystemExit) as stop:
            self.compile(text)
        return str(stop.exception)

    def test_good(self):
        meta, lines, order = self.compile(GOOD)
        line = lines["r-1"]
        self.assertEqual((line["source"], line["roman"], line["sourceLanguage"]), ("शिवनाम जप", "śivanāma japa", "sa"))
        self.assertEqual([w["roman"] for w in line["words"]], ["śiva", "nāma", "japa"])
        self.assertEqual([m["text"] for m in line["sourceWords"]], ["शिव", "नाम", "जप"])
        self.assertEqual(order, [{"ref": "r-1", "section": "refrain", "repeats": 2}])
        self.assertEqual(meta["credit"], "Purandaradāsa · Asha Rao & Uma Rao")
        self.assertIn("Siva", meta["searchAliases"])

    def test_mistakes_are_named(self):
        self.assertIn("leaves out 1 nāma", self.rejected(GOOD.replace("{1:the name }", "")))
        self.assertIn("text outside", self.rejected(GOOD.replace("{2:Chant }", "Chant {2:}")))
        self.assertIn("no meaning", self.rejected(GOOD.replace("| name |", "|  |")))
        self.assertIn("no line r-2", self.rejected(GOOD.replace("order: r-1*2", "order: r-1 r-2")))
        self.assertIn("never sung", self.rejected(GOOD.replace("order:", GOOD[GOOD.index("[r-1"):GOOD.index("order")]
                                                               .replace("r-1", "r-3") + "\norder:")))
        self.assertIn("Traditional", self.rejected(GOOD.replace("Purandaradāsa", "Traditional")))
        self.assertIn("not understood", self.rejected(GOOD.replace("japa | chant; second person imperative | जप", "japa chant")))

    def test_whole_line_links_are_refused(self):
        wide = GOOD.replace("japa |", "bho | O | भो\njapa |").replace("{2:Chant }{1:the name }{0:of Śiva.}", "{0,1,2,3:Chant.}")
        self.assertIn("word by word", self.rejected(wide))

    def test_duplicates(self):
        songs = [("a", {song.fold("Yeh Garv Bhara")}, {288.0}), ("b", {song.fold("Rudrashtakam")}, {600.0})]
        self.assertEqual(song.closest("Ye Garv Bhara", 287.0, songs), ("a", "recording"))
        self.assertEqual(song.closest("Rudraashtakam", 385.0, songs), ("b", "text"))
        self.assertEqual(song.closest("Madhurashtakam", 481.0, songs)[1], None)


if __name__ == "__main__":
    unittest.main()
