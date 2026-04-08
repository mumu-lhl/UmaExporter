import os
import dearpygui.dearpygui as dpg
from src.constants import Config
from src.ui.i18n import i18n
from src.thumbnail_manager import ThumbnailManager as thumb_manager
from src.unity_logic import UnityLogic


class SearchController:
    def __init__(self, app):
        self.app = app

    def _add_global_search_result_item(self, row):
        i_id, name, size, f_hash, key_val = row
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
        return f"search_item_{i_id}", u_data

    def _set_global_search_loading_indicator(self, show):
        def update():
            if show:
                if not dpg.does_item_exist("search_load_more_status"):
                    dpg.add_text(
                        i18n("msg_loading"),
                        parent="search_results",
                        tag="search_load_more_status",
                    )
            elif dpg.does_item_exist("search_load_more_status"):
                dpg.delete_item("search_load_more_status")

        self.app._queue_ui_task(update)

    def _load_global_search_page(self, query, request_id, reset=False):
        rows = self.app.db.search_assets(
            query,
            limit=self.app.global_search_limit,
            offset=self.app.global_search_offset,
        )
        if request_id != self.app.global_search_request_id:
            return

        self.app.global_search_has_more = len(rows) == self.app.global_search_limit
        self.app.global_search_offset += len(rows)

        if reset:
            self.app._queue_ui_task(
                lambda: dpg.delete_item("search_results", children_only=True)
            )

        if not rows and reset:
            self.app._queue_ui_task(
                lambda: dpg.add_text(i18n("label_no_assets"), parent="search_results")
            )
            self.app.global_search_loading_more = False
            return

        first_item = None
        for row in rows:
            added = self._add_global_search_result_item(row)
            if first_item is None:
                first_item = added

        if reset and first_item:
            self.app._queue_ui_task(
                lambda f=first_item: self.app.on_file_click(f[0], None, f[1])
            )

        self.app.global_search_loading_more = False
        self._set_global_search_loading_indicator(False)

    def on_search(self, sender, app_data, user_data, *args):
        if not self.app.db:
            return
        query = dpg.get_value("search_input").strip()
        if not query:
            self.clear_search()
            return

        def run_search():
            self.app.global_search_query = query
            self.app.global_search_offset = 0
            self.app.global_search_has_more = False
            self.app.global_search_loading_more = True
            self.app.global_search_request_id += 1
            request_id = self.app.global_search_request_id
            self.app._queue_ui_task(
                lambda: dpg.configure_item("browse_group", show=False)
            )
            self.app._queue_ui_task(
                lambda: dpg.configure_item("search_group", show=True)
            )
            self._set_global_search_loading_indicator(True)
            self._load_global_search_page(query, request_id, reset=True)

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
        self.app.global_search_query = ""
        self.app.global_search_offset = 0
        self.app.global_search_has_more = False
        self.app.global_search_loading_more = False
        self.app.global_search_request_id += 1

    def clear_scene_search(self, *args):
        dpg.set_value("scene_search_input", "")
        self.render_scene_results("")

    def on_prop_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("prop_search_input").strip()
        self.app.executor.submit(self.render_prop_results, query)

    def clear_prop_search(self, *args):
        dpg.set_value("prop_search_input", "")
        self.render_prop_results("")

    def render_character_results(self):
        list_container = "character_list_scroll"
        outfits_container = "character_outfits_content"

        self.app._queue_ui_task(lambda: dpg.delete_item(list_container, children_only=True))
        self.app._queue_ui_task(
            lambda: dpg.delete_item(outfits_container, children_only=True)
        )
        self.clear_search_thumbnails("character_icons")
        self.clear_search_thumbnails("character_outfits")
        self.app.lazy_thumb_queues["character_icons"] = []
        self.app.lazy_thumb_queues["character_outfits"] = []
        self.app.thumbnail_items["character_outfits"] = []

        if not self.app.db:
            self.app._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_db_not_ready"),
                    parent=list_container,
                    color=[200, 120, 120],
                )
            )
            self.app._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_character_panel_hint"), parent=outfits_container
                )
            )
            return

        self.app._queue_ui_task(
            lambda: (
                dpg.delete_item(list_container, children_only=True),
                dpg.add_text(i18n("msg_loading"), parent=list_container),
                dpg.delete_item(outfits_container, children_only=True),
                dpg.add_text(
                    i18n("label_character_panel_hint"), parent=outfits_container
                ),
            )
        )

        entries = self.app.db.get_character_entries()
        self.app.character_entries = entries
        self.app.thumbnail_request_ids["character_icons"] += 1
        request_id = self.app.thumbnail_request_ids["character_icons"]

        if not entries:
            self.app._queue_ui_task(
                lambda: dpg.add_text(i18n("label_no_characters"), parent=list_container)
            )
            self.app._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_character_panel_hint"), parent=outfits_container
                )
            )
            return

        def build_character_list():
            if not dpg.does_item_exist(list_container):
                return
            if request_id != self.app.thumbnail_request_ids.get("character_icons"):
                return

            dpg.delete_item(list_container, children_only=True)
            ui_entries = []

            for entry in entries:
                entry_data = dict(entry)
                with dpg.group(parent=list_container):
                    img_id = dpg.add_image(
                        "thumb_placeholder",
                        width=88,
                        height=88,
                    )
                    entry_data["item_tag"] = img_id

                    with dpg.item_handler_registry() as handler:
                        dpg.add_item_clicked_handler(
                            callback=lambda s, a, u, item=img_id: self.on_character_selected(
                                item, a, u
                            ),
                            user_data=entry_data,
                        )
                    dpg.bind_item_handler_registry(img_id, handler)

                    with dpg.tooltip(img_id):
                        dpg.add_text(entry_data["chara_name"])
                        dpg.add_text(f"ID: {entry_data['chara_id']}")

                    dpg.add_text(entry_data["chara_name"])
                    dpg.add_text(f"ID {entry_data['chara_id']}", color=[150, 150, 150])

                ui_entries.append(entry_data)
                cache_path = thumb_manager.get_character_cache_path(
                    entry_data["cache_name"]
                )
                self.app.lazy_thumb_queues["character_icons"].append(
                    {
                        "img_id": img_id,
                        "cache_name": entry_data["cache_name"],
                        "cache_path": cache_path,
                        "hash": entry_data["hash"],
                        "key": entry_data["key"],
                        "texture_name": entry_data["texture_name"],
                        "size": 88,
                    }
                )

            self.app.character_entries = ui_entries

            selected_entry = next(
                (
                    item
                    for item in ui_entries
                    if item["chara_id"] == self.app.current_character_id
                ),
                ui_entries[0],
            )
            self.on_character_selected(
                selected_entry.get("item_tag"), None, selected_entry
            )

        self.app._queue_ui_task(build_character_list)

    def on_character_selected(self, sender, app_data, user_data, *args):
        previous = self.app.last_selected_character_logo
        if previous and previous != sender and dpg.does_item_exist(previous):
            dpg.configure_item(previous, tint_color=[255, 255, 255, 255])

        if sender and dpg.does_item_exist(sender):
            dpg.configure_item(sender, tint_color=[150, 200, 255, 255])
            self.app.last_selected_character_logo = sender
        else:
            self.app.last_selected_character_logo = user_data.get("item_tag")
            if self.app.last_selected_character_logo and dpg.does_item_exist(
                self.app.last_selected_character_logo
            ):
                dpg.configure_item(
                    self.app.last_selected_character_logo,
                    tint_color=[150, 200, 255, 255],
                )

        self.app.current_character_id = user_data["chara_id"]
        self.app.current_character_outfit = None
        self.app.last_selected_character_outfit = None
        self.app._queue_ui_task(
            lambda: dpg.configure_item("character_export_button", enabled=False)
        )
        self.app.thumbnail_request_ids["character_outfits"] += 1
        request_id = self.app.thumbnail_request_ids["character_outfits"]
        self.clear_search_thumbnails("character_outfits")
        self.app.lazy_thumb_queues["character_outfits"] = []
        self.app.thumbnail_items["character_outfits"] = []
        self.app._queue_ui_task(
            lambda: (
                dpg.delete_item("character_outfits_content", children_only=True),
                dpg.add_text(i18n("msg_loading"), parent="character_outfits_content"),
            )
        )

        def load_outfits_worker():
            outfits = self.app.db.get_character_outfit_assets(user_data["chara_id"])
            self.app._queue_ui_task(
                lambda: self._render_character_outfit_grid(
                    user_data["chara_id"], outfits, request_id=request_id
                )
            )

        self.app.executor.submit(load_outfits_worker)

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

    def process_global_search_load_more(self):
        if not self.app.global_search_query or self.app.global_search_loading_more:
            return
        if not self.app.global_search_has_more:
            return
        if not dpg.does_item_exist("search_group") or not dpg.is_item_shown("search_group"):
            return
        if not dpg.does_item_exist("search_results"):
            return

        try:
            scroll_y = dpg.get_y_scroll("search_results")
            max_scroll_y = dpg.get_y_scroll_max("search_results")
        except Exception:
            return

        if max_scroll_y <= 0:
            return

        if scroll_y < max_scroll_y - self.app.global_search_scroll_threshold:
            return

        self.app.global_search_loading_more = True
        request_id = self.app.global_search_request_id
        query = self.app.global_search_query
        self._set_global_search_loading_indicator(True)
        self.app.executor.submit(self._load_global_search_page, query, request_id, False)

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
                        i18n("msg_no_thumbnails_hint"),
                        parent=thumb_container,
                        color=[255, 255, 0],
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
                    lambda: dpg.add_text(
                        i18n("msg_no_thumbnails_hint"),
                        parent=thumb_container,
                        color=[255, 255, 0],
                    )
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

    def _render_character_outfit_grid(self, chara_id, items, request_id=None):
        parent = "character_outfits_content"
        if request_id is None:
            self.app.thumbnail_request_ids["character_outfits"] += 1
            request_id = self.app.thumbnail_request_ids["character_outfits"]
        else:
            if request_id != self.app.thumbnail_request_ids.get("character_outfits"):
                return

        try:
            width = dpg.get_item_rect_size(parent)[0]
            if width <= 0:
                width = 800
        except Exception:
            width = 800

        columns = max(1, int(width / 220))
        self.app.thumbnail_columns["character_outfits"] = columns

        def build_grid():
            if not dpg.does_item_exist(parent):
                return
            if request_id != self.app.thumbnail_request_ids.get("character_outfits"):
                return
            if chara_id != self.app.current_character_id:
                return

            self.app.thumbnail_items["character_outfits"] = items
            dpg.delete_item(parent, children_only=True)
            self.clear_search_thumbnails("character_outfits")
            self.app.lazy_thumb_queues["character_outfits"] = []

            dpg.add_text(
                f"{i18n('label_character_outfits')} {chara_id}",
                parent=parent,
                color=[0, 255, 0],
            )
            dpg.set_value("character_export_status", i18n("msg_select_outfit"))
            dpg.add_separator(parent=parent)

            if not items:
                dpg.add_text(i18n("label_no_character_outfits"), parent=parent)
                return

            with dpg.table(
                header_row=False, parent=parent, policy=dpg.mvTable_SizingStretchProp
            ):
                for _ in range(columns):
                    dpg.add_table_column()

                for i in range(0, len(items), columns):
                    with dpg.table_row():
                        for j in range(columns):
                            idx = i + j
                            if idx >= len(items):
                                dpg.add_spacer()
                                continue

                            item = items[idx]
                            display_name = os.path.basename(item["full_path"])
                            if display_name.startswith("chara_stand_"):
                                display_name = display_name[len("chara_stand_") :]
                            chara_prefix = f"{chara_id}_"
                            if display_name.startswith(chara_prefix):
                                display_name = display_name[len(chara_prefix) :]
                            with dpg.group():
                                img_id = dpg.add_image(
                                    "thumb_placeholder",
                                    width=180,
                                    height=180,
                                )
                                item["item_tag"] = img_id
                                with dpg.item_handler_registry() as handler:
                                    dpg.add_item_clicked_handler(
                                        callback=lambda s, a, u, item_id=img_id: self.on_character_outfit_selected(
                                            item_id, a, u
                                        ),
                                        user_data=item,
                                    )
                                dpg.bind_item_handler_registry(img_id, handler)
                                with dpg.tooltip(img_id):
                                    dpg.add_text(os.path.basename(item["full_path"]))
                                dpg.add_text(display_name, wrap=180)

                                self.app.lazy_thumb_queues["character_outfits"].append(
                                    {
                                        "img_id": img_id,
                                        "cache_name": item["cache_name"],
                                        "cache_path": thumb_manager.get_character_cache_path(
                                            item["cache_name"]
                                        ),
                                        "hash": item["hash"],
                                        "key": item["key"],
                                        "texture_name": item["texture_name"],
                                        "size": 180,
                                    }
                                )

        self.app._queue_ui_task(build_grid)

    def on_character_outfit_selected(self, sender, app_data, user_data, *args):
        previous = self.app.last_selected_character_outfit
        if previous and previous != sender and dpg.does_item_exist(previous):
            dpg.configure_item(previous, tint_color=[255, 255, 255, 255])

        if sender and dpg.does_item_exist(sender):
            dpg.configure_item(sender, tint_color=[150, 200, 255, 255])
            self.app.last_selected_character_outfit = sender
        else:
            self.app.last_selected_character_outfit = user_data.get("item_tag")
            if self.app.last_selected_character_outfit and dpg.does_item_exist(
                self.app.last_selected_character_outfit
            ):
                dpg.configure_item(
                    self.app.last_selected_character_outfit,
                    tint_color=[150, 200, 255, 255],
                )

        self.app.current_character_outfit = user_data
        dpg.configure_item("character_export_button", enabled=True)
        dpg.set_value("character_export_status", os.path.basename(user_data["full_path"]))

    def _load_character_texture_batch_async(self, domain, tasks, request_id):
        def worker():
            import numpy as np
            from PIL import Image, ImageOps

            results = []
            resample_filter = getattr(Image, "Resampling", Image).BILINEAR

            for task in tasks:
                cache_path = task["cache_path"]
                if not os.path.exists(cache_path):
                    phys_path = os.path.join(
                        Config.get_data_root(),
                        task["hash"][:2],
                        task["hash"],
                    )
                    data, _, _ = UnityLogic.get_named_texture_data(
                        phys_path,
                        task["texture_name"],
                        bundle_key=task["key"],
                        max_size=task["size"],
                    )
                    if data is not None:
                        results.append((task["img_id"], data, task["size"]))
                        self._schedule_character_cache_write(task)
                    continue

                try:
                    img = Image.open(cache_path).convert("RGBA")
                    img = ImageOps.contain(
                        img, (task["size"], task["size"]), method=resample_filter
                    )
                    canvas = Image.new("RGBA", (task["size"], task["size"]), (0, 0, 0, 0))
                    paste_x = (task["size"] - img.width) // 2
                    paste_y = (task["size"] - img.height) // 2
                    canvas.paste(img, (paste_x, paste_y), img)
                    data = np.array(canvas).flatten().astype(np.float32) / 255.0
                    results.append((task["img_id"], data, task["size"]))
                except Exception:
                    continue

            return results

        future = self.app.executor.submit(worker)

        def done(f):
            try:
                batch_results = f.result()
                if batch_results:
                    self.app._queue_ui_task(
                        lambda: self._apply_character_texture_batch(
                            domain, request_id, batch_results
                        )
                    )
            except Exception:
                pass

        future.add_done_callback(done)

    def _schedule_character_cache_write(self, task):
        cache_name = task["cache_name"]
        if cache_name in self.app.character_cache_pending:
            return

        self.app.character_cache_pending.add(cache_name)

        def worker():
            try:
                cache_path = task["cache_path"]
                if os.path.exists(cache_path):
                    return

                phys_path = os.path.join(
                    Config.get_data_root(),
                    task["hash"][:2],
                    task["hash"],
                )
                UnityLogic.export_named_texture_to_png(
                    phys_path,
                    task["texture_name"],
                    cache_path,
                    bundle_key=task["key"],
                )
            finally:
                self.app.character_cache_pending.discard(cache_name)

        self.app.executor.submit(worker)

    def _apply_character_texture_batch(self, domain, request_id, batch_results):
        if request_id != self.app.thumbnail_request_ids.get(domain):
            return

        with self.app.texture_lock:
            for img_id, data, size in batch_results:
                if not dpg.does_item_exist(img_id):
                    continue

                tex_tag = dpg.generate_uuid()
                try:
                    dpg.add_static_texture(
                        width=size,
                        height=size,
                        default_value=data,
                        tag=tex_tag,
                        parent="main_texture_registry",
                    )
                    dpg.configure_item(img_id, texture_tag=tex_tag)
                    self.app.search_thumbnail_textures[domain].append(tex_tag)
                except Exception:
                    pass

    def _process_character_lazy_queue(self, domain, batch_size):
        queue = self.app.lazy_thumb_queues.get(domain, [])
        if not queue:
            return False

        first_visible_idx = -1
        for idx, task in enumerate(queue):
            try:
                if dpg.is_item_visible(task["img_id"]):
                    first_visible_idx = idx
                    break
            except Exception:
                continue

        if first_visible_idx == -1:
            to_load_batch = queue[:batch_size]
            remaining = queue[batch_size:]
        else:
            start = max(0, first_visible_idx - batch_size // 2)
            end = min(len(queue), start + batch_size)
            to_load_batch = queue[start:end]
            remaining = queue[:start] + queue[end:]

        self.app.lazy_thumb_queues[domain] = remaining

        if to_load_batch:
            self._load_character_texture_batch_async(
                domain,
                to_load_batch,
                self.app.thumbnail_request_ids.get(domain, 0),
            )
            return True

        return False

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
        if active_tab == "character_tab":
            try:
                width = dpg.get_item_rect_size("character_outfits_panel")[0]
                expected_columns = max(1, int(max(width, 1) / 220))
            except Exception:
                expected_columns = self.app.thumbnail_columns.get("character_outfits", 0)

            if expected_columns != self.app.thumbnail_columns.get("character_outfits", 0):
                items = self.app.thumbnail_items.get("character_outfits", [])
                if items and self.app.current_character_id:
                    self._render_character_outfit_grid(
                        self.app.current_character_id,
                        items,
                        request_id=self.app.thumbnail_request_ids.get(
                            "character_outfits", 0
                        ),
                    )
                    return

            if self._process_character_lazy_queue("character_icons", 12):
                return
            self._process_character_lazy_queue("character_outfits", 16)
            return

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
