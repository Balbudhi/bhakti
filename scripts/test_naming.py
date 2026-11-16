#!/usr/bin/env python3
"""Focused tests for display-preserving Bhakti search aliases."""

from __future__ import annotations

import unittest

import naming


class NamingTests(unittest.TestCase):
    def test_canonical_person_keeps_satpathy_searchable(self) -> None:
        self.assertEqual(naming.canonical_person("Satpathy Baba"), "Shri Chandra Bhanu Satpathy")
        self.assertEqual(naming.person_search_aliases(["Satpathy Baba"]), ["Satpathy Baba"])

    def test_known_poet_spellings_share_one_identity(self) -> None:
        for spelling in ("Guru Gobind Singh", "Gurū Gobind Siṅgh"):
            self.assertEqual(naming.canonical_person(spelling), "Gurū Gobind Siṅgh")
        self.assertEqual(naming.canonical_person("Kabīr, Nānak & others"),
                         "Kabīr, Gurū Nānak & others")
        self.assertEqual(naming.canonical_person("Sant Tukaram; Sant Namdev"),
                         "Tukārām; Nāmadev")
        self.assertEqual(naming.canonical_person("Unknown Singh"), "Unknown Singh")
        self.assertEqual(naming.canonical_person("Ramdas"), "Ramdas")
        self.assertEqual(naming.canonical_person("Amardas"), "Amardas")
        self.assertEqual(naming.canonical_person("Samarth Rāmdās"), "Samarth Rāmdās")

    def test_joint_credit_aliases_include_each_person(self) -> None:
        aliases = naming.person_search_aliases(["Gurū Arjan & Gurū Gobind Siṅgh", "Nāmadev"])
        for value in ("Guru Arjun Dev", "Guru Gobind Singh", "Namdev"):
            self.assertIn(value, aliases)

    def test_common_search_spelling_preserves_digraphs(self) -> None:
        self.assertEqual(naming.common_romanization("Śirḍī Sāī"), "Shirdi Sai")

    def test_source_spelling_variants_share_one_singer(self) -> None:
        self.assertEqual(naming.canonical_person("Surjho Bhattacharya"), "Shurjo Bhattacharya")
        self.assertIn("Surjho Bhattacharya", naming.person_search_aliases(["Surjho Bhattacharya"]))

    def test_aliases_keep_non_mechanical_source_spellings(self) -> None:
        aliases = naming.search_aliases(["Īśvar Se Kuch Māṅgnā Ho To"], ["Ishwar Se Kuch Mangna Ho To"])
        self.assertIn("Ishvar Se Kuch Mangna Ho To", aliases)
        self.assertIn("Ishwar Se Kuch Mangna Ho To", aliases)

    def test_no_duplicate_display_spelling(self) -> None:
        aliases = naming.search_aliases(["Akkamahādevī", "Akkamahadevi"])
        self.assertEqual(aliases, [])

    def test_slugify_uses_plain_searchable_spelling(self) -> None:
        self.assertEqual(naming.slugify("Ākāśī Jhep Ghe Re Pākharā"), "akashi-jhep-ghe-re-pakhara")

    def test_combining_vocalic_letters_normalize_to_standard_iast(self) -> None:
        self.assertEqual(naming.canonical_iast("hr̥daya kr̥̄pā kl̥pta"), "hṛdaya kṝpā kḷpta")


if __name__ == "__main__":
    unittest.main()
