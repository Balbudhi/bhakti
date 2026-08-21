#!/usr/bin/env python3

import unittest

import gloss_policy


class GlossPolicyTests(unittest.TestCase):
    def test_fictional_coinages_are_rejected_but_adamantine_is_real_english(self) -> None:
        self.assertEqual(gloss_policy.fictional_coinages("an adamantium body"), ["adamantium"])
        self.assertEqual(gloss_policy.fictional_coinages("adamantine claws"), [])

    def test_preserved_concept_explains_without_repeating_itself(self) -> None:
        self.assertEqual(
            gloss_policy.meaning_only_gloss("buddhi", "buddhi (intellect, faculty of discernment)", "buddhi"),
            "intellect; faculty of discernment",
        )

    def test_devotional_title_explains_without_repeating_itself(self) -> None:
        self.assertEqual(gloss_policy.meaning_only_gloss("guru", "Guru / spiritual teacher"), "spiritual teacher")
        self.assertEqual(gloss_policy.meaning_only_gloss("Bābā", "Baba, Father, Master"), "father; revered master")

    def test_existing_meaning_first_gloss_is_preserved(self) -> None:
        self.assertEqual(gloss_policy.meaning_only_gloss("māyā", "worldly appearance and attachment"),
                         "worldly appearance and attachment")

    def test_epic_names_receive_context_instead_of_repetition(self) -> None:
        self.assertEqual(gloss_policy.meaning_only_gloss("laṅkā", "Lanka"), "island kingdom of Rāvaṇa")
        self.assertEqual(gloss_policy.meaning_only_gloss("holikā", "Holika fire"), "bonfire; destructive blaze")
        self.assertEqual(gloss_policy.meaning_only_gloss("hanumāna", "Hanuman"), "monkey-god; son of the Wind")

    def test_self_reference_detection_ignores_diacritics_and_punctuation(self) -> None:
        self.assertTrue(gloss_policy.is_self_referential("buddhi,", "buddhi (intellect)"))
        self.assertTrue(gloss_policy.is_self_referential("Sāī̃", "Sai"))
        self.assertTrue(gloss_policy.is_self_referential("Sāīṃ", "Sai"))

    def test_divine_compound_never_falls_back_to_an_unexplained_spelling(self) -> None:
        self.assertTrue(gloss_policy.is_self_referential("śivaśaṅkara", "Shiva-Shankara"))
        self.assertEqual(
            gloss_policy.meaning_only_gloss("śivaśaṅkara", "Shiva-Shankara"),
            "Śiva as the auspicious maker of good",
        )


if __name__ == "__main__":
    unittest.main()
