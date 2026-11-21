#!/usr/bin/env python3

import unittest

import tag_taxonomy as tags


class TagTaxonomyTests(unittest.TestCase):
    def test_umbrella_aliases_preserve_order_and_are_idempotent(self) -> None:
        values = [" Nirguṇa ", "Devī", "Devi", "Shakti", "Sakti", "Śakti",
                  "Gurū", "Satguru", "Sadguru", "Guru", ""]
        expected = ["Nirguṇa", "Śakti", "Guru"]
        self.assertEqual(tags.normalize_subject_tags(values), expected)
        self.assertEqual(tags.normalize_subject_tags(expected), expected)
        self.assertEqual(values[1], "Devī")

    def test_declared_goddess_identities_keep_specific_tags_and_add_parent(self) -> None:
        identities = ["Durgā", "Kālī", "Lakṣmī", "Sarasvatī", "Pārvatī", "Sītā",
                      "Vaiṣṇo Devī", "Madhumatī Śyāmalā", "Śyāmalā"]
        for identity in identities:
            with self.subTest(identity=identity):
                self.assertEqual(tags.normalize_subject_tags([identity]), [identity, "Śakti"])
        self.assertEqual(tags.normalize_subject_tags(identities), [*identities, "Śakti"])

    def test_sharada_devi_has_two_ordered_parents(self) -> None:
        expected = ["Śāradā Devī", "Śakti", "Guru"]
        self.assertEqual(tags.normalize_subject_tags(["Śrī Śāradā Devī"]), expected)
        self.assertEqual(tags.normalize_subject_tags(expected), expected)
        self.assertEqual(tags.normalize_subject_tags(["Guru", "Śāradā Devī"]),
                         ["Guru", "Śāradā Devī", "Śakti"])


    def test_declared_teacher_identities_add_guru_without_merging_people(self) -> None:
        for identity in ["Śirḍī Sāī", "Dattātreya", "Rāmakṛṣṇa", "Śrī Rāmakṛṣṇa"]:
            with self.subTest(identity=identity):
                self.assertEqual(tags.normalize_subject_tags([identity]), [identity, "Guru"])

    def test_closure_applies_to_inferred_names(self) -> None:
        self.assertEqual(tags.merge_subject_tags([], [{"roman": "sarasvatī"}]),
                         ["Sarasvatī", "Śakti"])
        self.assertEqual(tags.merge_subject_tags([], [{"roman": "Śirḍī Sāī"}]),
                         ["Śirḍī Sāī", "Guru"])

    def test_no_general_mother_teacher_or_author_classification(self) -> None:
        self.assertEqual(tags.merge_subject_tags([], [{"roman": "mā mātā mother guru satguru sadguru",
            "writer": "Tukārām", "singer": "Nāmadev"}]), [])
        self.assertEqual(tags.normalize_subject_tags(["Mother", "Tukārām", "Nāmadev"]),
                         ["Mother", "Tukārām", "Nāmadev"])


    def test_explicit_names_add_deity_tags(self) -> None:
        lines = [
            {"roman": "rājārāma kaho jī"},
            {"roman": "nandalālā mere nainana ke pyāre"},
            {"roman": "hari bhajana ko māna le"},
        ]
        self.assertEqual(tags.infer_named_subject_tags(lines), ["Rāma", "Kṛṣṇa"])

    def test_generic_sai_does_not_claim_shirdi(self) -> None:
        self.assertNotIn("Śirḍī Sāī", tags.infer_named_subject_tags([{"roman": "bhūkhā sāīṁ"}]))
        self.assertIn("Śirḍī Sāī", tags.infer_named_subject_tags([{"roman": "Śirḍī Sāī Bābā"}]))

    def test_kali_age_does_not_claim_shakti(self) -> None:
        self.assertNotIn("Kālī", tags.infer_named_subject_tags([{"roman": "Kali yuga"}]))
        self.assertIn("Kālī", tags.infer_named_subject_tags([{"roman": "Mahākālī"}]))
        self.assertIn("Kālī", tags.infer_named_subject_tags([{"roman": "He Kālī Mā"}]))

    def test_punjabi_bhavani_verb_does_not_claim_shakti(self) -> None:
        self.assertNotIn(
            "Śakti",
            tags.infer_named_subject_tags([{"roman": "jo tudhu bhāvani ratē"}]),
        )
        self.assertIn(
            "Śakti",
            tags.infer_named_subject_tags([{"roman": "Jai Maa Bhavani"}]),
        )

    def test_merge_preserves_editorial_tags(self) -> None:
        merged = tags.merge_subject_tags(["Nirguṇa"], [{"roman": "Rāma nāma japa karanā"}])
        self.assertEqual(merged, ["Nirguṇa", "Rāma"])

    def test_ambiguous_historical_names_are_not_inferred(self) -> None:
        inferred = tags.infer_named_subject_tags([
            {"roman": "Śāradā Mā tum hṛdaya nivāsinī"},
            {"roman": "Rāmakṛṣṇa prabhu isa yuga ke nāyaka"},
        ])
        self.assertNotIn("Śāradā Devī", inferred)
        self.assertNotIn("Śrī Rāmakṛṣṇa", inferred)

    def test_subject_tag_aliases_collapse_without_duplicates(self) -> None:
        merged = tags.merge_subject_tags(
            ["Śrī Śāradā Devī", "Śakti"],
            [{"roman": "Śāradā Mā tum hṛdaya nivāsinī"}],
        )
        self.assertEqual(merged, ["Śāradā Devī", "Śakti", "Guru"])

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
        self.assertEqual(merged, ["Vaiṣṇo Devī", "Śakti"])


if __name__ == "__main__":
    unittest.main()
