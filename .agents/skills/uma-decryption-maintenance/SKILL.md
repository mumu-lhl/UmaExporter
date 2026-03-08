---
name: uma-decryption-maintenance
description: Maintenance, build, and extension procedures for UMA decryption (database and asset bundles). Use when modifying decryption logic, adding new game regions, or troubleshooting decryption failures.
---

# UMA Decryption Maintenance

This skill guides you through maintaining and extending the decryption capabilities of the UMA Viewer, specifically for SQLite databases and Unity Asset Bundles.

## Core Components

*   `src/uma_decryptor.pyx`: High-performance Cython implementation of the XOR decryption algorithm for Asset Bundles.
*   `src/decryptor.py`: Python wrapper that attempts to load the Cython module, falling back to a pure Python implementation if unavailable.
*   `src/database.py`: Handles SQLite database connections, using `apsw` and `sqlite3mc` for encrypted databases.
*   `setup.py`: Build script for the Cython extension.

## 1. Building the Cython Module

The project uses a Cython extension for performance. If you modify `src/uma_decryptor.pyx` or change environments, you must rebuild it.

### Build Command

Use `uv` to run the build script:

```bash
uv run python setup.py build_ext --inplace
```

### Verification

After building, verify the module is loadable and functioning correctly:

```bash
uv run python scripts/verify_region.py
```

## 2. Adding a New Game Region

To support a new game region (e.g., TW, KR), you must update several files to register the region and its specific keys.

### Checklist

1.  **Update `src/constants.py`**:
    *   No changes needed if `REGION` remains a simple string, but ensure any region-specific constants are managed.

2.  **Update `src/decryptor.py`**:
    *   Add the region's database key constant (e.g., `DATABASE_KEY_TW`).
    *   Update `get_db_hex_key(region)` to handle the new region string and return the derived hex key.
    *   **Note**: Asset Bundle keys (`DEFAULT_BASE_KEYS`, `DEFAULT_KEY`) are currently shared. If the new region uses different bundle keys, update `decrypt_bundle` signatures and logic accordingly.

3.  **Update `src/ui/i18n.py`**:
    *   Add translation keys for the new region (e.g., `"region_tw": "Taiwan"`).

4.  **Update `src/ui/main_window.py`**:
    *   Add the new region to `region_options` in `_create_main_layout` (or wherever the settings UI is defined).

## 3. Troubleshooting Database Decryption (Cipher Hunt)

If `src/database.py` fails to open a database, the encryption parameters (Cipher, Page Size, Legacy Mode) may have changed.

### Diagnosis Steps

1.  **Check `src/database.py`**: Look at the `configs` list in `_connect_encrypted`.
2.  **Test Configurations**: The app currently iterates through known working configurations:
    *   `chacha20` (Page Size 4096) - Common in recent versions.
    *   `sqlcipher` (Legacy 1-4, Page Sizes 1024/4096).
    *   `aes256cbc` (Page Sizes 1024/4096).
3.  **Manual Probe**: If all fail, you may need to manually probe the database using a tool like `sqlite3` with `sqlcipher` support or a script to brute-force parameters if the key is known to be correct.

## 4. Troubleshooting Asset Bundle Decryption

*   **Symptom**: Assets fail to load or preview, `UnityPy` errors (e.g. `LZ4BlockError`, `Decompression failed`).
*   **Check**:
    1.  **Region**: Ensure `Config.REGION` is set correctly.
    2.  **Encryption Check**: Verify `_load_bundle_data` in `src/unity_logic.py` detects encryption (checks for `UnityFS` header).
    3.  **Cython Module**: Run `scripts/verify_region.py` to ensure the Cython decryptor is working.
    4.  **Decryption Key (`e` column)**: Asset Bundles use individual keys stored in the `e` column of the `a` table in the `meta` database. Ensure `src/database.py` queries include this column when `Config.DB_ENCRYPTED` is true.
    5.  **External Resources (`.resS`)**: Large textures often reside in external `.resS` files which are also encrypted. `src/unity_logic.py` uses a monkey-patch on `UnityPy.Environment.load_file` to intercept these loads and inject the correct key. Ensure `UnityLogic.set_key_provider` is called in `main_window.py`.

## 5. Architecture Details

### Decryption Keys
*   **Database Key**: Used to open the SQLite `meta` database. Derived from `Config.REGION`.
*   **Asset Key**: Used to decrypt individual Asset Bundles (`.dat`, `.resS`). Stored in the `e` column of the `a` table in the `meta` database.

### UnityPy Integration
*   **Monkey Patch**: `src/unity_logic.py` patches `UnityPy.Environment.load_file`.
*   **Key Provider**: `src/database.py` provides `get_key_by_hash(file_hash)` which maps a file's hash (filename) to its `e` key.
*   **Flow**: `UnityPy` -> `load_file(path)` -> Interceptor -> `db.get_key_by_hash` -> `decrypt_bundle` -> Decrypted Bytes -> `UnityPy`.

### XOR Algorithm
*   **Indexing**: The XOR key indexing is absolute (`i % keys_len`), even though decryption starts at byte 256. Do not shift the index (e.g., do NOT use `i - 256`).
*   **Python 3.14**: Decrypted data must be converted to `bytes` (immutable) before passing to `UnityPy` to avoid hashing errors with `bytearray`.

