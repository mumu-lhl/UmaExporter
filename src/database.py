import sqlite3
import threading
import os
import apsw
from src.constants import Config
from src.decryptor import get_db_hex_key


class UmaDatabase:
    def __init__(self, db_path=None):
        self.db_path = db_path or Config.get_db_path()
        self.conn = self._connect(self.db_path)
        self._apply_read_pragmas()
        self._asset_info_by_id = {}
        self._deps_by_from = None
        self._deps_by_to = None
        self._dep_graph_lock = threading.Lock()

    def _connect(self, db_path):
        if not db_path:
            raise ValueError("Database path is empty.")

        # Try standard sqlite3 first
        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro",
                uri=True,
                check_same_thread=False,
                isolation_level=None,
                cached_statements=256,
            )
            # Verify it's actually readable
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master LIMIT 1")
            Config.DB_ENCRYPTED = False
            return conn
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            # If standard fails, try encrypted with apsw
            print(
                f"Standard SQLite failed for {db_path}, trying encrypted with apsw..."
            )
            conn = self._connect_encrypted(db_path)
            Config.DB_ENCRYPTED = True
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
            "PRAGMA cache_size=-131072",  # ~128MB page cache
        ]
        # mmap_size might not be supported or needed for encrypted?
        if not isinstance(self.conn, apsw.Connection):
            pragmas.append("PRAGMA mmap_size=268435456")

        for pragma in pragmas:
            try:
                cursor.execute(pragma)
            except (sqlite3.DatabaseError, apsw.Error):
                continue

    def load_index(self):
        """Parse database path structure with IDs"""
        print("Parsing database index...")
        cursor = self.conn.cursor()

        # Dynamically include 'e' (key) column only if the DB is encrypted
        cols = "i, n, l, h, e" if Config.DB_ENCRYPTED else "i, n, l, h, NULL as e"
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
                    self._asset_info_by_id[str(i_id)] = (name, size, f_hash, key_val)
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

    def _ensure_dependency_graph(self):
        if self._deps_by_from is not None and self._deps_by_to is not None:
            return

        with self._dep_graph_lock:
            if self._deps_by_from is not None and self._deps_by_to is not None:
                return

            print("Building in-memory dependency graph...")
            cursor = self.conn.cursor()
            cursor.execute("SELECT f, t, d FROM r WHERE d != '0'")
            deps_by_from = {}
            deps_by_to = {}

            for source_id, target_id, dep_type in cursor:
                src = str(source_id)
                tgt = str(target_id)
                rel = (tgt, dep_type)
                deps_by_from.setdefault(src, []).append(rel)
                deps_by_to.setdefault(tgt, []).append((src, dep_type))

            self._deps_by_from = deps_by_from
            self._deps_by_to = deps_by_to
            print(
                f"Dependency graph ready. from-keys={len(deps_by_from)}, to-keys={len(deps_by_to)}"
            )

    def _get_asset_info(self, asset_id):
        key = str(asset_id)
        info = self._asset_info_by_id.get(key)
        if info is not None:
            return info
        cursor = self.conn.cursor()
        cols = "n, l, h, e" if Config.DB_ENCRYPTED else "n, l, h"
        cursor.execute(f"SELECT {cols} FROM a WHERE i = ? LIMIT 1", (key,))
        row = cursor.fetchone()
        if row:
            if not Config.DB_ENCRYPTED:
                row = (*row, None)  # Add None as key_val
            self._asset_info_by_id[key] = row
        return row

    def get_dependencies(self, asset_id):
        """Fetch forward dependencies"""
        self._ensure_dependency_graph()
        source_key = str(asset_id)
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
        self._ensure_dependency_graph()
        target_key = str(asset_id)
        rows = []
        for source_id, dep_type in self._deps_by_to.get(target_key, []):
            info = self._get_asset_info(source_id)
            if not info:
                continue
            name, size, f_hash, key_val = info
            rows.append((name, dep_type, source_id, size, f_hash, key_val))
        return rows

    def search_assets(self, query, limit=100):
        """Search assets via database LIKE query"""
        cursor = self.conn.cursor()
        cols = "i, n, l, h, e" if Config.DB_ENCRYPTED else "i, n, l, h, NULL as e"
        cursor.execute(
            f"SELECT {cols} FROM a WHERE n LIKE ? LIMIT ?", (f"%{query}%", limit)
        )
        return cursor.fetchall()

    def get_all_recursive_dependencies(self, asset_id):
        """Recursively fetch all dependencies for an asset"""
        self._ensure_dependency_graph()
        start = str(asset_id)
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
        cols = "i, n, l, h, e" if Config.DB_ENCRYPTED else "i, n, l, h, NULL as e"
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
        cols = "i, n, l, h, e" if Config.DB_ENCRYPTED else "i, n, l, h, NULL as e"
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

    def close(self):
        self.conn.close()

    def get_key_by_hash(self, f_hash):
        """Quick look up for decryption key by file hash."""
        if not Config.DB_ENCRYPTED:
            return None

        # Check cache first
        # Note: _asset_info_by_id is keyed by ID, not hash.
        # But we can use a separate small cache or just query.
        cursor = self.conn.cursor()
        cursor.execute("SELECT e FROM a WHERE h = ? LIMIT 1", (f_hash,))
        row = cursor.fetchone()
        return row[0] if row else None
