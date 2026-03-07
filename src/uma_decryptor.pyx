# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True

from libc.stdint cimport int64_t, uint64_t, uint8_t

# Constants from original implementation
DEFAULT_BASE_KEYS = bytes([
    0x53, 0x2B, 0x46, 0x31, 0xE4, 0xA7, 0xB9, 0x47, 0x3E, 0x7C, 0xFB
])
DEFAULT_KEY = -7673907454518172050

cdef void _decrypt_inplace(unsigned char[:] data, int64_t key, const uint8_t[:] base_keys) noexcept:
    cdef Py_ssize_t data_len = data.shape[0]
    if data_len <= 256:
        return

    cdef Py_ssize_t base_len = base_keys.shape[0]
    if base_len <= 0:
        return
        
    cdef Py_ssize_t keys_len = base_len * 8
    
    # Construct keyBytes (8-byte little-endian)
    cdef uint8_t key_bytes[8]
    cdef uint64_t ukey = <uint64_t>key
    cdef int k
    for k in range(8):
        key_bytes[k] = <uint8_t>((ukey >> (k * 8)) & 0xFF)

    # Construct expanded keys array
    cdef uint8_t expanded_keys[2048]
    cdef Py_ssize_t i, j
    for i in range(base_len):
        for j in range(8):
            expanded_keys[i * 8 + j] = base_keys[i] ^ key_bytes[j]

    # XOR Execution
    for i in range(256, data_len):
        data[i] = data[i] ^ expanded_keys[i % keys_len]

def decrypt_inplace(data, int64_t key = DEFAULT_KEY, bytes base_keys = DEFAULT_BASE_KEYS):
    """
    In-place decryption for bytearray or memoryview.
    """
    cdef unsigned char[:] mv = data
    _decrypt_inplace(mv, key, base_keys)
    return data
