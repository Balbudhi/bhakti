"""Dictionary retrieval must not silently decide language, morphology or sense."""
import unittest
import bhakti_translation_policy as policy


class DictionaryCandidateTests(unittest.TestCase):
    def test_exact_hindi_source_retrieves_all_candidates_without_selecting(self):
        rows = policy.dictionary_candidates([{"source_text": "मन हार"}], ["Hindi"])
        self.assertEqual([row["lemma"] for row in rows], ["man", "hār"])
        senses = {sense["sense_id"] for row in rows for sense in row["senses"]}
        self.assertTrue({"hi.har.garland", "hi.har.defeat"}.issubset(senses))
        self.assertTrue(all(sense["selection_status"] == "unselected" for row in rows for sense in row["senses"]))

    def test_no_unknown_or_cross_language_inference(self):
        for languages in (None, [], ["Punjabi"], ["Sanskrit"], ["Hindi", "Punjabi"]):
            self.assertEqual(policy.dictionary_candidates([{"roman": "man hār"}], languages), [])

    def test_no_substrings_or_diacritic_folding(self):
        self.assertEqual(policy.dictionary_candidates([{"roman": "har karan-hār manas"}], ["Hindi"]), [])
        self.assertEqual(len(policy.dictionary_candidates([{"roman": "hār,"}], ["Hindi"])), 1)

    def test_policy_preserves_human_english_and_requires_contextual_choice(self):
        text = policy.guidance([], [])
        self.assertIn("Preserve explicitly supplied/owner-approved English exactly", text)
        self.assertIn("primary word gloss is that chosen", text)
        self.assertIn("Translate ordinary words and philosophical concepts", text)
        self.assertIn("Keep\ngenuine proper names", text)


if __name__ == "__main__":
    unittest.main()
