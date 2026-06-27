import sqlite3
import threading
import re
import os
import apsw
from collections import OrderedDict
from src.core.config import Config
from src.core.decryptor import get_db_hex_key
from src.core.utils import normalize_outfit_id


from src.core.monitor import Monitor


class MasterDatabase:
    def __init__(self, db_path=None, translation_service=None):
        self.db_path = db_path or Config.get_master_db_path()
        self.conn = self._connect(self.db_path)
        self.translation_service = translation_service

    @Monitor.time_func("master_db_connect")
    def _connect(self, db_path):
        if not db_path or not os.path.exists(db_path):
            return None
        try:
            # Try plain sqlite first, then fallback to encrypted
            try:
                conn = sqlite3.connect(db_path, check_same_thread=False)
                conn.execute("SELECT name FROM sqlite_master LIMIT 1")
                return conn
            except sqlite3.DatabaseError:
                conn = apsw.Connection(db_path)
                conn.pragma("hexkey", get_db_hex_key(Config.REGION))
                conn.cursor().execute("SELECT name FROM sqlite_master LIMIT 1")
                return conn
        except Exception:
            return None

    @Monitor.time_func("master_db_get_text")
    def get_text(self, category_id, index):
        if self.translation_service:
            translated = self.translation_service.get_text(category_id, index)
            if translated:
                return translated

        if not self.conn:
            return None
        try:
            # According to the provided C# logic:
            # 'id' is the category (6=chara, 14=dress, 59=mob)
            # 'index' is the specific ID within that category
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT text FROM text_data WHERE id = ? AND [index] = ?",
                (category_id, index),
            )
            row = cursor.fetchone()
            if row:
                return row[0]

            # Fallback for Mob characters if it's a mob ID (usually higher range or different)
            if category_id == 6:
                cursor.execute(
                    "SELECT text FROM text_data WHERE id = 59 AND [index] = ?",
                    (index,),
                )
                row = cursor.fetchone()
                return row[0] if row else None

            return None
        except Exception as e:
            print(f"MasterDB query error: {e}")
            return None

    def get_character_name(self, chara_id):
        return self.get_text(6, int(chara_id))

    def get_dress_name(self, dress_id):
        return self.get_text(14, int(dress_id))

    def get_dress_data(self, dress_id):
        """
        Query dress data from dress_data table in master.mdb.
        Returns a dict with dress metadata (id, chara_id, body_type, body_type_sub, body_setting).
        Uses the outfit/dress ID to look up body type information.

        The dress_id is a 6-digit string (e.g., "000001") that should be converted
        to an integer (e.g., 1) when querying dress_data.id.
        """
        if not self.conn or not dress_id:
            return None
        try:
            dress_id = normalize_outfit_id(dress_id)
            cursor = self.conn.cursor()
            # Convert the full 6-digit outfit_id to integer for querying dress_data
            # e.g., "000001" → 1, "000011" → 11
            dress_id_int = int(dress_id)
            cursor.execute(
                "SELECT id, chara_id, body_type, body_type_sub, body_setting FROM dress_data WHERE id = ?",
                (dress_id_int,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": str(row[0]) if row[0] is not None else None,
                    "chara_id": str(row[1]) if row[1] is not None else None,
                    "body_type": str(row[2]) if row[2] is not None else None,
                    "body_type_sub": str(row[3]) if row[3] is not None else None,
                    "body_setting": str(row[4]) if row[4] is not None else None,
                }
            return None
        except Exception as e:
            print(f"MasterDB dress_data query error: {e}")
            return None

    def get_all_dress_data(self):
        """Return the dress metadata used to map 3D body assets to UI dresses."""
        if not self.conn:
            return []
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, chara_id, body_type, body_type_sub, body_setting FROM dress_data"
            )
            return [
                {
                    "id": str(row[0]) if row[0] is not None else None,
                    "chara_id": str(row[1]) if row[1] is not None else None,
                    "body_type": str(row[2]) if row[2] is not None else None,
                    "body_type_sub": str(row[3]) if row[3] is not None else None,
                    "body_setting": str(row[4]) if row[4] is not None else None,
                }
                for row in cursor.fetchall()
            ]
        except Exception as e:
            print(f"MasterDB dress list query error: {e}")
            return []

    def get_chara_data(self, chara_id):
        """
        Query character data from chara_data table in master.mdb.
        Returns a dict with character attributes (skin, height, socks, bust, sex, shape).
        Uses the 4-digit character ID.
        """
        if not self.conn:
            return None
        try:
            cursor = self.conn.cursor()
            # Query chara_data table using the 4-digit character ID
            cursor.execute(
                "SELECT skin, height, socks, bust, sex, shape FROM chara_data WHERE id = ?",
                (int(chara_id),),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "skin": str(row[0]) if row[0] is not None else None,
                    "height": str(row[1]) if row[1] is not None else None,
                    "socks": str(row[2]) if row[2] is not None else None,
                    "bust": str(row[3]) if row[3] is not None else None,
                    "sex": str(row[4]) if row[4] is not None else None,
                    "shape": str(row[5]) if row[5] is not None else None,
                }
            return None
        except Exception as e:
            print(f"MasterDB chara_data query error: {e}")
            return None

    def close(self):
        if self.conn:
            self.conn.close()


class UmaDatabase:
    def __init__(self, db_path=None, translation_service=None):
        self.db_path = db_path or Config.get_db_path()
        self.conn = self._connect(self.db_path)
        self._apply_read_pragmas()
        self.master_db = MasterDatabase(translation_service=translation_service)
        self._asset_info_by_id = OrderedDict()
        self._deps_by_from = None
        self._deps_by_to = None
        self._dep_graph_lock = threading.Lock()
        self._asset_info_cache_limit = 16384
        self._dress_icon_rows = None
        self._dress_icon_by_dress_id = {}

    def _connect(self, db_path):
        if not db_path:
            raise ValueError("Database path is empty.")

        if not Config.DB_ENCRYPTED:
            print(f"Connecting to plain database {db_path}...")
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.execute("SELECT name FROM sqlite_master LIMIT 1")
            return conn

        print(f"Connecting to encrypted database {db_path}...")
        return self._connect_encrypted(db_path)

    def _connect_encrypted(self, db_path):
        """Connect to an encrypted database using apsw and sqlite3mc."""
        try:
            hex_key = get_db_hex_key(Config.REGION)
            conn = apsw.Connection(db_path)

            # Prioritize chacha20 as it's the most common for recent UMA versions
            configs = [
                {"cipher": "chacha20", "page_size": 4096},
                {"cipher": "sqlcipher", "legacy": 4, "page_size": 4096},  # SQLCipher v4
                {"cipher": "sqlcipher", "legacy": 1, "page_size": 1024},  # SQLCipher v1
                {"cipher": "sqlcipher", "legacy": 2, "page_size": 1024},  # SQLCipher v2
                {"cipher": "sqlcipher", "legacy": 3, "page_size": 1024},  # SQLCipher v3
                {"cipher": "aes256cbc", "page_size": 4096},
                {"cipher": "aes256cbc", "page_size": 1024},
            ]

            cursor = conn.cursor()
            success = False

            for cfg in configs:
                try:
                    # Apply config
                    conn.pragma("cipher", cfg.get("cipher"))
                    if cfg.get("legacy") is not None:
                        conn.pragma("legacy", str(cfg["legacy"]))
                    conn.pragma("page_size", str(cfg["page_size"]))
                    conn.pragma("hexkey", hex_key)

                    # Test connection
                    cursor.execute("SELECT name FROM sqlite_master LIMIT 1")
                    success = True
                    break
                except (apsw.NotADBError, apsw.AuthError, apsw.ExecutionCompleteError):
                    continue

            if not success:
                raise ValueError(
                    f"Failed to decrypt database {db_path} with any known configurations."
                )

            return conn

        except Exception as e:
            print(f"Encrypted connection error: {e}")
            raise

    def _apply_read_pragmas(self):
        cursor = self.conn.cursor()
        # apsw.Connection doesn't have a direct cursor().execute() in the same way?
        # Actually it does, but we can also use conn.cursor().execute().
        pragmas = [
            "PRAGMA query_only=ON",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-32768",  # ~32MB page cache
        ]
        # mmap_size might not be supported or needed for encrypted?
        if not isinstance(self.conn, apsw.Connection):
            pragmas.append("PRAGMA mmap_size=268435456")

        for pragma in pragmas:
            try:
                cursor.execute(pragma)
            except (sqlite3.DatabaseError, apsw.Error):
                continue

    @staticmethod
    def _asset_cols(include_id=True):
        key_col = "e" if Config.DB_ENCRYPTED else "NULL AS e"
        cols = ["n", "l", "h", key_col]
        if include_id:
            cols.insert(0, "i")
        return ", ".join(cols)

    def load_index(self):
        """Parse database path structure with IDs"""
        print("Parsing database index...")
        cursor = self.conn.cursor()

        cols = self._asset_cols()
        cursor.execute(f"SELECT {cols} FROM a WHERE n IS NOT NULL AND n != ''")

        tree_data = {}
        count = 0
        for row in cursor:
            count += 1
            i_id, name, size, f_hash, key_val = row

            clean_path = name.lstrip("/")
            parts = clean_path.split("/")

            current = tree_data
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    # File item
                    entry = {
                        "_is_file": True,
                        "id": i_id,
                        "size": size,
                        "hash": f_hash,
                        "full_path": name,
                        "key": key_val,
                    }
                    if part in current:
                        # Handle collision if a directory has the same name as a file
                        if isinstance(current[part], dict) and not current[part].get(
                            "_is_file"
                        ):
                            current[part]["_file_entry"] = entry
                        else:
                            current[part] = entry
                    else:
                        current[part] = entry
                else:
                    # Directory item
                    if part not in current:
                        current[part] = {}
                    elif isinstance(current[part], dict) and current[part].get(
                        "_is_file"
                    ):
                        # Convert file to directory with _file_entry
                        file_info = current[part]
                        current[part] = {"_file_entry": file_info}
                    current = current[part]

        print(f"Parsing complete. Total assets: {count}")
        return tree_data

    def _ensure_dependency_graph(self, include_reverse=False):
        if self._deps_by_from is not None and (
            not include_reverse or self._deps_by_to is not None
        ):
            return

        with self._dep_graph_lock:
            if self._deps_by_from is not None and (
                not include_reverse or self._deps_by_to is not None
            ):
                return

            print(
                "Building in-memory dependency graph..."
                if include_reverse
                else "Building in-memory forward dependency graph..."
            )
            cursor = self.conn.cursor()
            cursor.execute("SELECT f, t, d FROM r WHERE d != '0'")
            deps_by_from = {}
            deps_by_to = {} if include_reverse else None

            for source_id, target_id, dep_type in cursor:
                src = int(source_id)
                tgt = int(target_id)
                rel = (tgt, dep_type)
                deps_by_from.setdefault(src, []).append(rel)
                if include_reverse:
                    deps_by_to.setdefault(tgt, []).append((src, dep_type))

            self._deps_by_from = deps_by_from
            if include_reverse:
                self._deps_by_to = deps_by_to
                print(
                    f"Dependency graph ready. from-keys={len(deps_by_from)}, to-keys={len(deps_by_to)}"
                )
            else:
                print(f"Forward dependency graph ready. from-keys={len(deps_by_from)}")

    def _cache_asset_info(self, asset_id, info):
        self._asset_info_by_id[asset_id] = info
        self._asset_info_by_id.move_to_end(asset_id)
        if len(self._asset_info_by_id) > self._asset_info_cache_limit:
            self._asset_info_by_id.popitem(last=False)

    def _get_asset_info(self, asset_id):
        """Fetch basic asset info (name, size, hash, key) and cache it"""
        key = int(asset_id)
        info = self._asset_info_by_id.get(key)
        if info is not None:
            self._asset_info_by_id.move_to_end(key)
            return info
        cursor = self.conn.cursor()
        cols = self._asset_cols(include_id=False)
        cursor.execute(f"SELECT {cols} FROM a WHERE i = ? LIMIT 1", (key,))
        row = cursor.fetchone()
        if row:
            self._cache_asset_info(key, row)
        return row

    def get_dependencies(self, asset_id):
        """Fetch forward dependencies"""
        self._ensure_dependency_graph()
        source_key = int(asset_id)
        rows = []
        for target_id, dep_type in self._deps_by_from.get(source_key, []):
            info = self._get_asset_info(target_id)
            if not info:
                continue
            name, size, f_hash, key_val = info
            rows.append((name, dep_type, target_id, size, f_hash, key_val))
        return rows

    def get_reverse_dependencies(self, asset_id):
        """Fetch reverse dependencies"""
        self._ensure_dependency_graph(include_reverse=True)
        target_key = int(asset_id)
        rows = []
        for source_id, dep_type in self._deps_by_to.get(target_key, []):
            info = self._get_asset_info(source_id)
            if not info:
                continue
            name, size, f_hash, key_val = info
            rows.append((name, dep_type, source_id, size, f_hash, key_val))
        return rows

    def search_assets(self, query, limit=500, offset=0):
        """Search assets via database LIKE query"""
        cursor = self.conn.cursor()
        cols = self._asset_cols()
        cursor.execute(
            f"SELECT {cols} FROM a WHERE n LIKE ? ORDER BY n LIMIT ? OFFSET ?",
            (f"%{query}%", limit, offset),
        )
        return cursor.fetchall()

    def get_all_recursive_dependencies(self, asset_id):
        """Recursively fetch all dependencies for an asset"""
        self._ensure_dependency_graph()
        start = int(asset_id)
        visited = set()
        stack = [start]
        results = []  # List of (hash, key)

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            info = self._get_asset_info(current)
            if info:
                name, size, f_hash, key_val = info
                if f_hash:
                    results.append((f_hash, key_val))
            for next_id, _dep_type in self._deps_by_from.get(current, []):
                if next_id not in visited:
                    stack.append(next_id)

        return results

    def search_scenes(self, query="", limit=None):
        """Search specifically for scene assets in 3d/env/"""
        cursor = self.conn.cursor()
        cols = self._asset_cols()
        excluded_filters = (
            "n NOT LIKE '%_cloth00/%' AND n NOT LIKE '%_cloth00' "
            "AND n NOT LIKE '%/ast_%' AND n NOT LIKE 'ast_%'"
        )
        if limit is None:
            cursor.execute(
                f"SELECT {cols} FROM a WHERE n LIKE ? AND n LIKE '3d/env/%' AND {excluded_filters}",
                (f"%{query}%",),
            )
        else:
            cursor.execute(
                f"SELECT {cols} FROM a WHERE n LIKE ? AND n LIKE '3d/env/%' AND {excluded_filters} LIMIT ?",
                (f"%{query}%", limit),
            )
        rows = cursor.fetchall()

        def asset_name_sort_key(row):
            _, name, *_ = row
            parent_dir = os.path.dirname(name.rstrip("/"))
            sort_name = os.path.basename(parent_dir) if parent_dir else name
            return (sort_name.casefold(), name.casefold())

        rows.sort(key=asset_name_sort_key)
        return rows

    def search_props(self, query="", limit=None):
        """Search specifically for prop assets in 3d/chara/prop, 3d/chara/toonprop, and 3d/chara/richprop"""
        cursor = self.conn.cursor()
        cols = self._asset_cols()
        excluded_filters = (
            "n NOT LIKE '%_cloth00/%' AND n NOT LIKE '%_cloth00' "
            "AND n NOT LIKE '%/ast_%' AND n NOT LIKE 'ast_%'"
        )
        conditions = [
            "n LIKE '3d/chara/prop/%'",
            "n LIKE '3d/chara/toonprop/%'",
            "n LIKE '3d/chara/richprop/%'",
        ]
        path_filter = f"({' OR '.join(conditions)})"

        if limit is None:
            cursor.execute(
                f"SELECT {cols} FROM a WHERE n LIKE ? AND {path_filter} AND {excluded_filters}",
                (f"%{query}%",),
            )
        else:
            cursor.execute(
                f"SELECT {cols} FROM a WHERE n LIKE ? AND {path_filter} AND {excluded_filters} LIMIT ?",
                (f"%{query}%", limit),
            )
        rows = cursor.fetchall()

        # Sort by the asset directory name, e.g. prop1811_00 for
        # 3d/chara/prop/prop1811_00/pfb_chr_prop1811_00.
        def prop_sort_key(row):
            _, name, *_ = row
            parent_dir = os.path.dirname(name.rstrip("/"))
            sort_name = os.path.basename(parent_dir) if parent_dir else name
            return (sort_name.casefold(), name.casefold())

        rows.sort(key=prop_sort_key)
        return rows

    def get_character_entries(self):
        """Return character logo assets, excluding placeholder character chr0000."""
        cursor = self.conn.cursor()
        cols = self._asset_cols()

        cursor.execute(
            f"""
            SELECT {cols}
            FROM a
            WHERE n LIKE 'chara/chr____/%'
              AND n NOT LIKE 'chara/chr0000/%'
            ORDER BY n
            """
        )

        rows = []
        for i_id, name, size, f_hash, key_val in cursor.fetchall():
            parts = name.split("/")
            if len(parts) < 3:
                continue

            dir_match = re.fullmatch(r"chr(\d+)", parts[1])
            file_match = re.fullmatch(r"chr_icon_(\d+)", parts[2])
            if not dir_match or not file_match:
                continue

            chara_id = dir_match.group(1)
            if chara_id != file_match.group(1):
                continue
            if chara_id == "0000":
                continue

            name_en = (
                self.master_db.get_character_name(chara_id) if self.master_db else None
            )

            rows.append(
                {
                    "id": i_id,
                    "chara_id": chara_id,
                    "chara_name": name_en or f"Chara {chara_id}",
                    "full_path": name,
                    "size": size,
                    "hash": f_hash,
                    "key": key_val,
                    "texture_name": parts[2],
                    "cache_name": parts[2],
                }
            )

        rows.sort(key=lambda x: int(x["chara_id"]))
        return rows

    def get_character_outfit_assets(self, chara_id):
        """Return stand and 3D-discoverable outfits for one character.

        UmaViewer lists both character-specific body prefabs and common body
        prefabs.  The latter have no stand illustration, so ``dress_data`` is
        used to associate their body type/subtype with a dress icon and name.
        """
        cursor = self.conn.cursor()
        cols = self._asset_cols()
        cursor.execute(
            f"""
            SELECT {cols}
            FROM a
            WHERE n LIKE ?
            ORDER BY n
            """,
            (f"chara/chr{chara_id}/chara_stand_{chara_id}_______",),
        )

        rows_by_outfit_id = {}
        for i_id, name, size, f_hash, key_val in cursor.fetchall():
            texture_name = name.split("/")[-1]
            outfit_match = re.fullmatch(
                rf"chara_stand_{re.escape(chara_id)}_(\d{{6}})", texture_name
            )
            outfit_id = outfit_match.group(1) if outfit_match else None

            dress_name = (
                self.master_db.get_dress_name(outfit_id)
                if self.master_db and outfit_id
                else None
            )

            if not outfit_id:
                continue
            stand_item = {
                "id": i_id,
                "chara_id": chara_id,
                "full_path": name,
                "size": size,
                "hash": f_hash,
                "key": key_val,
                "texture_name": texture_name,
                "cache_name": texture_name,
                "outfit_id": outfit_id,
                "dress_name": dress_name or f"Outfit {outfit_id}",
                "has_stand": True,
            }
            rows_by_outfit_id[outfit_id] = stand_item

        if not self.master_db:
            return list(rows_by_outfit_id.values())

        # Index actual body prefabs, matching UmaViewer's body-path based
        # discovery.  This avoids displaying database entries whose model is
        # absent in the selected game data.
        cursor.execute(
            f"""
            SELECT {self._asset_cols()} FROM a
            WHERE n LIKE '3d/chara/body/bdy%/pfb_bdy%'
              AND n NOT LIKE '%/clothes/%'
            ORDER BY n
            """
        )
        body_assets = {}
        for i_id, name, size, f_hash, key_val in cursor.fetchall():
            prefab_name = name.rsplit("/", 1)[-1]
            match = re.match(r"pfb_bdy(\d{4})_(\d{2})(?:_|$)", prefab_name)
            if not match:
                continue
            body_assets.setdefault(
                (match.group(1), match.group(2)),
                {"id": i_id, "full_path": name, "size": size, "hash": f_hash, "key": key_val},
            )

        dress_data = self.master_db.get_all_dress_data()
        dedicated_dresses = {}
        common_dresses = {}
        for dress in dress_data:
            dress_id = dress.get("id")
            body_type = (dress.get("body_type") or "").zfill(4)
            body_sub = (dress.get("body_type_sub") or "").zfill(2)
            if not dress_id or not body_type or not body_sub:
                continue

            # This reproduces UmaViewer.ListCostumes:
            # - character prefabs: first CostumeEntry for chara_id + subtype
            # - common prefabs: first CostumeEntry for body type + subtype
            # ``setdefault`` preserves master-data order, the equivalent of
            # UmaViewer's FirstOrDefault selection.
            if dress.get("chara_id") == str(chara_id):
                dedicated_dresses.setdefault(body_sub, dress)
            elif dress.get("chara_id") == "0":
                common_dresses.setdefault((body_type, body_sub), dress)

        for (body_type, body_sub), asset in body_assets.items():
            if body_type == str(chara_id).zfill(4):
                dress = dedicated_dresses.get(body_sub)
            else:
                dress = common_dresses.get((body_type, body_sub))
            if dress is None:
                continue

            # Keep the original master dress ID.  Export normalizes special
            # IDs when it builds paths, while names and cached translations
            # are keyed by the unmodified text_data[14] index.
            dress_id = dress["id"]
            item = {
                **asset,
                "chara_id": chara_id,
                "texture_name": None,
                "cache_name": None,
                "outfit_id": dress_id,
                "dress_name": self.master_db.get_dress_name(dress_id)
                or f"Outfit {dress_id}",
                "has_stand": False,
            }
            # Source-qualified keys keep a 3D card even when its dress ID
            # matches a stand illustration (for example 101 vs 000101).
            rows_by_outfit_id[f"3d:{dress_id}"] = item

            # Icon bundle names include a model ID that is not consistently
            # equal to dress_data.id.  This suffix lookup is the stable
            # association available in the game metadata.  UmaViewer's
            # broader Contains-based lookup is intentionally not used here:
            # it can overwrite unrelated costume entries.
            icon_row = self._get_dress_icon_for_dress_id(dress_id)
            if icon_row:
                _, icon_path, _, icon_hash, icon_key = icon_row
                icon_name = icon_path.rsplit("/", 1)[-1]
                item.update(
                    {
                        "icon_hash": icon_hash,
                        "icon_key": icon_key,
                        "icon_texture_name": icon_name,
                        "icon_cache_name": icon_name,
                    }
                )

        # A 3D-only card is represented by its dress icon.  Suppress the
        # rare model-only entry for which the game has no matching icon;
        # otherwise the UI would need an empty stand-image placeholder.
        visible_items = [
            item
            for item in rows_by_outfit_id.values()
            if item.get("has_stand") or item.get("icon_texture_name")
        ]
        return sorted(
            visible_items,
            key=lambda item: (not item.get("has_stand", False), item["outfit_id"]),
        )

    def _get_dress_icon_for_dress_id(self, dress_id):
        """Return the first dress icon matching *dress_id*, cached per DB session."""
        if dress_id in self._dress_icon_by_dress_id:
            return self._dress_icon_by_dress_id[dress_id]

        if self._dress_icon_rows is None:
            cursor = self.conn.cursor()
            cursor.execute(
                f"""
                SELECT {self._asset_cols()} FROM a
                WHERE n LIKE 'outgame/dress/dress_%'
                ORDER BY n
                """
            )
            self._dress_icon_rows = cursor.fetchall()

        # Equivalent to the prior SQL LIKE pattern ``dress_%{dress_id}_%``.
        # In SQL LIKE, each ``_`` is a one-character wildcard, including the
        # final character after the dress ID.
        pattern = re.compile(
            rf"^outgame/dress/dress..*{re.escape(str(dress_id))}..*$"
        )
        icon_row = next(
            (row for row in self._dress_icon_rows if pattern.match(row[1])),
            None,
        )
        self._dress_icon_by_dress_id[dress_id] = icon_row
        return icon_row

    def get_asset_by_path(self, logical_path):
        cursor = self.conn.cursor()
        cols = self._asset_cols()
        cursor.execute(f"SELECT {cols} FROM a WHERE n = ? LIMIT 1", (logical_path,))
        row = cursor.fetchone()
        if not row:
            return None

        i_id, name, size, f_hash, key_val = row
        return {
            "id": i_id,
            "full_path": name,
            "size": size,
            "hash": f_hash,
            "key": key_val,
        }

    def get_assets_by_prefix(self, logical_prefix):
        cursor = self.conn.cursor()
        cols = self._asset_cols()
        cursor.execute(
            f"SELECT {cols} FROM a WHERE n LIKE ? ORDER BY n",
            (f"{logical_prefix}%",),
        )

        rows = []
        for i_id, name, size, f_hash, key_val in cursor.fetchall():
            rows.append(
                {
                    "id": i_id,
                    "full_path": name,
                    "size": size,
                    "hash": f_hash,
                    "key": key_val,
                }
            )
        return rows

    def debug_find_related_paths(self, category, chara_id, outfit_id, limit=40):
        outfit_id = normalize_outfit_id(outfit_id)
        cursor = self.conn.cursor()
        outfit_main = outfit_id[:4] if outfit_id else ""
        outfit_suffix = outfit_id[-2:] if outfit_id and len(outfit_id) >= 6 else ""
        if outfit_suffix == "01":
            outfit_suffix = "00"

        patterns = []
        if category == "body":
            patterns = [
                f"3d/chara/body/%{outfit_main}_{outfit_suffix}%",
                f"3d/chara/body/%{outfit_main}%",
                f"3d/chara/body/%{outfit_suffix}%",
            ]
        elif category == "head":
            patterns = [
                f"3d/chara/head/%{chara_id}_{outfit_suffix}%",
                f"3d/chara/head/%{chara_id}%",
                f"3d/chara/head/%{outfit_suffix}%",
            ]
        elif category == "tail":
            patterns = [
                f"3d/chara/tail/%{outfit_main}_{outfit_suffix}%",
                f"3d/chara/tail/%{outfit_main}%",
                f"3d/chara/tail/%{outfit_suffix}%",
            ]

        seen = set()
        results = []
        for pattern in patterns:
            try:
                cursor.execute(
                    "SELECT n FROM a WHERE n LIKE ? ORDER BY n LIMIT ?",
                    (pattern, limit),
                )
                for row in cursor.fetchall():
                    path = row[0]
                    if path in seen:
                        continue
                    seen.add(path)
                    results.append(path)
            except Exception:
                continue
        return results[:limit]

    def find_character_component_candidates(
        self, category, chara_id, outfit_id, is_mini=False
    ):
        outfit_id = normalize_outfit_id(outfit_id)
        cursor = self.conn.cursor()
        outfit_main = outfit_id[:4] if outfit_id else ""
        outfit_suffix = outfit_id[-2:] if outfit_id and len(outfit_id) >= 6 else ""
        if outfit_suffix == "01":
            outfit_suffix = "00"

        if is_mini:
            if category == "body":
                patterns = [
                    f"3d/chara/mini/body/mbdy{outfit_main}_%/pfb_mbdy{outfit_main}_%",
                    f"3d/chara/mini/body/mbdy{chara_id}_%/pfb_mbdy{chara_id}_%",
                ]
            elif category == "head":
                patterns = [
                    f"3d/chara/mini/head/mchr{chara_id}_%/pfb_mchr{chara_id}_%_hair",
                    f"3d/chara/mini/head/mchr{chara_id}_%/pfb_mchr{chara_id}_%",
                ]
            elif category == "tail":
                patterns = [
                    f"3d/chara/mini/tail/mtail{outfit_main}_%/pfb_mtail{outfit_main}_%",
                    f"3d/chara/mini/tail/mtail{chara_id}_%/pfb_mtail{chara_id}_%",
                    f"3d/chara/mini/tail/tail{outfit_main}_%/pfb_tail{outfit_main}_%",
                    f"3d/chara/mini/tail/tail{chara_id}_%/pfb_tail{chara_id}_%",
                ]
            else:
                patterns = []
        elif category == "body":
            patterns = [
                f"3d/chara/body/bdy{chara_id}_%/pfb_bdy{chara_id}_%",
                f"3d/chara/body/bdy{outfit_main}_%/pfb_bdy{outfit_main}_%",
            ]
        elif category == "head":
            patterns = [
                f"3d/chara/head/chr{chara_id}_%/pfb_chr{chara_id}_%",
            ]
        elif category == "tail":
            patterns = [
                f"3d/chara/tail/tail{outfit_main}_%/pfb_tail{outfit_main}_%",
                f"3d/chara/tail/tail{chara_id}_%/pfb_tail{chara_id}_%",
            ]
        else:
            patterns = []

        seen = set()
        candidates = []
        for pattern in patterns:
            cursor.execute(
                f"SELECT {self._asset_cols()} FROM a WHERE n LIKE ? ORDER BY n",
                (pattern,),
            )
            for i_id, name, size, f_hash, key_val in cursor.fetchall():
                if name in seen:
                    continue
                seen.add(name)
                name_base = name.rsplit("/", 1)[-1]
                suffix_match = re.search(r"_(\d{2})$", name_base)
                suffix = suffix_match.group(1) if suffix_match else ""
                candidates.append(
                    {
                        "id": i_id,
                        "full_path": name,
                        "size": size,
                        "hash": f_hash,
                        "key": key_val,
                        "suffix": suffix,
                        "preferred": 0
                        if suffix == outfit_suffix
                        else 1
                        if suffix == "00"
                        else 2,
                    }
                )

        candidates.sort(
            key=lambda item: (item["preferred"], item["suffix"], item["full_path"])
        )
        return candidates

    def get_all_animator_assets(self, categories=None):
        """Retrieves all asset info for specified categories (scene, prop)."""
        cursor = self.conn.cursor()
        cols = self._asset_cols()

        query_base = f"SELECT {cols} FROM a WHERE "
        conditions = []

        # Define 3D-related path filters
        scene_filter = "n LIKE '3d/env/%'"
        prop_filters = "(n LIKE '3d/chara/prop/%' OR n LIKE '3d/chara/toonprop/%' OR n LIKE '3d/chara/richprop/%')"

        if categories is None or "all" in categories:
            # "All" now specifically means Scenes + Props to avoid scanning 300k+ non-3D assets
            conditions.append(f"({scene_filter} OR {prop_filters})")
        else:
            if "scene" in categories:
                conditions.append(scene_filter)
            if "prop" in categories:
                conditions.append(prop_filters)

        if not conditions:
            return []

        cursor.execute(f"{query_base} ({' OR '.join(conditions)})")
        return cursor.fetchall()

    def close(self):
        self._asset_info_by_id.clear()
        self._deps_by_from = None
        self._deps_by_to = None
        if self.master_db:
            self.master_db.close()
        self.conn.close()

    def get_key_by_hash(self, f_hash):
        """Quick look up for decryption key by file hash."""
        if not Config.DB_ENCRYPTED:
            return None
        # Note: _asset_info_by_id is keyed by ID, not hash.
        # But we can use a separate small cache or just query.
        cursor = self.conn.cursor()
        cursor.execute("SELECT e FROM a WHERE h = ? LIMIT 1", (f_hash,))
        row = cursor.fetchone()
        return row[0] if row else None
