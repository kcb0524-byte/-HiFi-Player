"""
dst_ctypes.py
=============
DST (Direct Stream Transfer) 디코더 — Python ctypes 바인딩 + SACD 섹터 파서

사용법:
    from dst_ctypes import DSTDecoder, extract_dst_frames, is_dst_available

    if is_dst_available():
        dec = DSTDecoder(channels=2, fs_factor=64)
        for frame_bytes, frame_idx, is_raw_dsd in extract_dst_frames(sectors_blob, channels=2):
            dsd_bytes = bytes(frame_bytes) if is_raw_dsd else dec.decode_frame(frame_bytes)
            if dsd_bytes:
                # dsd_bytes: 채널인터리브 DSD (ch0_b0, ch1_b0, ch0_b1, ...)
                process(dsd_bytes)
        del dec
"""

from __future__ import annotations

import ctypes
import sys
import os
from pathlib import Path

# ── 비트 역전 테이블 ───────────────────────────────────────────────
# C의 dst_wrapper.c 와 동일한 테이블 (바이트 내 비트 순서 역전)
# DST_NO_BITREV=1 환경변수 설정 시: Python에서 미리 역전해 두면
# C가 다시 역전 → 이중 역전 = 원본 = "비트 역전 없음" 효과
# (libdst.dylib 재빌드 없이 비트 순서 테스트 가능)
_BIT_REV = bytes([int(f'{b:08b}'[::-1], 2) for b in range(256)])
_TEST_NO_BITREV = os.environ.get('DST_NO_BITREV', '0') == '1'
if _TEST_NO_BITREV:
    import sys as _sys2
    print("[DST_BITREV] DST_NO_BITREV=1 — 비트 역전 없음 모드 (이중역전으로 C 역전 상쇄)",
          file=_sys2.stderr, flush=True)

# ── 상수 ─────────────────────────────────────────────────────────
SACD_SECTOR     = 2048
DATA_TYPE_AUDIO = 2
FRAME_SIZE_64   = 4704   # bytes per channel per DSD64 frame (588×64/8)


# ── 라이브러리 로드 ────────────────────────────────────────────────
def _find_lib() -> Path | None:
    """libdst.dylib (macOS) 또는 libdst.dll (Windows) 경로 반환"""
    base = Path(__file__).parent
    if sys.platform == 'darwin':
        names = ['libdst.dylib', 'libdst.so']
    elif sys.platform == 'win32':
        names = ['libdst.dll']
    else:
        names = ['libdst.so', 'libdst.dylib']
    for n in names:
        p = base / n
        if p.exists():
            return p
    return None


_lib     = None
_lib_ok  = None   # True/False/None(미시도)


def _load_lib():
    global _lib, _lib_ok
    if _lib_ok is not None:
        return _lib_ok
    path = _find_lib()
    if path is None:
        _lib_ok = False
        return False
    try:
        lib = ctypes.CDLL(str(path))
        # 함수 시그니처 설정
        lib.dst_wrap_create.restype  = ctypes.c_void_p
        lib.dst_wrap_create.argtypes = [ctypes.c_int, ctypes.c_int]

        lib.dst_wrap_decode.restype  = ctypes.c_int
        lib.dst_wrap_decode.argtypes = [
            ctypes.c_void_p,                     # handle
            ctypes.POINTER(ctypes.c_uint8),      # dst_data
            ctypes.c_int,                         # dst_size
            ctypes.POINTER(ctypes.c_uint8),      # dsd_out
            ctypes.c_int,                         # dsd_out_size
        ]

        lib.dst_wrap_frame_output_size.restype  = ctypes.c_int
        lib.dst_wrap_frame_output_size.argtypes = [ctypes.c_int, ctypes.c_int]

        lib.dst_wrap_destroy.restype  = None
        lib.dst_wrap_destroy.argtypes = [ctypes.c_void_p]

        _lib    = lib
        _lib_ok = True
        return True
    except Exception as e:
        print(f"[DST] 라이브러리 로드 실패: {e}")
        _lib_ok = False
        return False


def is_dst_available() -> bool:
    """DST 디코딩 가능 여부 (libdst.dylib/dll 존재 + 로드 성공)"""
    return _load_lib()


# ── DSTDecoder 클래스 ──────────────────────────────────────────────
class DSTDecoder:
    """
    DST 프레임 단위 디코더
    thread-unsafe: 단일 스레드에서 사용할 것
    """

    def __init__(self, channels: int = 2, fs_factor: int = 64):
        """
        channels  : 채널 수 (SACD 2채널 = 2)
        fs_factor : 64 for DSD64 (SACD 표준), 128 for DSD128
        """
        if not _load_lib():
            raise RuntimeError(
                "libdst.dylib/dll을 찾을 수 없습니다.\n"
                "build_libdst_mac.sh (macOS) 또는 build_libdst_win.bat (Windows) 를\n"
                "실행해 주세요."
            )
        self._lib      = _lib
        self._channels = channels
        self._fs       = fs_factor
        self._out_size = _lib.dst_wrap_frame_output_size(channels, fs_factor)
        self._out_buf  = (ctypes.c_uint8 * self._out_size)()
        self._handle   = _lib.dst_wrap_create(channels, fs_factor)
        if not self._handle:
            raise RuntimeError("DST_InitDecoder 실패 (채널 수/fs_factor 확인)")
        self._frame_errors = 0

    @property
    def output_size(self) -> int:
        """디코딩 출력 바이트 수 (DSD64 2ch = 9408)"""
        return self._out_size

    def decode_frame(self, dst_data: bytes) -> bytes | None:
        """
        DST 압축 프레임 → 채널인터리브 DSD 바이트

        반환: bytes (채널 인터리브), 또는 None (디코딩 실패)
        출력 형식: [ch0_b0, ch1_b0, ch0_b1, ch1_b1, ...]
        """
        if not dst_data:
            return None
        # DST_NO_BITREV=1: 미리 역전해 C의 역전을 상쇄 → 실질적으로 역전 없음 테스트
        if _TEST_NO_BITREV:
            dst_data = bytes(_BIT_REV[b] for b in dst_data)
        in_arr = (ctypes.c_uint8 * len(dst_data)).from_buffer_copy(dst_data)
        ret = self._lib.dst_wrap_decode(
            self._handle,
            in_arr,
            len(dst_data),
            self._out_buf,
            self._out_size,
        )
        # 첫 10프레임: 첫 32바이트 출력 (추출 오류 진단용, stderr=무버퍼)
        _fnum = getattr(self, '_total_frames', 0)
        self._total_frames = _fnum + 1
        if self._total_frames <= 10:
            import sys
            print(f"[PY_FRAME] F#{self._total_frames-1:03d} sz={len(dst_data)} "
                  f"hex32={dst_data[:32].hex()} ret={ret}",
                  file=sys.stderr, flush=True)

        if ret != 0:
            self._frame_errors += 1
            return None   # 오류 → 호출측에서 무음 처리
        return bytes(self._out_buf)

    def __del__(self):
        if self._handle and self._lib:
            try:
                self._lib.dst_wrap_destroy(self._handle)
            except Exception:
                pass
            self._handle = None


# ── SACD DST 섹터 파서 ────────────────────────────────────────────
def extract_dst_frames(sectors_data: bytes, channels: int = 2):
    """
    SACD ISO 오디오 섹터 스트림에서 DST 프레임 추출 (generator)

    섹터 헤더 포맷 (실제 ISO 분석 기반):
      bit7     : TC/타임코드 섹터 플래그 (1이면 스킵)
      bit6     : DST 인코딩 여부 (1=DST, 0=raw DSD)
      bits[5:3]: frame_info_count (N_Frame_Starts)
      bits[2:0]: packet_info_count (N_Packets)

    패킷 정보 (2바이트):
      byte[0] bit7       : frame_start
      byte[0] bits[5:3]  : data_type (2=AUDIO)
      byte[0] bits[2:0] + byte[1]: packet_length

    Yields: (frame_bytes: bytes, frame_index: int, is_raw_dsd: bool)
      is_raw_dsd=False → DST 압축 프레임 (디코더 통과)
      is_raw_dsd=True  → Raw DSD 바이트 (직접 사용)
    """
    frame_buf     = bytearray()
    frame_started = False
    frame_index   = 0
    raw_dsd_buf   = bytearray()   # dst_enc=0 섹터 raw DSD 누적
    raw_dsd_idx   = 0
    offset        = 0
    total         = len(sectors_data)

    import sys as _sys

    _dbg_tc = 0; _dbg_audio = 0; _dbg_fs = 0; _dbg_skip = 0
    _sec_idx = 0                      # 전체 섹터 번호 (TC 포함)
    _dst_fi0 = 0; _dst_fi1p = 0      # fi_count=0 / fi_count>0 DST 섹터 수
    _frames_from_fi0 = 0             # fi_count=0 경계에서 나온 프레임 수
    _frames_from_fi1p = 0            # fi_count>0 경계에서 나온 프레임 수
    _cur_sec = 0                     # 현재 섹터 번호 (출력용)
    _cur_fi = 0                      # 현재 섹터 fi_count

    while offset + SACD_SECTOR <= total:
        sec    = sectors_data[offset: offset + SACD_SECTOR]
        offset += SACD_SECTOR
        _sec_idx += 1
        sec_lsn = _sec_idx   # 전체 섹터 번호

        ptr = 0
        hdr = sec[ptr]; ptr += 1

        # bit7=1 → TC 타임코드 섹터, 건너뜀
        if (hdr >> 7) & 1:
            _dbg_tc += 1
            continue

        dst_enc  = (hdr >> 6) & 1
        fi_count = (hdr >> 3) & 7
        pi_count = hdr & 7
        _cur_sec = sec_lsn
        _cur_fi  = fi_count

        # 처음 12개 비-TC 섹터: 헤더 + raw32 헥스덤프 (stderr=무버퍼)
        if _dbg_audio < 12:
            print(f"[SEC_DBG] sec#{sec_lsn} hdr=0x{hdr:02x} "
                  f"dst={dst_enc} fi={fi_count} pi={pi_count} "
                  f"raw32={sec[:32].hex()}", file=_sys.stderr, flush=True)
        elif dst_enc and fi_count > 0:
            # fi_count>0 섹터는 항상 출력 (중요)
            print(f"[FI_SEC] sec#{sec_lsn} fi={fi_count} pi={pi_count}",
                  file=_sys.stderr, flush=True)

        if pi_count == 0:
            _dbg_skip += 1
            continue

        _dbg_audio += 1

        # 패킷 정보 파싱 (2바이트 × pi_count)
        pkts = []
        for _ in range(min(pi_count, 7)):
            if ptr + 2 > SACD_SECTOR:
                break
            b0 = sec[ptr]; b1 = sec[ptr + 1]; ptr += 2
            pkt_info = {
                'fs': (b0 >> 7) & 1,          # frame_start
                'dt': (b0 >> 3) & 7,           # data_type
                'pl': (b0 & 7) << 8 | b1,      # packet_length
            }
            pkts.append(pkt_info)
            # 처음 12섹터는 패킷인포도 출력
            if _dbg_audio <= 12:
                print(f"  pkt_info: fs={pkt_info['fs']} dt={pkt_info['dt']} "
                      f"pl={pkt_info['pl']} (b0=0x{b0:02x} b1=0x{b1:02x})",
                      file=_sys.stderr, flush=True)

        # 프레임 정보 파싱 (DST 전용, 4바이트 × fi_count)
        # 포맷: bytes[0..1]=채널상태(무시), bytes[2..3]=fs=1 오디오패킷 내 분할 오프셋
        # fi_count=0: 모든 fs=1 오디오 패킷이 바이트0에서 프레임 시작 (오프셋 불필요)
        # fi_count>0: fs=1 오디오 패킷 중 바이트0이 아닌 위치에서 시작하는 것만 기재
        fi_offsets = []
        if fi_count > 0:
            fi_raw = sec[ptr: ptr + fi_count * 4]
            if _dbg_audio <= 12:
                print(f"  frame_info({fi_count}): {fi_raw.hex()} dst_enc={dst_enc}",
                      file=_sys.stderr, flush=True)
            if dst_enc:
                _dst_fi1p += 1
                for i in range(fi_count):
                    # bytes[2..3] = 섹터 오디오 페이로드 내 절대 바이트 오프셋
                    b0, b1 = fi_raw[i * 4 + 2], fi_raw[i * 4 + 3]
                    fi_offsets.append((b0 << 8) | b1)
                # fi_count>0 섹터는 항상 fi_offsets 출력
                print(f"  [FI_OFF] sec#{sec_lsn} fi_offsets={fi_offsets} "
                      f"raw4={fi_raw[:fi_count*4].hex()}",
                      file=_sys.stderr, flush=True)
            ptr += fi_count * 4  # dst_enc 여부 무관하게 항상 전진
        elif dst_enc:
            _dst_fi0 += 1

        # 패킷 데이터 처리
        if dst_enc:
            # ── DST 압축 섹터 ────────────────────────────────────────────
            if fi_offsets:
                # fi_count > 0:
                # fi_offsets[i] = 섹터의 모든 패킷 페이로드를 연결한 스트림에서
                # 새 DST 프레임이 시작하는 절대 바이트 오프셋.
                # (특정 패킷 내 로컈 오프셋이 아님!)
                fi_sorted = sorted(fi_offsets)
                fi_ptr_idx = 0
                stream_pos = 0   # 패킷 페이로드 영역 내 누적 오프셋

                for pkt in pkts:
                    pl = pkt['pl']
                    if ptr >= SACD_SECTOR:
                        break
                    actual_pl = min(pl, SACD_SECTOR - ptr)

                    pkt_stream_start = stream_pos
                    pkt_stream_end   = stream_pos + actual_pl

                    if pkt['dt'] == DATA_TYPE_AUDIO:
                        pkt_off = 0   # 이 패킷 내 시작 위치

                        while (fi_ptr_idx < len(fi_sorted) and
                               fi_sorted[fi_ptr_idx] < pkt_stream_end):
                            fi_abs       = fi_sorted[fi_ptr_idx]
                            split_in_pkt = max(0, fi_abs - pkt_stream_start)

                            if split_in_pkt > pkt_off and frame_started:
                                frame_buf.extend(
                                    sec[ptr + pkt_off: ptr + split_in_pkt])

                            if frame_started and frame_buf:
                                if frame_index < 20:
                                    print(f"[FRAME_DBG] yield frame#{frame_index}: "
                                          f"{len(frame_buf)}B "
                                          f"first32={bytes(frame_buf)[:32].hex()} "
                                          f"(sec#{sec_lsn} fi_abs={fi_abs})",
                                          file=_sys.stderr, flush=True)
                                yield (bytes(frame_buf), frame_index, False)
                                frame_index += 1
                                _dbg_fs += 1
                                _frames_from_fi1p += 1

                            frame_buf     = bytearray()
                            frame_started = True
                            pkt_off       = split_in_pkt
                            fi_ptr_idx   += 1

                        if pkt_off < actual_pl and frame_started:
                            frame_buf.extend(sec[ptr + pkt_off: ptr + actual_pl])

                    stream_pos = pkt_stream_end
                    ptr += pl
            else:
                # fi_count = 0: fs=1 오디오 패킷의 바이트0에서 프레임 시작 (기존 방식)
                for pkt in pkts:
                    pl = pkt['pl']
                    if ptr >= SACD_SECTOR:
                        break
                    actual_pl = min(pl, SACD_SECTOR - ptr)

                    if pkt['dt'] == DATA_TYPE_AUDIO:
                        if pkt['fs']:
                            _dbg_fs += 1
                            if frame_started and frame_buf:
                                if frame_index < 20:
                                    print(f"[FRAME_DBG] yield frame#{frame_index}: "
                                          f"{len(frame_buf)}B "
                                          f"first32={bytes(frame_buf)[:32].hex()} "
                                          f"(sec#{sec_lsn} fs=1 fi0)",
                                          file=_sys.stderr, flush=True)
                                yield (bytes(frame_buf), frame_index, False)
                                frame_index += 1
                                _frames_from_fi0 += 1
                            frame_buf = bytearray()
                            frame_started = True
                            frame_buf.extend(sec[ptr: ptr + actual_pl])
                        else:
                            if frame_started:
                                frame_buf.extend(sec[ptr: ptr + actual_pl])

                    ptr += pl
        else:
            # ── Raw DSD 섹터 (dst_enc=0) ─────────────────────────
            for pkt in pkts:
                pl = pkt['pl']
                if ptr >= SACD_SECTOR:
                    break
                actual_pl = min(pl, SACD_SECTOR - ptr)
                if pkt['dt'] == DATA_TYPE_AUDIO:
                    if pkt['fs'] and raw_dsd_buf:
                        yield (bytes(raw_dsd_buf), raw_dsd_idx, True)
                        raw_dsd_idx += 1
                        raw_dsd_buf = bytearray()
                    raw_dsd_buf.extend(sec[ptr: ptr + actual_pl])
                ptr += pl

    # 마지막 raw DSD 버퍼 flush
    if raw_dsd_buf:
        yield (bytes(raw_dsd_buf), raw_dsd_idx, True)

    print(f"[DST_DBG] 요약: TC섹터={_dbg_tc} 오디오섹터={_dbg_audio} "
          f"frame_start수={_dbg_fs} pi=0 스킵={_dbg_skip} "
          f"총DST프레임={frame_index} 총rawDSD={raw_dsd_idx}",
          file=_sys.stderr, flush=True)
    print(f"[SEC_STAT] DST섹터: fi_count=0 수={_dst_fi0}, fi_count>0 수={_dst_fi1p}",
          file=_sys.stderr, flush=True)
    print(f"[FRAME_SRC] fi_count=0(fs=1)에서 나온 프레임={_frames_from_fi0}, "
          f"fi_count>0(fi_offset)에서 나온 프레임={_frames_from_fi1p}",
          file=_sys.stderr, flush=True)
    # 마지막 미완성 프레임은 버림 (1/75초 미만 손실, 무시 가능)
