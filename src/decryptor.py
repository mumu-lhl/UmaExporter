import struct


# Asset Bundle Constants
DEFAULT_BASE_KEYS = bytes(
    [0x53, 0x2B, 0x46, 0x31, 0xE4, 0xA7, 0xB9, 0x47, 0x3E, 0x7C, 0xFB]
)
DEFAULT_KEY = -7673907454518172050

# Database Constants
DATABASE_BASE_KEY = bytes(
    [
        0xF1,
        0x70,
        0xCE,
        0xA4,
        0xDF,
        0xCE,
        0xA3,
        0xE1,
        0xA5,
        0xD8,
        0xC7,
        0x0B,
        0xD1,
        0x00,
        0x00,
        0x00,
    ]
)

DATABASE_KEY_JAPAN = bytes(
    [
        0x6D,
        0x5B,
        0x65,
        0x33,
        0x63,
        0x36,
        0x63,
        0x25,
        0x54,
        0x71,
        0x2D,
        0x73,
        0x50,
        0x53,
        0x63,
        0x38,
        0x6D,
        0x34,
        0x37,
        0x7B,
        0x35,
        0x63,
        0x70,
        0x23,
        0x37,
        0x34,
        0x53,
        0x29,
        0x73,
        0x43,
        0x36,
        0x33,
    ]
)

DATABASE_KEY_GLOBAL = bytes(
    [0x56, 0x63, 0x6B, 0x63, 0x42, 0x72, 0x37, 0x76, 0x65, 0x70, 0x41, 0x62]
)


try:
    from . import uma_decryptor

    HAS_CYTHON = True
except Exception:
    try:
        import uma_decryptor

        HAS_CYTHON = True
    except Exception:
        HAS_CYTHON = False
        print(
            "Warning: Cython decryptor not found, falling back to pure Python (slower)."
        )


def decrypt_bundle(
    data: bytearray,
    region: str = "jp",
    key: int = DEFAULT_KEY,
    base_keys: bytes = DEFAULT_BASE_KEYS,
) -> bytearray:
    """Decrypt UMA encrypted asset bundle."""
    if HAS_CYTHON:
        uma_decryptor.decrypt_inplace(data, key, base_keys)
        return data

    # Fallback to pure Python XOR
    data_len = len(data)
    if data_len <= 256:
        return data

    base_len = len(base_keys)
    if base_len <= 0:
        return data

    keys_len = base_len * 8

    # Create expanded keys (strictly following C# BitConverter.GetBytes(int64) little-endian)
    key_bytes = struct.pack("<q", key)
    expanded_keys = bytearray(keys_len)
    for i in range(base_len):
        for j in range(8):
            expanded_keys[i * 8 + j] = base_keys[i] ^ key_bytes[j]

    # Perform XOR from byte 256 onwards
    # This might be slow in Python for very large files, but works for now.
    for i in range(256, data_len):
        data[i] ^= expanded_keys[i % keys_len]

    return data


def generate_db_final_key(key: bytes) -> bytes:
    """Derive the final key for SQLite3MC decryption."""
    final_key = bytearray(len(key))
    for i in range(len(key)):
        final_key[i] = key[i] ^ DATABASE_BASE_KEY[i % 13]
    return bytes(final_key)


def get_db_hex_key(region: str = "jp") -> str:
    """Get the final hex key for the specified region."""
    if region.lower() in ("jp", "japan"):
        base_key = DATABASE_KEY_JAPAN
    elif region.lower() in ("global", "en"):
        base_key = DATABASE_KEY_GLOBAL
    else:
        raise ValueError(f"Unsupported region: {region}")

    return generate_db_final_key(base_key).hex()
