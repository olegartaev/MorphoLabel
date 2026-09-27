import unittest

from app.ui.photo_list_panel import (
    DEFAULT_SHOW_EXCLUDED,
    filtered_photo_indices,
    next_working_photo_index,
    photo_search_cache,
)


class PhotoListExclusionFilterTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"image_id": "a", "locality": "A", "source_relpath": "a.png", "excluded": False},
            {"image_id": "x", "locality": "A", "source_relpath": "x.png", "excluded": True},
            {"image_id": "b", "locality": "A", "source_relpath": "b.png", "excluded": False},
        ]
        self.cache = photo_search_cache(self.rows)

    def test_excluded_images_stay_visible_in_list_by_default(self):
        self.assertTrue(DEFAULT_SHOW_EXCLUDED)
        self.assertEqual([0, 1, 2], filtered_photo_indices(self.rows, self.cache))

    def test_user_can_explicitly_hide_excluded_rows(self):
        self.assertEqual([0, 2], filtered_photo_indices(self.rows, self.cache, show_excluded=False))

    def test_working_navigation_skips_visible_excluded_row_forward_and_backward(self):
        visible = filtered_photo_indices(self.rows, self.cache)
        self.assertEqual(2, next_working_photo_index(self.rows, visible, 0, 1))
        self.assertEqual(0, next_working_photo_index(self.rows, visible, 2, -1))

    def test_navigation_from_clicked_excluded_row_moves_to_active_neighbor(self):
        visible = filtered_photo_indices(self.rows, self.cache)
        self.assertEqual(2, next_working_photo_index(self.rows, visible, 1, 1))
        self.assertEqual(0, next_working_photo_index(self.rows, visible, 1, -1))

    def test_navigation_returns_none_when_every_visible_row_is_excluded(self):
        rows = [{"image_id": "x", "excluded": True}]
        cache = photo_search_cache(rows)
        visible = filtered_photo_indices(rows, cache)
        self.assertIsNone(next_working_photo_index(rows, visible, 0, 1))


if __name__ == "__main__":
    unittest.main()
