"""
DST (Direct Stream Transfer) Decoder Wrapper
libdstdec.dylib — dst_decode_sectors() 동기식 API 사용
Python GIL 충돌 없이 안전하게 DST→DSD 변환
"""

import ctypes
import os
import threading

_LIB = None
_LIB_LOCK = threading.Lock()


def _load_lib():
    global _LIB
    if _LIB is not None:
        return _LIB
    with _LIB_LOCK:
        if _LIB is not None:
            return _LIB
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libdstdec.dylib'),
            '/tmp/libdstdec.dylib',
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    lib = ctypes.CDLL(path)
                    # dst_decode_sectors(in_data, in_size, channel_count, out_size*) -> uint8_t*
                    lib.dst_decode_sectors.restype  = ctypes.POINTER(ctypes.c_uint8)
                    lib.dst_decode_sectors.argtypes = [
                        ctypes.POINTER(ctypes.c_uint8),  # in_data
                        ctypes.c_size_t,                  # in_size
                        ctypes.c_int,                     # channel_count
                        ctypes.POINTER(ctypes.c_size_t),  # out_size
                    ]
                    lib.dst_free_buffer.restype  = None
                    lib.dst_free_buffer.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
                    _LIB = lib
                    print(f"[DST] libdstdec 로드: {path}")
                    return _LIB
                except Exception as e:
                    print(f"[DST] 로드 실패 ({path}): {e}")
    return None


def is_dst_data(sector_bytes: bytes) -> bool:
    """첫 바이트 0xFD = DST 압축 프레임"""
    return len(sector_bytes) > 0 and sector_bytes[0] == 0xFD


def decode_dst_sectors(sectors_data: bytes, channels: int) -> bytes:
    """
    DST 압축 섹터들(각 2048바이트) → raw DSD bytes
    반환값: 디코딩된 DSD bytes (채널 인터리브)
    """
    lib = _load_lib()
    if lib is None:
        raise RuntimeError("libdstdec.dylib 로드 실패")

    in_arr = (ctypes.c_uint8 * len(sectors_data)).from_buffer_copy(sectors_data)
    out_size = ctypes.c_size_t(0)

    ptr = lib.dst_decode_sectors(in_arr, len(sectors_data), channels, ctypes.byref(out_size))
    if not ptr or out_size.value == 0:
        return b''

    try:
        result = bytes(ptr[:out_size.value])
    finally:
        lib.dst_free_buffer(ptr)

    return result


def available() -> bool:
    return _load_lib() is not None
