import sqlite3
import threading
import re
import os
import apsw
from collections import OrderedDict
from src.constants import Config
from src.decryptor import get_db_hex_key


class MasterDatabase:
    def __init__(self, db_path=None):
        self.db_path = db_path or Config.get_master_db_path()
        self.conn = self._connect(self.db_path)

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

    def get_text(self, category_id, index):
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

    def close(self):
        if self.conn:
            self.conn.close()


class UmaDatabase:
    def __init__(self, db_path=None):
        self.db_path = db_path or Config.get_db_path()
        self.conn = self._connect(self.db_path)
        self._apply_read_pragmas()
        self.master_db = MasterDatabase()
        self._asset_info_by_id = OrderedDict()
        self._deps_by_from = None
        self._deps_by_to = None
        self._dep_graph_lock = threading.Lock()
        self._asset_info_cache_limit = 16384

    def _connect(self, db_path):
        if not db_path:
            raise ValueError("Database path is empty.")

        # Always use encrypted connection with apsw as all data is now encrypted
        print(f"Connecting to encrypted database {db_path}...")
        conn = self._connect_encrypted(db_path)
        return conn

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
                except apsw.NotADBError, apsw.AuthError, apsw.ExecutionCompleteError:
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
            except sqlite3.DatabaseError, apsw.Error:
                continue

    def load_index(self):
        """Parse database path structure with IDs"""
        print("Parsing database index...")
        cursor = self.conn.cursor()

        # Dynamically include 'e' (key) column only if the DB is encrypted
        cols = "i, n, l, h, e"
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
        cols = "n, l, h, e"
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
        cols = "i, n, l, h, e"
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
        cols = "i, n, l, h, e"
        if limit is None:
            cursor.execute(
                f"SELECT {cols} FROM a WHERE n LIKE ? AND n LIKE '3d/env/%'",
                (f"%{query}%",),
            )
        else:
            cursor.execute(
                f"SELECT {cols} FROM a WHERE n LIKE ? AND n LIKE '3d/env/%' LIMIT ?",
                (f"%{query}%", limit),
            )
        return cursor.fetchall()

    def search_props(self, query="", limit=None):
        """Search specifically for prop assets in 3d/chara/prop, 3d/chara/toonprop, and 3d/chara/richprop"""
        cursor = self.conn.cursor()
        cols = "i, n, l, h, e"
        conditions = [
            "n LIKE '3d/chara/prop/%'",
            "n LIKE '3d/chara/toonprop/%'",
            "n LIKE '3d/chara/richprop/%'",
        ]
        path_filter = f"({' OR '.join(conditions)})"

        if limit is None:
            cursor.execute(
                f"SELECT {cols} FROM a WHERE n LIKE ? AND {path_filter}",
                (f"%{query}%",),
            )
        else:
            cursor.execute(
                f"SELECT {cols} FROM a WHERE n LIKE ? AND {path_filter} LIMIT ?",
                (f"%{query}%", limit),
            )
        return cursor.fetchall()

    def get_character_entries(self):
        """Return character logo assets, excluding placeholder character chr0000."""
        cursor = self.conn.cursor()
        cols = "i, n, l, h, e"

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
        """Return stand illustration assets for one character."""
        cursor = self.conn.cursor()
        cols = "i, n, l, h, e"
        cursor.execute(
            f"""
            SELECT {cols}
            FROM a
            WHERE n LIKE ?
            ORDER BY n
            """,
            (f"chara/chr{chara_id}/chara_stand_{chara_id}_______",),
        )

        rows = []
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

            rows.append(
                {
                    "id": i_id,
                    "chara_id": chara_id,
                    "full_path": name,
                    "size": size,
                    "hash": f_hash,
                    "key": key_val,
                    "texture_name": texture_name,
                    "cache_name": texture_name,
                    "outfit_id": outfit_id,
                    "dress_name": dress_name or f"Outfit {outfit_id}"
                    if outfit_id
                    else "Unknown",
                }
            )

        return rows

    def get_asset_by_path(self, logical_path):
        cursor = self.conn.cursor()
        cols = "i, n, l, h, e"
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
        cols = "i, n, l, h, e"
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

    def find_character_component_candidates(self, category, chara_id, outfit_id):
        cursor = self.conn.cursor()
        outfit_main = outfit_id[:4] if outfit_id else ""
        outfit_suffix = outfit_id[-2:] if outfit_id and len(outfit_id) >= 6 else ""
        if outfit_suffix == "01":
            outfit_suffix = "00"

        if category == "body":
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
                "SELECT i, n, l, h, e FROM a WHERE n LIKE ? ORDER BY n",
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
        cols = "i, n, l, h, e"

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
        # Note: _asset_info_by_id is keyed by ID, not hash.
        # But we can use a separate small cache or just query.
        cursor = self.conn.cursor()
        cursor.execute("SELECT e FROM a WHERE h = ? LIMIT 1", (f_hash,))
        row = cursor.fetchone()
        return row[0] if row else None
