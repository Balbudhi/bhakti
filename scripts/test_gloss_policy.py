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
                    "intellect, faculty of discernment",
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

    def test_mainaka_supplied_context_is_not_replaced(self) -> None:
        self.assertEqual(
            gloss_policy.meaning_only_gloss("Maināka", "Mainaka (golden mountain)"),
            "golden mountain",
        )

    def test_existing_meaning_first_gloss_is_preserved(self) -> None:
        self.assertEqual(gloss_policy.meaning_only_gloss("māyā", "worldly appearance and attachment"),
                         "worldly appearance and attachment")

    def test_bare_names_require_context_instead_of_global_identity(self) -> None:
        for roman, gloss in (("laṅkā", "Lanka"), ("hanumāna", "Hanuman"),
                             ("Śiva", "Shiva"), ("Rāma", "Rama"),
                             ("Surāsā", "Surasa"), ("nāma", "Nama"),
                             ("brahma", "Brahma"), ("mandā", "manda")):
            with self.subTest(roman=roman):
                with self.assertRaisesRegex(ValueError, "unresolved self-referential gloss"):
                    gloss_policy.meaning_only_gloss(roman, gloss)

    def test_self_reference_detection_ignores_diacritics_and_punctuation(self) -> None:
        self.assertFalse(gloss_policy.is_self_referential("buddhi,", "buddhi (intellect)"))
        self.assertTrue(gloss_policy.is_self_referential("Sāī̃", "Sai"))
        self.assertTrue(gloss_policy.is_self_referential("Sāīṃ", "Sai"))

    def test_divine_compound_never_falls_back_to_an_unexplained_spelling(self) -> None:
        self.assertTrue(gloss_policy.is_self_referential("śivaśaṅkara", "Shiva-Shankara"))
        with self.assertRaisesRegex(ValueError, "unresolved self-referential gloss"):
            gloss_policy.meaning_only_gloss("śivaśaṅkara", "Shiva-Shankara")

    def test_unknown_name_blocks_publication_instead_of_emitting_a_placeholder(self) -> None:
        with self.assertRaisesRegex(ValueError, "unresolved self-referential gloss"):
            gloss_policy.meaning_only_gloss("UnresolvedName", "UnresolvedName")

    def test_bare_madhava_requires_context_in_actual_pipeline_normalization(self) -> None:
        import bhakti_pipeline as pipeline

        for gloss in ("Madhava", "Mādhava", "Mādhava (proper name)"):
            with self.subTest(gloss=gloss):
                rows = [{"id": "context-needed", "word_glosses": [
                    {"roman": "Mādhava", "gloss": gloss, "concept_key": ""}]}]
                with self.assertRaisesRegex(ValueError, "unresolved self-referential gloss"):
                    pipeline.normalize_gloss_rows([], rows)
                self.assertEqual(rows[0]["word_glosses"][0]["gloss"], gloss)

    def test_madhava_context_preserves_both_poet_and_deity_in_pipeline(self) -> None:
        import bhakti_pipeline as pipeline

        for meaning in ("the poet's signature-name",
                        "Kṛṣṇa, here named as the cowherd beside the Yamunā"):
            with self.subTest(meaning=meaning):
                word = {"roman": "Mādhava", "gloss": meaning, "concept_key": "",
                        "preserve_in_english": False}
                rows = [{"id": "context-reviewed", "word_glosses": [word]}]
                self.assertEqual(pipeline.clean_gloss_rows(rows), rows)
                # Generation calls this same word cleaner after normalizing IAST.
                self.assertEqual(gloss_policy.clean_word(word), word)
                self.assertEqual(gloss_policy.meaning_only_gloss(
                    "Mādhava", "Mādhava, " + meaning), meaning)

    def test_name_leading_prose_remains_exact(self) -> None:
        for roman, explanation in (
            ("Mādhava", "Mādhava is a name of Kṛṣṇa in this scene"),
            ("Maināka", "Maināka is the mountain that offers Hanumān rest"),
            ("Rāma", "Rāma’s elder brother in the speaker’s comparison"),
            ("holikā", "Holika fire"),
        ):
            with self.subTest(explanation=explanation):
                self.assertFalse(gloss_policy.is_self_referential(roman, explanation))
                self.assertEqual(gloss_policy.meaning_only_gloss(roman, explanation), explanation)

    def test_label_delimiters_and_alias_only_explanations(self) -> None:
        for gloss in ("Mādhava, the poet's signature-name", "Madhava (the poet's signature-name)",
                      "Mādhava — the poet's signature-name", "Mādhava: the poet's signature-name"):
            with self.subTest(gloss=gloss):
                self.assertEqual(gloss_policy.meaning_only_gloss("Mādhava", gloss),
                                 "the poet's signature-name")
        for gloss in ("Mādhava / Madhava", "Madhava — Mādhava", "Mādhava Mādhava", "Mādhava (proper name)",
                      "Mādhava;", "Madhava", "proper name"):
            with self.subTest(gloss=gloss):
                with self.assertRaisesRegex(ValueError, "unresolved self-referential gloss"):
                    gloss_policy.meaning_only_gloss("Mādhava", gloss)

    def test_supplied_tail_preserves_its_own_parentheses(self) -> None:
        for gloss in ("Maināka (the mountain (a divine being))",
                      "Maināka, the mountain (a divine being)",
                      "Maināka [the mountain (a divine being)]"):
            self.assertEqual(gloss_policy.meaning_only_gloss("Maināka", gloss),
                             "the mountain (a divine being)")

    def test_parenthetical_name_leading_prose_remains_exact(self) -> None:
        for explanation in ("Mādhava (Kṛṣṇa), the cowherd",
                            "Mādhava (one name) and (another)"):
            self.assertEqual(gloss_policy.meaning_only_gloss("Mādhava", explanation),
                             explanation)

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
