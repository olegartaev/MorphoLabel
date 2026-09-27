import unittest

from app.ui.photo_list_panel import (
    DEFAULT_SHOW_EXCLUDED,
    filtered_photo_indices,
    photo_search_cache,
)


class PhotoListExclusionFilterTests(unittest.TestCase):
    def test_excluded_images_are_hidden_from_working_list_by_default(self):
        rows = [
            {"image_id": "active", "locality": "A", "source_relpath": "a.png", "excluded": False},
            {"image_id": "excluded", "locality": "A", "source_relpath": "b.png", "excluded": True},
        ]
        cache = photo_search_cache(rows)
        self.assertFalse(DEFAULT_SHOW_EXCLUDED)
        self.assertEqual([0], filtered_photo_indices(rows, cache))

    def test_show_excluded_remains_an_explicit_inspection_mode(self):
        rows = [
            {"image_id": "active", "locality": "A", "source_relpath": "a.png", "excluded": False},
            {"image_id": "excluded", "locality": "A", "source_relpath": "b.png", "excluded": True},
        ]
        cache = photo_search_cache(rows)
        self.assertEqual([0, 1], filtered_photo_indices(rows, cache, show_excluded=True))


if __name__ == "__main__":
    unittest.main()
