#!/usr/bin/env python3

import unittest

import tag_taxonomy as tags


class TagTaxonomyTests(unittest.TestCase):
    def test_explicit_names_add_deity_tags(self) -> None:
        lines = [
            {"roman": "rājārāma kaho jī"},
            {"roman": "nandalālā mere nainana ke pyāre"},
            {"roman": "hari bhajana ko māna le"},
        ]
        self.assertEqual(tags.infer_named_subject_tags(lines), ["Rāma", "Kṛṣṇa", "Viṣṇu"])

    def test_generic_sai_does_not_claim_shirdi(self) -> None:
        self.assertNotIn("Śirḍī Sāī", tags.infer_named_subject_tags([{"roman": "bhūkhā sāīṁ"}]))
        self.assertIn("Śirḍī Sāī", tags.infer_named_subject_tags([{"roman": "Śirḍī Sāī Bābā"}]))

    def test_kali_age_does_not_claim_shakti(self) -> None:
        self.assertNotIn("Śakti", tags.infer_named_subject_tags([{"roman": "Kali yuga"}]))
        self.assertIn("Śakti", tags.infer_named_subject_tags([{"roman": "Mahākālī"}]))

    def test_merge_preserves_editorial_tags(self) -> None:
        merged = tags.merge_subject_tags(["Nirguṇa"], [{"roman": "Rāma nāma japa karanā"}])
        self.assertEqual(merged, ["Nirguṇa", "Rāma"])

    def test_named_modern_saints_are_recognized(self) -> None:
        inferred = tags.infer_named_subject_tags([
            {"roman": "Śāradā Mā tum hṛdaya nivāsinī"},
            {"roman": "Rāmakṛṣṇa prabhu isa yuga ke nāyaka"},
        ])
        self.assertIn("Śāradā Devī", inferred)
        self.assertIn("Śrī Rāmakṛṣṇa", inferred)

    def test_subject_tag_aliases_collapse_without_duplicates(self) -> None:
        merged = tags.merge_subject_tags(
            ["Śrī Śāradā Devī", "Śakti"],
            [{"roman": "Śāradā Mā tum hṛdaya nivāsinī"}],
        )
        self.assertEqual(merged, ["Śāradā Devī", "Śakti"])

    def test_hanuman_names_are_recognized(self) -> None:
        inferred = tags.infer_named_subject_tags([{"roman": "pavanaputra hanumāna saṅkaṭa harana"}])
        self.assertIn("Hanumān", inferred)

    def test_ganesha_names_are_recognized(self) -> None:
        inferred = tags.infer_named_subject_tags([{"roman": "gajavadan gaṇapati vināyaka"}])
        self.assertIn("Gaṇeśa", inferred)

    def test_vaishno_devi_is_both_specific_and_shakti(self) -> None:
        inferred = tags.infer_named_subject_tags([{"roman": "Vaishno Devi"}])
        self.assertIn("Śakti", inferred)
        self.assertIn("Vaiṣṇo Devī", inferred)

    def test_plain_vaishno_tag_normalizes_to_iast(self) -> None:
        merged = tags.merge_subject_tags(["Vaishno Devi"], [])
        self.assertEqual(merged, ["Vaiṣṇo Devī"])


if __name__ == "__main__":
    unittest.main()
