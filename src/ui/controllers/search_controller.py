import os
import time

import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.core.i18n import i18n
from src.core.monitor import Monitor
from src.ui.features.characters.thumbnails import CharacterThumbnailLoader

SEARCH_LIST_ROWS_PER_FRAME = 256
SEARCH_THUMBNAIL_ROWS_PER_FRAME = 48
SEARCH_THUMBNAIL_DECODE_BATCH_SIZE = 8
SEARCH_THUMBNAIL_MAX_INFLIGHT = 2
SEARCH_LIST_WINDOW_ROWS = 256
SEARCH_LIST_WINDOW_STEP = 96
SEARCH_THUMBNAIL_WINDOW_GRID_ROWS = 48
SEARCH_THUMBNAIL_WINDOW_STEP_ROWS = 16

_SEARCH_PREFIXES = ("", "scene_", "prop_")
_LIST_ROW_HEIGHT = 24
_THUMBNAIL_ROW_HEIGHT = 108
_THUMBNAIL_COLUMN_WIDTH = 115


class SearchController:
    def __init__(self, app):
        self.app = app
        self.character_thumbnails = CharacterThumbnailLoader(app)
        self._cached_queries = {prefix: None for prefix in _SEARCH_PREFIXES}
        self._search_thumbnail_paths = {
            prefix: {} for prefix in _SEARCH_PREFIXES
        }
        self._lazy_queue_generations = {
            prefix: None for prefix in _SEARCH_PREFIXES
        }
        self._virtual_views = {prefix: None for prefix in _SEARCH_PREFIXES}
        self._page_request_ids = {prefix: 0 for prefix in _SEARCH_PREFIXES}
        self._query_inflight_generation = {
            prefix: None for prefix in _SEARCH_PREFIXES
        }

    def _mode_for_prefix(self, prefix):
        if prefix == "scene_":
            return self.app.scene_view_mode
        if prefix == "prop_":
            return self.app.prop_view_mode
        return "list"

    @staticmethod
    def _metric_name(prefix, suffix):
        domain = "global_" if prefix == "" else prefix
        return f"{domain}{suffix}"


    @staticmethod
    def _containers_for_prefix(prefix):
        if prefix == "scene_":
            return "scene_results_parent", "scene_thumbnails_parent"
        if prefix == "prop_":
            return "prop_results_parent", "prop_thumbnails_parent"
        return "search_results", None

    @staticmethod
    def _table_tag(prefix, mode):
        if not prefix:
            return "search_results_table"
        kind = "thumbnails" if mode == "thumbnail" else "results"
        return f"{prefix}{kind}_table"

    @staticmethod
    def _item_tag(prefix, mode, item_id):
        if not prefix:
            return f"search_item_{item_id}"
        kind = "thumb" if mode == "thumbnail" else "item"
        return f"{prefix}{kind}_{item_id}"

    @staticmethod
    def _item_data(row):
        item_id, name, size, asset_hash, key = row
        return {
            "id": item_id,
            "full_path": name,
            "size": size,
            "hash": asset_hash,
            "key": key,
        }

    @staticmethod
    def _tag_belongs_to_prefix(prefix, tag):
        if not isinstance(tag, str):
            return False
        if not prefix:
            return tag.startswith("search_item_")
        return tag.startswith(f"{prefix}item_") or tag.startswith(
            f"{prefix}thumb_"
        )

    @staticmethod
    def _snapshot_thumbnail_paths():
        thumbnail_dir = Config.get_thumbnail_dir()
        paths = {}
        try:
            with os.scandir(thumbnail_dir) as entries:
                for entry in entries:
                    if entry.name.lower().endswith(".png") and entry.is_file():
                        paths[entry.name[:-4]] = os.path.abspath(entry.path)
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            return {}
        return paths

    def _query_search_results(self, database, prefix, query):
        query_started_at = time.perf_counter() if Config.PROFILE else None
        if prefix == "":
            total_count = database.count_assets(query)
            rows = tuple(
                database.search_assets(
                    query,
                    limit=SEARCH_LIST_WINDOW_ROWS,
                    offset=0,
                )
            )
        elif prefix == "scene_":
            rows = tuple(database.search_scenes(query))
            total_count = len(rows)
        elif prefix == "prop_":
            rows = tuple(database.search_props(query))
            total_count = len(rows)
        else:
            raise ValueError(f"Unknown search prefix: {prefix}")
        query_elapsed = (
            time.perf_counter() - query_started_at
            if query_started_at is not None
            else None
        )

        thumbnail_paths = self._snapshot_thumbnail_paths() if prefix else {}
        return rows, thumbnail_paths, query_elapsed, total_count

    def request_results(self, prefix, query="", *, reuse_rows=False):
        if prefix not in _SEARCH_PREFIXES:
            raise ValueError(f"Unknown search prefix: {prefix}")
        started_at = time.perf_counter() if Config.PROFILE else None

        mode = self._mode_for_prefix(prefix)
        cached = (
            reuse_rows
            and query == self.app.search_queries[prefix]
            and self._cached_queries[prefix] == query
        )
        self.app.search_request_ids[prefix] += 1
        generation = self.app.search_request_ids[prefix]
        self.app.search_queries[prefix] = query

        if prefix == "" and not query:
            self._apply_search_results(
                prefix,
                query,
                mode,
                generation,
                (),
                {},
                cancelled=True,
                started_at=started_at,
            )
            return

        if cached:
            rows = self.app.search_rows[prefix]
            thumbnail_paths = self._search_thumbnail_paths[prefix]
            self.app._queue_ui_task(
                lambda: self._apply_search_results(
                    prefix,
                    query,
                    mode,
                    generation,
                    rows,
                    thumbnail_paths,
                    started_at=started_at,
                )
            )
            return

        database = self.app.db
        if not database:
            self.app._queue_ui_task(
                lambda: self._apply_search_results(
                    prefix,
                    query,
                    mode,
                    generation,
                    (),
                    {},
                    database_ready=False,
                    started_at=started_at,
                )
            )
            return

        self._query_inflight_generation[prefix] = generation
        future = self.app.executor.submit(
            self._query_search_results, database, prefix, query
        )

        def complete(done):
            try:
                rows, thumbnail_paths, query_elapsed, total_count = done.result()
            except Exception:
                rows, thumbnail_paths, query_elapsed, total_count = (), {}, None, 0
            self.app._queue_ui_task(
                lambda: self._apply_search_results(
                    prefix,
                    query,
                    mode,
                    generation,
                    rows,
                    thumbnail_paths,
                    started_at=started_at,
                    query_elapsed=query_elapsed,
                    total_count=total_count,
                )
            )

        future.add_done_callback(complete)

    def on_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("search_input").strip()
        self.request_results("", query, reuse_rows=False)

    def on_scene_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("scene_search_input").strip()
        self.request_results("scene_", query, reuse_rows=False)

    def on_prop_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("prop_search_input").strip()
        self.request_results("prop_", query, reuse_rows=False)

    def clear_search(self, *args):
        dpg.set_value("search_input", "")
        self.request_results("", "", reuse_rows=False)

    def clear_scene_search(self, *args):
        dpg.set_value("scene_search_input", "")
        self.request_results("scene_", "", reuse_rows=False)

    def clear_prop_search(self, *args):
        dpg.set_value("prop_search_input", "")
        self.request_results("prop_", "", reuse_rows=False)

    def on_view_mode_change(self, sender, app_data, user_data):
        prefix = user_data
        new_mode = (
            "thumbnail" if app_data == i18n("label_view_thumbnail") else "list"
        )
        if prefix == "scene_":
            self.app.scene_view_mode = new_mode
        elif prefix == "prop_":
            self.app.prop_view_mode = new_mode
        else:
            raise ValueError(f"Unknown search prefix: {prefix}")

        query = dpg.get_value(f"{prefix}search_input").strip()
        self.request_results(prefix, query, reuse_rows=True)

    def reset_search_state(self):
        for prefix in _SEARCH_PREFIXES:
            self._query_inflight_generation[prefix] = None
            self.app.search_request_ids[prefix] += 1
            generation = self.app.search_request_ids[prefix]
            self.app.search_queries[prefix] = ""
            self._apply_search_results(
                prefix,
                "",
                self._mode_for_prefix(prefix),
                generation,
                (),
                {},
                cancelled=(prefix == ""),
                database_ready=(prefix == ""),
            )
            self._cached_queries[prefix] = None

    def _retire_search_domain(self, prefix):
        list_container, thumbnail_container = self._containers_for_prefix(prefix)
        for container in (list_container, thumbnail_container):
            if container and dpg.does_item_exist(container):
                dpg.delete_item(container, children_only=True)

        old_tags = set(self.app.search_item_tags.get(prefix, ()))
        old_tags.update(
            tag
            for tag in tuple(self.app.file_item_data)
            if self._tag_belongs_to_prefix(prefix, tag)
        )
        for tag in old_tags:
            self.app.file_item_data.pop(tag, None)

        if self.app.last_selected in old_tags or self._tag_belongs_to_prefix(
            prefix, self.app.last_selected
        ):
            self.app.last_selected = None

        self.app.search_item_tags[prefix] = []
        self.app.pending_search_builds[prefix] = None
        self.app.lazy_thumb_queues[prefix] = []
        self._lazy_queue_generations[prefix] = None
        for key in tuple(self.app.search_thumbnail_inflight):
            if key[0] == prefix:
                self.app.search_thumbnail_inflight.pop(key, None)
        if prefix in self.app.thumbnail_items:
            self.app.thumbnail_items[prefix] = []
        self._virtual_views[prefix] = None
        self._page_request_ids[prefix] += 1

    def _clear_virtual_window(self, prefix):
        old_tags = tuple(self.app.search_item_tags.get(prefix, ()))
        for tag in old_tags:
            self.app.file_item_data.pop(tag, None)
        if self.app.last_selected in old_tags:
            self.app.last_selected = None
        self.app.search_item_tags[prefix] = []
        self.app.lazy_thumb_queues[prefix] = []
        self._lazy_queue_generations[prefix] = None
        for key in tuple(self.app.search_thumbnail_inflight):
            if key[0] == prefix:
                self.app.search_thumbnail_inflight.pop(key, None)
        self.app.texture_registry.clear_domain(prefix)

    @staticmethod
    def _virtual_window_bounds(mode, total_count, scroll_y, columns):
        if mode == "thumbnail":
            first_grid_row = max(0, int(scroll_y / _THUMBNAIL_ROW_HEIGHT))
            start_grid_row = (
                first_grid_row // SEARCH_THUMBNAIL_WINDOW_STEP_ROWS
            ) * SEARCH_THUMBNAIL_WINDOW_STEP_ROWS
            start_grid_row = max(
                0, start_grid_row - SEARCH_THUMBNAIL_WINDOW_STEP_ROWS
            )
            start = start_grid_row * columns
            count = SEARCH_THUMBNAIL_WINDOW_GRID_ROWS * columns
            return start, min(total_count, start + count)

        first_row = max(0, int(scroll_y / _LIST_ROW_HEIGHT))
        start = (first_row // SEARCH_LIST_WINDOW_STEP) * SEARCH_LIST_WINDOW_STEP
        start = max(0, start - SEARCH_LIST_WINDOW_STEP)
        return start, min(total_count, start + SEARCH_LIST_WINDOW_ROWS)

    @staticmethod
    def _virtual_spacer_heights(mode, total_count, start, end, columns):
        if mode == "thumbnail":
            total_grid_rows = (total_count + columns - 1) // columns
            start_grid_row = start // columns
            end_grid_row = (end + columns - 1) // columns
            return (
                start_grid_row * _THUMBNAIL_ROW_HEIGHT,
                max(0, total_grid_rows - end_grid_row) * _THUMBNAIL_ROW_HEIGHT,
            )
        return start * _LIST_ROW_HEIGHT, max(0, total_count - end) * _LIST_ROW_HEIGHT

    def _render_virtual_rows(self, view, start, rows, *, auto_select=False):
        if not self._virtual_view_is_current(view):
            return
        prefix = view["prefix"]
        table = view["table"]
        if not dpg.does_item_exist(table):
            return

        scroll_y = dpg.get_y_scroll(view["target"])
        self._clear_virtual_window(prefix)
        dpg.delete_item(table, children_only=True, slot=1)
        top_height, bottom_height = self._virtual_spacer_heights(
            view["mode"],
            view["total_count"],
            start,
            start + len(rows),
            view["columns"],
        )
        dpg.configure_item(view["top_spacer"], height=max(1, top_height))
        dpg.configure_item(view["bottom_spacer"], height=max(1, bottom_height))
        try:
            dpg.set_y_scroll(view["target"], scroll_y)
        except Exception:
            pass

        view["start"] = start
        view["end"] = start + len(rows)
        view["window_rows"] = tuple(rows)
        view["requested_start"] = start
        self.app.pending_search_builds[prefix] = {
            "prefix": prefix,
            "query": view["query"],
            "mode": view["mode"],
            "generation": view["generation"],
            "rows": tuple(rows),
            "thumbnail_paths": view["thumbnail_paths"],
            "table": table,
            "target": view["target"],
            "columns": view["columns"],
            "row_offset": start,
            "index": 0,
            "decode_tasks": [],
            "auto_select": auto_select,
            "auto_selected": False,
            "select_index": view.pop("pending_select_index", None),
            "started_at": view["started_at"],
            "first_item_recorded": False,
        }

    def _virtual_view_is_current(self, view):
        prefix = view["prefix"]
        return (
            self._virtual_views.get(prefix) is view
            and self.app.search_request_ids.get(prefix) == view["generation"]
            and self.app.search_queries.get(prefix) == view["query"]
            and self._mode_for_prefix(prefix) == view["mode"]
        )


    def _apply_search_results(
        self,
        prefix,
        query,
        mode,
        generation,
        rows,
        thumbnail_paths,
        *,
        cancelled=False,
        database_ready=True,
        started_at=None,
        query_elapsed=None,
        total_count=None,
    ):
        if self.app.search_request_ids.get(prefix) != generation:
            return
        if self.app.search_queries.get(prefix) != query:
            return
        if self._mode_for_prefix(prefix) != mode:
            return
        if self._query_inflight_generation[prefix] == generation:
            self._query_inflight_generation[prefix] = None

        self._retire_search_domain(prefix)
        self.app.texture_registry.clear_domain(prefix)
        immutable_rows = tuple(rows)
        immutable_paths = dict(thumbnail_paths)
        self.app.search_rows[prefix] = immutable_rows
        self._cached_queries[prefix] = (
            query if database_ready and not cancelled else None
        )
        self._search_thumbnail_paths[prefix] = immutable_paths
        if Config.PROFILE and database_ready and not cancelled:
            if query_elapsed is not None:
                Monitor.record(
                    self._metric_name(prefix, "search_query_seconds"),
                    query_elapsed,
                )
            Monitor.record(
                self._metric_name(prefix, "search_row_count"),
                len(immutable_rows),
            )

        list_container, thumbnail_container = self._containers_for_prefix(prefix)
        if prefix == "":
            if dpg.does_item_exist("browse_group"):
                dpg.configure_item("browse_group", show=cancelled)
            if dpg.does_item_exist("search_group"):
                dpg.configure_item("search_group", show=not cancelled)
            if cancelled:
                return
        else:
            if dpg.does_item_exist(list_container):
                dpg.configure_item(list_container, show=(mode == "list"))
            if dpg.does_item_exist(thumbnail_container):
                dpg.configure_item(
                    thumbnail_container, show=(mode == "thumbnail")
                )

        target = (
            thumbnail_container
            if mode == "thumbnail" and thumbnail_container
            else list_container
        )
        if not database_ready:
            dpg.add_text(
                i18n("label_db_not_ready"),
                parent=target,
                color=[200, 120, 120],
            )
            return

        result_count = len(immutable_rows) if total_count is None else total_count
        if result_count == 0:
            empty_label = {
                "": "label_no_assets",
                "scene_": "label_no_scenes",
                "prop_": "label_no_props",
            }[prefix]
            dpg.add_text(i18n(empty_label), parent=target)
            return

        display_rows = immutable_rows
        display_count = result_count
        if mode == "thumbnail":
            display_rows = tuple(
                row for row in immutable_rows if row[3] in immutable_paths
            )
            display_count = len(display_rows)
            if not display_rows:
                self.app.thumbnail_items[prefix] = []
                dpg.add_text(
                    i18n("msg_no_thumbnails_hint"),
                    parent=target,
                    color=[255, 255, 0],
                )
                return

        table_tag = self._table_tag(prefix, mode)
        columns = 1
        if mode == "thumbnail":
            try:
                width = dpg.get_item_rect_size(target)[0]
            except Exception:
                width = 0
            if width <= 0:
                width = 500
            columns = max(1, int(width / _THUMBNAIL_COLUMN_WIDTH))
            self.app.thumbnail_columns[prefix] = columns
            self.app.thumbnail_items[prefix] = display_rows

        top_spacer = f"{table_tag}_top_spacer"
        bottom_spacer = f"{table_tag}_bottom_spacer"
        dpg.add_spacer(parent=target, tag=top_spacer, height=1)

        with dpg.table(
            tag=table_tag,
            parent=target,
            header_row=False,
            clipper=True,
            policy=dpg.mvTable_SizingStretchProp,
        ):
            for _ in range(columns):
                dpg.add_table_column()
        dpg.add_spacer(parent=target, tag=bottom_spacer, height=1)

        auto_select = bool(query) and (
            prefix == "" or mode == "list"
        )
        view = {
            "prefix": prefix,
            "query": query,
            "mode": mode,
            "generation": generation,
            "thumbnail_paths": immutable_paths,
            "table": table_tag,
            "target": target,
            "columns": columns,
            "total_count": display_count,
            "all_rows": display_rows if prefix else None,
            "top_spacer": top_spacer,
            "bottom_spacer": bottom_spacer,
            "start": 0,
            "end": 0,
            "requested_start": 0,
            "started_at": (
                started_at
                if started_at is not None
                else (time.perf_counter() if Config.PROFILE else None)
            ),
        }
        self._virtual_views[prefix] = view
        start, end = self._virtual_window_bounds(mode, display_count, 0, columns)
        initial_rows = display_rows[: end - start]
        self._render_virtual_rows(
            view,
            start,
            initial_rows,
            auto_select=auto_select,
        )

    def _build_is_current(self, job):
        prefix = job["prefix"]
        return (
            self.app.pending_search_builds.get(prefix) is job
            and self.app.search_request_ids.get(prefix) == job["generation"]
            and self.app.search_queries.get(prefix) == job["query"]
            and self._mode_for_prefix(prefix) == job["mode"]
        )

    def _record_build_metric(self, job, suffix):
        if (
            not Config.PROFILE
            or job["started_at"] is None
            or not self._build_is_current(job)
        ):
            return
        Monitor.record(
            self._metric_name(job["prefix"], suffix),
            time.perf_counter() - job["started_at"],
        )

    def _record_first_item_metric(self, job):
        if job["first_item_recorded"]:
            return
        job["first_item_recorded"] = True
        self._record_build_metric(job, "search_first_item_seconds")


    def _build_list_chunk(self, job):
        rows = job["rows"]
        start = job["index"]
        end = min(len(rows), start + SEARCH_LIST_ROWS_PER_FRAME)
        prefix = job["prefix"]

        for row_index, row in enumerate(rows[start:end], start=start):
            item_id, name, _size, _asset_hash, _key = row
            data = self._item_data(row)
            tag = self._item_tag(prefix, "list", item_id)
            with dpg.table_row(
                parent=job["table"], height=_LIST_ROW_HEIGHT
            ) as table_row:
                dpg.add_selectable(
                    label=os.path.basename(name),
                    parent=table_row,
                    callback=self.app.on_file_click,
                    user_data=data,
                    span_columns=True,
                    height=_LIST_ROW_HEIGHT,
                    tag=tag,
                )
            self.app.file_item_data[tag] = data
            self.app.search_item_tags[prefix].append(tag)
            self._record_first_item_metric(job)
            if job["auto_select"] and not job["auto_selected"]:
                job["auto_selected"] = True
                self.app.on_file_click(tag, None, data)
            elif (
                job["select_index"]
                == job["row_offset"] + row_index
            ):
                self.app.on_file_click(tag, None, data)

        job["index"] = end

    def _build_thumbnail_chunk(self, job):
        rows = job["rows"]
        columns = job["columns"]
        start = job["index"]
        end = min(
            len(rows),
            start + SEARCH_THUMBNAIL_ROWS_PER_FRAME * columns,
        )
        prefix = job["prefix"]

        for row_start in range(start, end, columns):
            with dpg.table_row(
                parent=job["table"], height=_THUMBNAIL_ROW_HEIGHT
            ) as table_row:
                for column in range(columns):
                    index = row_start + column
                    if index >= len(rows):
                        dpg.add_spacer(
                            parent=table_row,
                            width=100,
                            height=100,
                        )
                        continue

                    row = rows[index]
                    item_id, name, _size, asset_hash, _key = row
                    data = self._item_data(row)
                    tag = self._item_tag(prefix, "thumbnail", item_id)
                    dpg.add_image_button(
                        "thumb_placeholder",
                        parent=table_row,
                        tag=tag,
                        width=100,
                        height=100,
                        background_color=[0, 0, 0, 0],
                        callback=self.app.on_file_click,
                        user_data=data,
                    )
                    self.app.file_item_data[tag] = data
                    self.app.search_item_tags[prefix].append(tag)
                    self._record_first_item_metric(job)
                    with dpg.tooltip(tag):
                        dpg.add_text(os.path.basename(name))

                    if (
                        job["select_index"]
                        == job["row_offset"] + index
                    ):
                        self.app.on_file_click(tag, None, data)

                    thumbnail_path = job["thumbnail_paths"].get(asset_hash)
                    if thumbnail_path:
                        job["decode_tasks"].append((thumbnail_path, tag))

        job["index"] = end

    def navigate_virtual(self, prefix, direction):
        """Move within the complete logical result set, not just visible widgets."""
        view = self._virtual_views.get(prefix)
        if not view or not self._virtual_view_is_current(view):
            return False
        tags = [
            tag
            for tag in self.app.search_item_tags.get(prefix, ())
            if dpg.does_item_exist(tag) and tag in self.app.file_item_data
        ]
        if not tags:
            return False

        selected = self.app.last_selected
        try:
            local_index = tags.index(selected)
        except ValueError:
            current_id = getattr(self.app, "current_asset_id", None)
            local_index = next(
                (
                    index
                    for index, row in enumerate(view.get("window_rows", ()))
                    if row[0] == current_id
                ),
                0,
            )
        logical_index = view["start"] + local_index
        target_index = max(
            0,
            min(view["total_count"] - 1, logical_index + direction),
        )
        if target_index == logical_index:
            return True

        if view["start"] <= target_index < view["end"]:
            relative_index = target_index - view["start"]
            if relative_index < len(tags):
                target_tag = tags[relative_index]
                data = self.app.file_item_data.get(target_tag)
                if data:
                    self.app.on_file_click(target_tag, None, data)
                    return True

        view["pending_select_index"] = target_index
        if view["mode"] == "thumbnail":
            scroll_y = (
                target_index // view["columns"]
            ) * _THUMBNAIL_ROW_HEIGHT
        else:
            scroll_y = target_index * _LIST_ROW_HEIGHT
        dpg.set_y_scroll(view["target"], scroll_y)
        self._update_virtual_window(prefix)
        return True

    def _build_target_is_shown(self, job):
        target = job["target"]
        if not dpg.is_item_shown(target):
            return False

        raw_tab = dpg.get_value("main_tabs")
        active_tab = (
            dpg.get_item_alias(raw_tab) if isinstance(raw_tab, int) else raw_tab
        )
        expected_tab = {
            "": "home_tab",
            "scene_": "scene_tab",
            "prop_": "prop_tab",
        }[job["prefix"]]
        if active_tab and active_tab != expected_tab:
            return False
        if (
            job["prefix"] == ""
            and dpg.does_item_exist("search_group")
            and not dpg.is_item_shown("search_group")
        ):
            return False
        return True

    def _request_paged_window(self, view, start, end):
        view["requested_start"] = start
        view["requested_end"] = end
        if view.get("page_inflight"):
            return

        database = self.app.db
        if not database:
            return
        view["page_inflight"] = True
        request_start = view["requested_start"]
        request_end = view["requested_end"]
        future = self.app.executor.submit(
            database.search_assets,
            view["query"],
            request_end - request_start,
            request_start,
        )

        def complete(done):
            try:
                rows = tuple(done.result())
            except Exception:
                rows = ()
            self.app._queue_ui_task(
                lambda: self._apply_paged_window(
                    view,
                    request_start,
                    rows,
                )
            )

        future.add_done_callback(complete)

    def _apply_paged_window(self, view, request_start, rows):
        if not self._virtual_view_is_current(view):
            return
        view["page_inflight"] = False
        if request_start != view["requested_start"]:
            self._request_paged_window(
                view,
                view["requested_start"],
                view["requested_end"],
            )
            return
        self.app.search_rows[view["prefix"]] = rows
        self._render_virtual_rows(view, request_start, rows)

    def _update_virtual_window(self, prefix):
        view = self._virtual_views.get(prefix)
        if not view or not self._virtual_view_is_current(view):
            return
        target = view["target"]
        if not dpg.does_item_exist(target) or not dpg.is_item_shown(target):
            return
        try:
            scroll_y = dpg.get_y_scroll(target)
        except Exception:
            return
        start, end = self._virtual_window_bounds(
            view["mode"],
            view["total_count"],
            scroll_y,
            view["columns"],
        )
        if start == view["start"] or start == view["requested_start"]:
            return

        if view["all_rows"] is None:
            self._request_paged_window(view, start, end)
            return
        self._render_virtual_rows(view, start, view["all_rows"][start:end])


    def process_pending_search_builds(self):
        for prefix in _SEARCH_PREFIXES:
            self._update_virtual_window(prefix)

        for prefix in _SEARCH_PREFIXES:
            job = self.app.pending_search_builds.get(prefix)
            if not job:
                continue
            if not self._build_is_current(job):
                if self.app.pending_search_builds.get(prefix) is job:
                    self.app.pending_search_builds[prefix] = None
                continue
            if not dpg.does_item_exist(job["target"]):
                continue
            if not self._build_target_is_shown(job):
                continue
            if not dpg.does_item_exist(job["table"]):
                self.app.pending_search_builds[prefix] = None
                continue

            if job["mode"] == "thumbnail":
                self._build_thumbnail_chunk(job)
            else:
                self._build_list_chunk(job)

            if job["index"] >= len(job["rows"]):
                if job["mode"] == "thumbnail":
                    self.app.lazy_thumb_queues[prefix] = list(
                        job["decode_tasks"]
                    )
                    self._lazy_queue_generations[prefix] = job["generation"]
                self._record_build_metric(job, "search_all_items_seconds")
                self.app.pending_search_builds[prefix] = None

    def _apply_search_thumbnail_batch(self, prefix, generation, batch_results):
        inflight_key = (prefix, generation)
        inflight = self.app.search_thumbnail_inflight.get(inflight_key, 0)
        remaining = max(0, inflight - 1)
        if remaining == 0:
            self.app.search_thumbnail_inflight.pop(inflight_key, None)
        else:
            self.app.search_thumbnail_inflight[inflight_key] = remaining

        if self.app.search_request_ids.get(prefix) != generation:
            return

        if Config.PROFILE:
            Monitor.record(
                self._metric_name(prefix, "thumbnail_inflight"),
                remaining,
            )
            decode_seconds = getattr(batch_results, "decode_seconds", None)
            if decode_seconds is not None:
                Monitor.record(
                    self._metric_name(prefix, "thumbnail_decode_seconds"),
                    decode_seconds,
                )
            with Monitor.time_block(
                self._metric_name(prefix, "thumbnail_apply_seconds")
            ):
                for image_tag, data in batch_results:
                    if dpg.does_item_exist(image_tag):
                        self.app.texture_registry.replace(
                            prefix, image_tag, data, 100, 100
                        )
            return

        for image_tag, data in batch_results:
            if dpg.does_item_exist(image_tag):
                self.app.texture_registry.replace(
                    prefix, image_tag, data, 100, 100
                )

    def _build_character_thumbnail_column_reflow(self):
        try:
            width = dpg.get_item_rect_size("character_outfits_panel")[0]
            expected_columns = max(
                1,
                int(max(width, 1) / (Config.CHARACTER_OUTFIT_IMAGE_SIZE + 40)),
            )
        except Exception:
            expected_columns = self.app.thumbnail_columns.get(
                "character_outfits", 0
            )

        if expected_columns == self.app.thumbnail_columns.get(
            "character_outfits", 0
        ):
            return False
        items = self.app.thumbnail_items.get("character_outfits", [])
        if not items or not self.app.current_character_id:
            return False
        self.app.character_controller.render_outfit_grid(
            self.app.current_character_id,
            items,
            self.app.thumbnail_request_ids.get("character_outfits", 0),
        )
        return True

    def _build_search_thumbnail_column_reflow(self, prefix):
        rows = self.app.search_rows.get(prefix, ())
        if not rows:
            return False
        container = f"{prefix}thumbnails_parent"
        if not dpg.does_item_exist(container):
            return False
        try:
            width = dpg.get_item_rect_size(container)[0]
        except Exception:
            width = 0
        if width <= 0:
            width = 500
        expected_columns = max(1, int(width / _THUMBNAIL_COLUMN_WIDTH))
        if expected_columns == self.app.thumbnail_columns.get(prefix, 0):
            return False
        self.request_results(
            prefix,
            self.app.search_queries[prefix],
            reuse_rows=True,
        )
        return True

    @staticmethod
    def _take_thumbnail_batch(queue):
        first_visible = None
        for index, (_path, image_tag) in enumerate(queue):
            try:
                if dpg.is_item_visible(image_tag):
                    first_visible = index
                    break
            except Exception:
                continue
        start = first_visible if first_visible is not None else 0
        end = min(len(queue), start + SEARCH_THUMBNAIL_DECODE_BATCH_SIZE)
        batch = queue[start:end]
        del queue[start:end]
        return batch

    def _submit_thumbnail_batches(self, prefix):
        generation = self.app.search_request_ids[prefix]
        inflight_key = (prefix, generation)
        queue = self.app.lazy_thumb_queues[prefix]
        queue_generation = self._lazy_queue_generations[prefix]
        if queue:
            if queue_generation is None:
                self._lazy_queue_generations[prefix] = generation
            elif queue_generation != generation:
                return
        inflight = self.app.search_thumbnail_inflight.get(inflight_key, 0)

        while queue and inflight < SEARCH_THUMBNAIL_MAX_INFLIGHT:
            tasks = self._take_thumbnail_batch(queue)
            if not tasks:
                break
            inflight += 1
            self.app.search_thumbnail_inflight[inflight_key] = inflight
            if Config.PROFILE:
                Monitor.record(
                    self._metric_name(prefix, "thumbnail_inflight"),
                    inflight,
                )
            try:
                self.app.thumbnail_service.load_search_thumbnails_batch_async(
                    tasks,
                    lambda results, p=prefix, g=generation: (
                        self._apply_search_thumbnail_batch(p, g, results)
                    ),
                )
            except Exception:
                self._apply_search_thumbnail_batch(prefix, generation, [])
                inflight = self.app.search_thumbnail_inflight.get(
                    inflight_key, 0
                )

    def process_lazy_thumbnails(self):
        raw_tab = dpg.get_value("main_tabs")
        active_tab = (
            dpg.get_item_alias(raw_tab) if isinstance(raw_tab, int) else raw_tab
        )

        if active_tab == "character_tab":
            now = time.time()
            if now - self.app.last_lazy_scan_time < self.app.lazy_scan_interval:
                return
            self.app.last_lazy_scan_time = now
            if self._build_character_thumbnail_column_reflow():
                return
            if self.character_thumbnails.process_visible(
                "character_outfits", 16
            ):
                return
            self.character_thumbnails.process_visible("character_icons", 12)
            return

        active_prefix = {
            "scene_tab": "scene_",
            "prop_tab": "prop_",
        }.get(active_tab)
        if not active_prefix:
            return
        if (
            self._cached_queries[active_prefix] is None
            and self._query_inflight_generation[active_prefix] is None
        ):
            query = dpg.get_value(f"{active_prefix}search_input").strip()
            self.request_results(active_prefix, query, reuse_rows=False)
            return
        if self._mode_for_prefix(active_prefix) != "thumbnail":
            return
        if self._build_search_thumbnail_column_reflow(active_prefix):
            return
        self._submit_thumbnail_batches(active_prefix)
