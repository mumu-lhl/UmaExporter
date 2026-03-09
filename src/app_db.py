import sqlite3
import os
import threading
from src.constants import Config

class AppDatabase:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AppDatabase, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.db_path = Config.get_app_db_path()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._create_tables()
        self._initialized = True

    def _create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS thumbnails (
                asset_hash TEXT PRIMARY KEY,
                thumbnail_path TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def get_thumbnail(self, asset_hash):
        """Returns the thumbnail path for the given asset hash, if it exists."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT thumbnail_path FROM thumbnails WHERE asset_hash = ?", (asset_hash,))
        row = cursor.fetchone()
        if row:
            path = row[0]
            if os.path.exists(path):
                return path
            else:
                # Cleanup orphaned record
                self.remove_thumbnail(asset_hash)
        return None

    def set_thumbnail(self, asset_hash, thumbnail_path):
        """Sets or updates the thumbnail path for the given asset hash."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO thumbnails (asset_hash, thumbnail_path, created_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (asset_hash, thumbnail_path))
        self.conn.commit()

    def remove_thumbnail(self, asset_hash):
        """Removes the thumbnail record for the given asset hash."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT thumbnail_path FROM thumbnails WHERE asset_hash = ?", (asset_hash,))
        row = cursor.fetchone()
        if row and os.path.exists(row[0]):
            try:
                os.remove(row[0])
            except OSError:
                pass
        
        cursor.execute("DELETE FROM thumbnails WHERE asset_hash = ?", (asset_hash,))
        self.conn.commit()

    def clear_all(self):
        """Clears all thumbnails and records."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT thumbnail_path FROM thumbnails")
        rows = cursor.fetchall()
        for row in rows:
            if os.path.exists(row[0]):
                try:
                    os.remove(row[0])
                except OSError:
                    pass
        
        cursor.execute("DELETE FROM thumbnails")
        self.conn.commit()

    def close(self):
        self.conn.close()

# Singleton instance for easy access
app_db = AppDatabase()
