import os
import dearpygui.dearpygui as dpg
from src.constants import Config
from src.ui.i18n import i18n
from src.thumbnail_manager import ThumbnailManager as thumb_manager


class SearchController:
    def __init__(self, app):
        self.app = app

    def on_search(self, sender, app_data, user_data, *args):
        if not self.app.db:
            return
        query = dpg.get_value("search_input").strip()
        if not query:
            self.clear_search()
            return

        def run_search():
            self.app._queue_ui_task(
                lambda: dpg.configure_item("browse_group", show=False)
            )
            self.app._queue_ui_task(
                lambda: dpg.configure_item("search_group", show=True)
            )
            self.app._queue_ui_task(
                lambda: dpg.delete_item("search_results", children_only=True)
            )

            rows = self.app.db.search_assets(query)
            if not rows:
                self.app._queue_ui_task(
                    lambda: dpg.add_text(
                        i18n("label_no_assets"), parent="search_results"
                    )
                )
            else:
                first_item = None
                for i_id, name, size, f_hash, key_val in rows:
                    u_data = {
                        "id": i_id,
                        "full_path": name,
                        "size": size,
                        "hash": f_hash,
                        "key": key_val,
                    }

                    def add_item(
                        label=os.path.basename(name),
                        tag=f"search_item_{i_id}",
                        data=u_data,
                    ):
                        self.app._add_file_selectable(
                            label,
                            data,
                            "search_results",
                            span_columns=True,
                            tag=tag,
                        )

                    self.app._queue_ui_task(add_item)
                    if first_item is None:
                        first_item = (f"search_item_{i_id}", u_data)

                if first_item:
                    self.app._queue_ui_task(
                        lambda f=first_item: self.app.on_file_click(f[0], None, f[1])
                    )

        self.app.executor.submit(run_search)

    def on_scene_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("scene_search_input").strip()
        self.app.executor.submit(self.render_scene_results, query)

    def scene_display_name(self, full_path):
        return os.path.basename(full_path)

    def clear_search(self, *args):
        dpg.set_value("search_input", "")
        dpg.configure_item("browse_group", show=True)
        dpg.configure_item("search_group", show=False)

    def clear_scene_search(self, *args):
        dpg.set_value("scene_search_input", "")
        self.render_scene_results("")

    def on_prop_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("prop_search_input").strip()
        self.app.executor.submit(self.render_prop_results, query)

    def clear_prop_search(self, *args):
        dpg.set_value("prop_search_input", "")
        self.render_prop_results("")

    def on_view_mode_change(self, sender, app_data, user_data):
        prefix = user_data  # "scene_" or "prop_"
        new_mode = "thumbnail" if app_data == i18n("label_view_thumbnail") else "list"

        if prefix == "scene_":
            self.app.scene_view_mode = new_mode
            query = dpg.get_value("scene_search_input").strip()
            self.app.executor.submit(self.render_scene_results, query)
        else:
            self.app.prop_view_mode = new_mode
            query = dpg.get_value("prop_search_input").strip()
            self.app.executor.submit(self.render_prop_results, query)

    def clear_search_thumbnails(self, prefix):
        with self.app.texture_lock:
            for tag in self.app.search_thumbnail_textures.get(prefix, []):
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            self.app.search_thumbnail_textures[prefix] = []

    def render_scene_results(self, query=""):
        view_mode = self.app.scene_view_mode
        list_container = "scene_results_parent"
        thumb_container = "scene_thumbnails_parent"

        self.app._queue_ui_task(
            lambda: dpg.configure_item(list_container, show=(view_mode == "list"))
        )
        self.app._queue_ui_task(
            lambda: dpg.configure_item(thumb_container, show=(view_mode == "thumbnail"))
        )
        self.app._queue_ui_task(
            lambda: dpg.delete_item(list_container, children_only=True)
        )
        self.app._queue_ui_task(
            lambda: dpg.delete_item(thumb_container, children_only=True)
        )
        self.clear_search_thumbnails("scene_")
        self.app.lazy_thumb_queues["scene_"] = []

        if not self.app.db:
            self.app._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_db_not_ready"),
                    parent=list_container,
                    color=[200, 120, 120],
                )
            )
            return

        rows = self.app.db.search_scenes(query)
        if not rows:
            target = list_container if view_mode == "list" else thumb_container
            self.app._queue_ui_task(
                lambda: dpg.add_text(i18n("label_no_scenes"), parent=target)
            )
            return

        first_item = None

        if view_mode == "list":
            for i_id, name, size, f_hash, key_val in rows:
                u_data = {
                    "id": i_id,
                    "full_path": name,
                    "size": size,
                    "hash": f_hash,
                    "key": key_val,
                }
                display_name = self.scene_display_name(name)

                def add_scene_item(
                    label=display_name, tag=f"scene_item_{i_id}", data=u_data
                ):
                    self.app._add_file_selectable(
                        label,
                        data,
                        list_container,
                        span_columns=True,
                        tag=tag,
                    )

                self.app._queue_ui_task(add_scene_item)
                if first_item is None:
                    first_item = (f"scene_item_{i_id}", u_data)
        else:
            # Thumbnail mode
            items_with_thumb = []
            thumb_dir = Config.get_thumbnail_dir()
            existing_thumbs = set()
            if os.path.exists(thumb_dir):
                existing_thumbs = {
                    f[:-4] for f in os.listdir(thumb_dir) if f.endswith(".png")
                }

            for i_id, name, size, f_hash, key_val in rows:
                if f_hash in existing_thumbs:
                    items_with_thumb.append((i_id, name, size, f_hash, key_val))

            if not items_with_thumb:
                self.app.thumbnail_items["scene_"] = []
                self.app._queue_ui_task(
                    lambda: dpg.add_text(
                        i18n("label_no_scenes"), parent=thumb_container
                    )
                )
            else:
                self.render_thumbnail_grid("scene_", items_with_thumb, thumb_container)

        if first_item and query and view_mode == "list":
            self.app._queue_ui_task(
                lambda f=first_item: self.app.on_file_click(f[0], None, f[1])
            )

    def render_prop_results(self, query=""):
        view_mode = self.app.prop_view_mode
        list_container = "prop_results_parent"
        thumb_container = "prop_thumbnails_parent"

        self.app._queue_ui_task(
            lambda: dpg.configure_item(list_container, show=(view_mode == "list"))
        )
        self.app._queue_ui_task(
            lambda: dpg.configure_item(thumb_container, show=(view_mode == "thumbnail"))
        )
        self.app._queue_ui_task(
            lambda: dpg.delete_item(list_container, children_only=True)
        )
        self.app._queue_ui_task(
            lambda: dpg.delete_item(thumb_container, children_only=True)
        )
        self.clear_search_thumbnails("prop_")
        self.app.lazy_thumb_queues["prop_"] = []

        if not self.app.db:
            self.app._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_db_not_ready"),
                    parent=list_container,
                    color=[200, 120, 120],
                )
            )
            return

        rows = self.app.db.search_props(query)
        if not rows:
            target = list_container if view_mode == "list" else thumb_container
            self.app._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_no_props"),
                    parent=target,
                )
            )
            return

        if view_mode == "list":
            first_item = None
            for i_id, name, size, f_hash, key_val in rows:
                u_data = {
                    "id": i_id,
                    "full_path": name,
                    "size": size,
                    "hash": f_hash,
                    "key": key_val,
                }

                def add_prop_item(
                    label=os.path.basename(name), tag=f"prop_item_{i_id}", data=u_data
                ):
                    self.app._add_file_selectable(
                        label,
                        data,
                        list_container,
                        span_columns=True,
                        tag=tag,
                    )

                self.app._queue_ui_task(add_prop_item)
                if first_item is None:
                    first_item = (f"prop_item_{i_id}", u_data)

            if first_item and query:
                self.app._queue_ui_task(
                    lambda f=first_item: self.app.on_file_click(f[0], None, f[1])
                )
        else:
            # Thumbnail mode
            items_with_thumb = []
            thumb_dir = Config.get_thumbnail_dir()
            existing_thumbs = set()
            if os.path.exists(thumb_dir):
                existing_thumbs = {
                    f[:-4] for f in os.listdir(thumb_dir) if f.endswith(".png")
                }

            for i_id, name, size, f_hash, key_val in rows:
                if f_hash in existing_thumbs:
                    items_with_thumb.append((i_id, name, size, f_hash, key_val))

            if not items_with_thumb:
                self.app.thumbnail_items["prop_"] = []
                self.app._queue_ui_task(
                    lambda: dpg.add_text(i18n("label_no_props"), parent=thumb_container)
                )
            else:
                self.render_thumbnail_grid("prop_", items_with_thumb, thumb_container)

    def render_thumbnail_grid(self, prefix, items, parent):
        self.app.thumbnail_items[prefix] = items

        try:
            width = dpg.get_item_rect_size(parent)[0]
            if width <= 0:
                width = 500
        except Exception:
            width = 500

        columns = max(1, int(width / 115))
        self.app.thumbnail_columns[prefix] = columns

        def build_grid():
            if not dpg.does_item_exist(parent):
                return

            dpg.delete_item(parent, children_only=True)
            self.clear_search_thumbnails(prefix)
            self.app.lazy_thumb_queues[prefix] = []

            with dpg.table(
                header_row=False, parent=parent, policy=dpg.mvTable_SizingStretchProp
            ):
                for _ in range(columns):
                    dpg.add_table_column()

                for i in range(0, len(items), columns):
                    with dpg.table_row():
                        for j in range(columns):
                            idx = i + j
                            if idx < len(items):
                                i_id, name, size, f_hash, key_val = items[idx]
                                with dpg.group() as cell_group:
                                    u_data = {
                                        "id": i_id,
                                        "full_path": name,
                                        "size": size,
                                        "hash": f_hash,
                                        "key": key_val,
                                    }

                                    img_id = dpg.add_image(
                                        "thumb_placeholder",
                                        width=100,
                                        height=100,
                                    )

                                    with dpg.item_handler_registry() as handler:
                                        dpg.add_item_clicked_handler(
                                            callback=lambda s, a, u: (
                                                self.app.on_file_click(a[1], a, u)
                                            ),
                                            user_data=u_data,
                                        )
                                    dpg.bind_item_handler_registry(img_id, handler)

                                    with dpg.tooltip(img_id):
                                        dpg.add_text(os.path.basename(name))

                                    thumb_path = thumb_manager.get_thumbnail(f_hash)
                                    if thumb_path:
                                        abs_path = os.path.abspath(thumb_path)
                                        # Include parent tag for buffered coordinate checking
                                        self.app.lazy_thumb_queues[prefix].append(
                                            (abs_path, img_id, parent)
                                        )
                            else:
                                dpg.add_spacer()

        self.app._queue_ui_task(build_grid)

    def process_lazy_thumbnails(self):
        import time

        now = time.time()
        if now - self.app.last_lazy_scan_time < self.app.lazy_scan_interval:
            return
        self.app.last_lazy_scan_time = now

        raw_tab = dpg.get_value("main_tabs")
        active_tab = (
            dpg.get_item_alias(raw_tab) if isinstance(raw_tab, int) else raw_tab
        )
        tab_to_prefix = {"scene_tab": "scene_", "prop_tab": "prop_"}
        active_prefix = tab_to_prefix.get(active_tab)

        if active_prefix:
            view_mode = (
                self.app.scene_view_mode
                if active_prefix == "scene_"
                else self.app.prop_view_mode
            )
            if view_mode == "thumbnail":
                container = f"{active_prefix}thumbnails_parent"
                if dpg.does_item_exist(container):
                    width = dpg.get_item_rect_size(container)[0]
                    expected_columns = max(1, int(width / 115))
                    if expected_columns != self.app.thumbnail_columns.get(
                        active_prefix, 0
                    ):
                        items = self.app.thumbnail_items.get(active_prefix, [])
                        if items:
                            self.render_thumbnail_grid(active_prefix, items, container)
                            return

        if not active_prefix or not self.app.lazy_thumb_queues[active_prefix]:
            return

        queue = self.app.lazy_thumb_queues[active_prefix]

        first_visible_idx = -1
        for i in range(0, len(queue), 4):
            try:
                if dpg.is_item_visible(queue[i][1]):
                    first_visible_idx = i
                    break
            except:
                continue

        if first_visible_idx == -1:
            try:
                if dpg.is_item_visible(queue[0][1]):
                    first_visible_idx = 0
            except:
                pass

        to_load_batch = []
        remaining = []

        if first_visible_idx == -1:
            to_load_batch = queue[:24]
            remaining = queue[24:]
        else:
            start = max(0, first_visible_idx - 12)
            end = min(len(queue), first_visible_idx + 48)

            to_load_batch = queue[start:end]
            remaining = queue[:start] + queue[end:]

        self.app.lazy_thumb_queues[active_prefix] = remaining

        if to_load_batch:
            tasks = [(t[0], t[1]) for t in to_load_batch]
            self.app.thumbnail_service.load_search_thumbnails_batch_async(
                active_prefix, tasks
            )
