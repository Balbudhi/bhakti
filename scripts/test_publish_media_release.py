#!/usr/bin/env python3

import unittest

import publish_media_release as media


class MediaReleaseTests(unittest.TestCase):
    def test_same_size_replacement_uses_content_hash(self) -> None:
        self.assertTrue(media.needs_upload(100, 100, "old", "new"))

    def test_matching_asset_does_not_upload_again(self) -> None:
        self.assertFalse(media.needs_upload(100, 100, "same", "same"))

    def test_size_change_always_uploads(self) -> None:
        self.assertTrue(media.needs_upload(99, 100, "same", "same"))


if __name__ == "__main__":
    unittest.main()
