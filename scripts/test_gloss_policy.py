#!/usr/bin/env python3

import unittest

import gloss_policy


class GlossPolicyTests(unittest.TestCase):
    def test_fictional_coinages_are_rejected_but_adamantine_is_real_english(self) -> None:
        self.assertEqual(gloss_policy.fictional_coinages("an adamantium body"), ["adamantium"])
        self.assertEqual(gloss_policy.fictional_coinages("adamantine claws"), [])

    def test_preserved_concept_explains_without_repeating_itself(self) -> None:
        for concept_key in ("buddhi", ""):
            with self.subTest(concept_key=concept_key):
                self.assertEqual(
                    gloss_policy.meaning_only_gloss("buddhi", "buddhi (intellect, faculty of discernment)", concept_key),
                    "intellect; faculty of discernment",
                )

    def test_devotional_title_explains_without_repeating_itself(self) -> None:
        self.assertEqual(gloss_policy.meaning_only_gloss("guru", "Guru / spiritual teacher"), "spiritual teacher")
        self.assertEqual(gloss_policy.meaning_only_gloss("Bābā", "Baba, Father, Master"), "Father, Master")

    def test_reviewed_name_context_survives_word_cleaning(self) -> None:
        for roman, gloss, expected in (
            ("Nānak", "Nānak, the Gurūs’ shared poetic signature; here Gurū Arjan",
             "the Gurūs’ shared poetic signature; here Gurū Arjan"),
            ("Hari", "Hari, the Divine", "the Divine"),
            ("UnresolvedName", "UnresolvedName (the singer's companion)", "the singer's companion"),
        ):
            with self.subTest(roman=roman):
                original = {"roman": roman, "gloss": gloss, "preserve_in_english": False}
                cleaned = gloss_policy.clean_word(original)
                self.assertEqual(cleaned, {**original, "gloss": expected})
                self.assertEqual(original["gloss"], gloss)

    def test_placeholder_tail_is_not_a_contextual_explanation(self) -> None:
        with self.assertRaisesRegex(ValueError, "unresolved self-referential gloss"):
            gloss_policy.meaning_only_gloss("UnresolvedName", "UnresolvedName (proper name)")

    def test_curated_mainaka_identity_remains_authoritative(self) -> None:
        self.assertEqual(
            gloss_policy.meaning_only_gloss("Maināka", "Mainaka (golden mountain)"),
            "the mountain who rises from the sea to offer Hanumān rest",
        )

    def test_existing_meaning_first_gloss_is_preserved(self) -> None:
        self.assertEqual(gloss_policy.meaning_only_gloss("māyā", "worldly appearance and attachment"),
                         "worldly appearance and attachment")

    def test_epic_names_receive_context_instead_of_repetition(self) -> None:
        self.assertEqual(gloss_policy.meaning_only_gloss("laṅkā", "Lanka"), "island kingdom of Rāvaṇa")
        self.assertEqual(gloss_policy.meaning_only_gloss("holikā", "Holika fire"), "bonfire; destructive blaze")
        self.assertEqual(gloss_policy.meaning_only_gloss("hanumāna", "Hanuman"), "monkey-god; son of the Wind")
        self.assertEqual(gloss_policy.meaning_only_gloss("Śiva", "Shiva"),
                         "the auspicious one; deity of transformation and yogic asceticism")
        self.assertEqual(gloss_policy.meaning_only_gloss("Rāma", "Rama"),
                         "hero of the Rāmāyaṇa and Viṣṇu’s avatāra")
        self.assertEqual(gloss_policy.meaning_only_gloss("Surāsā", "Surasa"),
                         "serpent-mother who tests Hanumān on his journey")

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

    def test_unknown_name_blocks_publication_instead_of_emitting_a_placeholder(self) -> None:
        with self.assertRaisesRegex(ValueError, "unresolved self-referential gloss"):
            gloss_policy.meaning_only_gloss("UnresolvedName", "UnresolvedName")

    def test_relational_titles_remain_available_for_contextual_review(self) -> None:
        for roman, meaning in (
            ("pati", "lord; master in this address"),
            ("raghupati", "lord of Raghu's line"),
            ("girijāpati", "Girijā's husband"),
            ("patita", "fallen"),
            ("sampati", "wealth"),
        ):
            with self.subTest(roman=roman):
                self.assertEqual(gloss_policy.meaning_only_gloss(roman, meaning), meaning)


if __name__ == "__main__":
    unittest.main()
