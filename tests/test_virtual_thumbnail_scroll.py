import unittest
from src.ui.controllers.search_controller import (
    SEARCH_THUMBNAIL_WINDOW_GRID_ROWS,
    SEARCH_THUMBNAIL_WINDOW_STEP_ROWS,
    SEARCH_THUMBNAIL_ROWS_PER_FRAME,
    _THUMBNAIL_ROW_HEIGHT,
    SearchController,
)


class VirtualThumbnailScrollTests(unittest.TestCase):
    def test_window_buffer_geometry(self):
        # Ensure single frame building to prevent multi-frame incomplete rendering
        self.assertGreaterEqual(
            SEARCH_THUMBNAIL_ROWS_PER_FRAME,
            SEARCH_THUMBNAIL_WINDOW_GRID_ROWS,
            "ROWS_PER_FRAME should be >= WINDOW_GRID_ROWS so all rows build in 1 frame",
        )

        # Ensure window is large enough to cover viewport (up to 12 rows / ~1300px) plus buffer
        min_required_window = 2 * SEARCH_THUMBNAIL_WINDOW_STEP_ROWS + 12
        self.assertGreaterEqual(
            SEARCH_THUMBNAIL_WINDOW_GRID_ROWS,
            min_required_window,
            "WINDOW_GRID_ROWS must be >= 2 * STEP + viewport_rows to prevent blank exposure",
        )

    def test_scroll_down_never_exposes_bottom_spacer(self):
        # Simulate scrolling down from 0 to 10000px on a large 1080p/1440p viewport (1200px / ~11 rows)
        viewport_height = 1200
        columns = 4
        total_items = 1000  # 250 rows

        for scroll_y in range(0, 250 * _THUMBNAIL_ROW_HEIGHT - viewport_height, 20):
            start, end = SearchController._virtual_window_bounds(
                "thumbnail", total_items, scroll_y, columns
            )
            top_spacer_h, bottom_spacer_h = SearchController._virtual_spacer_heights(
                "thumbnail", total_items, start, end, columns
            )

            viewport_top = scroll_y
            viewport_bottom = scroll_y + viewport_height

            start_row = start // columns
            end_row = (end + columns - 1) // columns

            table_top_y = start_row * _THUMBNAIL_ROW_HEIGHT
            table_bottom_y = end_row * _THUMBNAIL_ROW_HEIGHT

            # Viewport top must not be above table top (unless at the very top of content)
            if start_row > 0:
                self.assertLessEqual(
                    table_top_y,
                    viewport_top,
                    f"Top spacer exposed at scroll_y={scroll_y}: table starts at {table_top_y}, viewport at {viewport_top}",
                )

            # Viewport bottom must not exceed table bottom (unless at the very bottom of content)
            if end < total_items:
                self.assertGreaterEqual(
                    table_bottom_y,
                    viewport_bottom,
                    f"Bottom spacer exposed at scroll_y={scroll_y}: table ends at {table_bottom_y}, viewport bottom at {viewport_bottom}",
                )

    def test_take_thumbnail_batch_fallback(self):
        from unittest.mock import patch
        queue = [("path_1", "tag_1"), ("path_2", "tag_2")]
        with patch("dearpygui.dearpygui.is_item_visible", return_value=False):
            batch = SearchController._take_thumbnail_batch(queue)
        # When first_visible is None (no item visible yet in test), it should fall back to 0
        self.assertEqual(len(batch), 2)
        self.assertEqual(len(queue), 0)


if __name__ == "__main__":
    unittest.main()
