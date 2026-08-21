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


if __name__ == "__main__":
    unittest.main()
