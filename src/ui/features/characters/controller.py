"""Character and outfit UI feature controller."""

import os

import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.core.i18n import i18n
from src.services.thumbnail.manager import ThumbnailManager as thumb_manager


class CharacterController:
    """Own character selection, outfit cards, and their request lifecycle."""

    list_container = "character_list_scroll"
    outfits_container = "character_outfits_content"

    def __init__(self, app):
        self.app = app

    def render_results(self):
        self.app._queue_ui_task(
            lambda: dpg.delete_item(self.list_container, children_only=True)
        )
        self.app._queue_ui_task(
            lambda: dpg.delete_item(self.outfits_container, children_only=True)
        )
        self.app.texture_registry.clear_domain("character_icons")
        self.app.texture_registry.clear_domain("character_outfits")
        self.app.lazy_thumb_queues["character_icons"] = []
        self.app.lazy_thumb_queues["character_outfits"] = []
        self.app.thumbnail_items["character_outfits"] = []

        if not self.app.db:
            self.app._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_db_not_ready"),
                    parent=self.list_container,
                    color=[200, 120, 120],
                )
            )
            self.app._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_character_panel_hint"), parent=self.outfits_container
                )
            )
            return

        self.app._queue_ui_task(
            lambda: (
                dpg.delete_item(self.list_container, children_only=True),
                dpg.add_text(i18n("msg_loading"), parent=self.list_container),
                dpg.delete_item(self.outfits_container, children_only=True),
                dpg.add_text(
                    i18n("label_character_panel_hint"), parent=self.outfits_container
                ),
            )
        )
        entries = self.app.db.get_character_entries()
        self.app.character_state.entries = entries
        self.app.thumbnail_request_ids["character_icons"] += 1
        request_id = self.app.thumbnail_request_ids["character_icons"]
        if not entries:
            self.app._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_no_characters"), parent=self.list_container
                )
            )
            return

        def build_list():
            if not dpg.does_item_exist(self.list_container):
                return
            if request_id != self.app.thumbnail_request_ids.get("character_icons"):
                return
            dpg.delete_item(self.list_container, children_only=True)
            ui_entries = []
            for entry in entries:
                data = dict(entry)
                with dpg.group(parent=self.list_container):
                    image_tag = dpg.add_image("thumb_placeholder", width=88, height=88)
                    data["item_tag"] = image_tag
                    with dpg.item_handler_registry() as handler:
                        dpg.add_item_clicked_handler(
                            callback=lambda s, a, u, tag=image_tag: self.on_selected(
                                tag, a, u
                            ),
                            user_data=data,
                        )
                    dpg.bind_item_handler_registry(image_tag, handler)
                    with dpg.tooltip(image_tag):
                        dpg.add_text(data["chara_name"])
                        dpg.add_text(f"ID: {data['chara_id']}")
                    dpg.add_text(data["chara_name"])
                    dpg.add_text(f"ID {data['chara_id']}", color=[150, 150, 150])
                ui_entries.append(data)
                self.app.lazy_thumb_queues["character_icons"].append(
                    {
                        "img_id": image_tag,
                        "cache_name": data["cache_name"],
                        "cache_path": thumb_manager.get_character_cache_path(
                            data["cache_name"]
                        ),
                        "hash": data["hash"],
                        "key": data["key"],
                        "texture_name": data["texture_name"],
                        "size": 88,
                    }
                )
            self.app.character_state.entries = ui_entries
            selected = next(
                (
                    item
                    for item in ui_entries
                    if item["chara_id"] == self.app.character_state.current_id
                ),
                ui_entries[0],
            )
            self.on_selected(selected["item_tag"], None, selected)

        self.app._queue_ui_task(build_list)

    def on_selected(self, sender, app_data, user_data, *args):
        state = self.app.character_state
        previous = state.selected_logo_tag
        if previous and previous != sender and dpg.does_item_exist(previous):
            dpg.configure_item(previous, tint_color=[255, 255, 255, 255])
        if sender and dpg.does_item_exist(sender):
            dpg.configure_item(sender, tint_color=[150, 200, 255, 255])
            state.selected_logo_tag = sender
        else:
            state.selected_logo_tag = user_data.get("item_tag")

        state.current_id = user_data["chara_id"]
        state.selected_outfit = None
        state.selected_outfit_tags = None
        self.app._queue_ui_task(
            lambda: dpg.configure_item("character_export_button", enabled=False)
        )
        self.app.thumbnail_request_ids["character_outfits"] += 1
        request_id = self.app.thumbnail_request_ids["character_outfits"]
        self.app.texture_registry.clear_domain("character_outfits")
        self.app.lazy_thumb_queues["character_outfits"] = []
        self.app.thumbnail_items["character_outfits"] = []
        self.app._queue_ui_task(
            lambda: (
                dpg.delete_item(self.outfits_container, children_only=True),
                dpg.add_text(i18n("msg_loading"), parent=self.outfits_container),
            )
        )

        def load_outfits():
            outfits = self.app.db.get_character_outfit_assets(user_data["chara_id"])
            self.app._queue_ui_task(
                lambda: self.render_outfit_grid(
                    user_data["chara_id"], outfits, request_id
                )
            )

        self.app.executor.submit(load_outfits)

    def render_outfit_grid(self, chara_id, items, request_id=None):
        items = [
            item
            for item in items
            if item.get("texture_name") or item.get("icon_texture_name")
        ]
        if request_id != self.app.thumbnail_request_ids.get("character_outfits"):
            return
        image_size = Config.CHARACTER_OUTFIT_IMAGE_SIZE
        try:
            width = dpg.get_item_rect_size(self.outfits_container)[0] or 800
        except Exception:
            width = 800
        columns = max(1, int(width / (image_size + 40)))
        self.app.thumbnail_columns["character_outfits"] = columns

        def build_grid():
            if not dpg.does_item_exist(self.outfits_container):
                return
            if request_id != self.app.thumbnail_request_ids.get("character_outfits"):
                return
            if chara_id != self.app.character_state.current_id:
                return
            self.app.thumbnail_items["character_outfits"] = items
            dpg.delete_item(self.outfits_container, children_only=True)
            self.app.texture_registry.clear_domain("character_outfits")
            self.app.lazy_thumb_queues["character_outfits"] = []
            dpg.add_text(
                f"{i18n('label_character_outfits')} {chara_id}",
                parent=self.outfits_container,
                color=[0, 255, 0],
            )
            dpg.set_value("character_export_status", i18n("msg_select_outfit"))
            dpg.add_separator(parent=self.outfits_container)
            if not items:
                dpg.add_text(
                    i18n("label_no_character_outfits"), parent=self.outfits_container
                )
                return
            with dpg.table(
                header_row=False,
                parent=self.outfits_container,
                policy=dpg.mvTable_SizingStretchProp,
            ):
                for _ in range(columns):
                    dpg.add_table_column()
                for offset in range(0, len(items), columns):
                    with dpg.table_row():
                        for index in range(columns):
                            item_index = offset + index
                            if item_index >= len(items):
                                dpg.add_spacer()
                                continue
                            self._add_outfit_card(items[item_index], image_size)

        self.app._queue_ui_task(build_grid)

    def _add_outfit_card(self, item, image_size):
        has_stand = bool(item.get("texture_name"))
        card_size = image_size if has_stand else Config.CHARACTER_3D_OUTFIT_ICON_SIZE
        with dpg.group():
            image_tag = dpg.add_image(
                "thumb_placeholder", width=card_size, height=card_size
            )
            item["item_tag"] = image_tag
            item["selection_tags"] = [image_tag]
            with dpg.item_handler_registry() as handler:
                dpg.add_item_clicked_handler(
                    callback=lambda s, a, u, tag=image_tag: self.on_outfit_selected(
                        tag, a, u
                    ),
                    user_data=item,
                )
            dpg.bind_item_handler_registry(image_tag, handler)
            with dpg.tooltip(image_tag):
                dpg.add_text(item["dress_name"])
                if item.get("outfit_id"):
                    dpg.add_text(f"ID: {item['outfit_id']}")
            source = (
                item
                if has_stand
                else {
                    "cache_name": item["icon_cache_name"],
                    "hash": item["icon_hash"],
                    "key": item["icon_key"],
                    "texture_name": item["icon_texture_name"],
                }
            )
            self.app.lazy_thumb_queues["character_outfits"].append(
                {
                    "img_id": image_tag,
                    "cache_name": source["cache_name"],
                    "cache_path": thumb_manager.get_character_cache_path(
                        source["cache_name"]
                    ),
                    "hash": source["hash"],
                    "key": source["key"],
                    "texture_name": source["texture_name"],
                    "size": card_size,
                }
            )
            dpg.add_text(item["dress_name"], wrap=image_size)
            if item.get("outfit_id"):
                dpg.add_text(
                    f"ID {item['outfit_id']}", wrap=image_size, color=[150, 150, 150]
                )

    def on_outfit_selected(self, sender, app_data, user_data, *args):
        def tint(tag, color):
            if tag and dpg.does_item_exist(tag):
                dpg.configure_item(tag, tint_color=color)

        previous = self.app.character_state.selected_outfit_tags or []
        for tag in previous:
            if tag != sender:
                tint(tag, [255, 255, 255, 255])
        selected = user_data.get("selection_tags") or [
            sender or user_data.get("item_tag")
        ]
        for tag in selected:
            tint(tag, [150, 200, 255, 255])
        self.app.character_state.selected_outfit_tags = selected
        self.app.character_state.selected_outfit = user_data
        dpg.configure_item("character_export_button", enabled=True)
        status = user_data.get("dress_name", "")
        if user_data.get("outfit_id"):
            status = f"{status} (ID: {user_data['outfit_id']})"
        dpg.set_value("character_export_status", status)
