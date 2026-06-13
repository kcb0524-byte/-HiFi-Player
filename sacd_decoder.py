"""
SACD ISO Decoder
================
SACD ISO 이미지 파일에서 트랙을 추출하고 DSD→PCM 변환
지원 포맷: .iso (SACD)

SACD ISO 구조:
  - Master TOC: sector 510/511
  - Area TOC: TWOCH(2채널) / MULCH(멀티채널)
  - Track DST or DSD raw data
"""

import struct
import threading
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Callable

# SACD ISO 상수
SACD_SECTOR_SIZE   = 2048
SACD_LSN_MASTER    = 510          # Master TOC 시작 섹터
SACD_MAGIC_MASTER  = b'SACDMTOC'
SACD_MAGIC_AREA    = b'TWOCHTOC'
SACD_MAGIC_MULCH   = b'MULCHTOC'
SACD_MAGIC_TRACK   = b'SACDTTxt'

# DSD 샘플레이트
DSD64_FS  = 2822400   # DSD64 (1bit × 64 × 44100)
DSD128_FS = 5644800   # DSD128


# ─────────────────────────────────────────────────────────────
# DSD 변환 함수 — dsd_decoder.py 공유 로직 임포트
# ─────────────────────────────────────────────────────────────
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from dsd_decoder import _get_fir, _bits_to_pcm


def _dsd_bits_to_pcm(dsd_bytes: bytes, channels: int,
                     decimation: int = 64) -> np.ndarray:
    """
    SACD ISO DSD 데이터 → float32 PCM

    SACD ISO는 big-endian 비트 순서 (MSB first), 채널 바이트 인터리브
    (ch0_byte, ch1_byte, ch0_byte, ch1_byte, ...)

    DFF는 bitorder='little'이지만 SACD ISO는 bitorder='big' (기본값)
    """
    fir  = _get_fir(decimation)
    arr  = np.frombuffer(dsd_bytes, dtype=np.uint8)

    total_bytes = len(arr)
    usable = (total_bytes // channels) * channels
    if usable == 0:
        return np.zeros((0, channels), dtype=np.float32)

    arr = arr[:usable]
    pcm_channels = []
    for ch in range(channels):
        ch_bytes = arr[ch::channels]
        # SACD ISO: big-endian 비트 순서 (bitorder 기본값 = 'big')
        bits = np.unpackbits(ch_bytes).astype(np.float32)
        pcm_ch = _bits_to_pcm(bits, decimation, fir)
        pcm_channels.append(pcm_ch)

    min_len = min(len(c) for c in pcm_channels)
    if min_len == 0:
        return np.zeros((0, channels), dtype=np.float32)
    return np.column_stack([c[:min_len] for c in pcm_channels]).astype(np.float32)


# ─────────────────────────────────────────────────────────────
# Master TOC 파싱
# ─────────────────────────────────────────────────────────────
def _read_sector(f, lsn: int) -> bytes:
    f.seek(lsn * SACD_SECTOR_SIZE)
    return f.read(SACD_SECTOR_SIZE)


def _find_master_toc(f) -> Optional[int]:
    """Master TOC 섹터 번호 탐색 (510, 520, 530 순으로 시도)"""
    for lsn in [510, 520, 530, 511, 512]:
        try:
            sec = _read_sector(f, lsn)
            if sec[:8] == SACD_MAGIC_MASTER:
                return lsn
        except Exception:
            pass
    return None


def _parse_master_toc(f) -> Optional[Dict]:
    """Master TOC에서 Area 위치 정보 추출

    실제 SACD ISO Master TOC 레이아웃 (hex 덤프 기반):
      0x00-0x07: 'SACDMTOC'
      0x08-0x09: version
      0x40-0x43: 2ch area LSN  (big-endian uint32)
      0x44-0x47: 2ch area size (big-endian uint32)
      0x50-0x53: mulch area LSN
      0x54-0x57: mulch area size
    """
    try:
        lsn = _find_master_toc(f)
        if lsn is None:
            return None
        sec = _read_sector(f, lsn)

        # 실제 오프셋 (덤프 검증):
        # 0x40: 00 00 02 20 = 0x220 = 544 → 2ch Area TOC 섹터 번호 ✓
        # 0x44: 00 0c 00 78 = 2ch area 크기
        # 0x50: 00 00 00 00 = 0 (mulch 없음)
        # 0x54: 00 08 00 00 = mulch size
        twoch_lsn  = struct.unpack_from('>I', sec, 0x40)[0]
        twoch_size = struct.unpack_from('>I', sec, 0x44)[0]
        mulch_lsn  = struct.unpack_from('>I', sec, 0x50)[0]
        mulch_size = struct.unpack_from('>I', sec, 0x54)[0]

        # Album title (offset 0x12 부터 ASCII/UTF-8 패딩)
        album_title = ''
        try:
            raw = sec[0x10:0x40]
            album_title = raw.rstrip(b'\x00').decode('utf-8', errors='ignore').strip()
        except Exception:
            pass

        return {
            'twoch_lsn':   twoch_lsn,
            'twoch_size':  twoch_size,
            'mulch_lsn':   mulch_lsn,
            'mulch_size':  mulch_size,
            'album_title': album_title,
            'master_lsn':  lsn,
        }
    except Exception:
        return None


def _parse_area_toc(f, area_lsn: int) -> Optional[Dict]:
    """Area TOC에서 트랙 목록 추출

    실제 SACD ISO Area TOC 레이아웃 (hex 덤프 기반):
      0x00-0x07: 'TWOCHTOC' or 'MULCHTOC'
      0x08-0x09: version
      0x0a-0x0b: area_description flags
      0x0c     : 0=reserved
      0x0d     : 0=reserved
      0x0e     : 0=reserved
      0x0f     : 0=reserved
      0x10-0x13: sample_frequency (big-endian) — 0x000AF000=720896=DSD64 관련
      0x14     : channel_count
      0x15     : channel_assignment
      0x16-0x17: track_count (big-endian uint16)
      0x20-0x21: track_count (alternative, uint16 big-endian)
      0x40+    : 트랙 테이블 (각 8바이트: LSN 4 + size 4)
    """
    if area_lsn == 0:
        return None
    try:
        sec = _read_sector(f, area_lsn)
        magic = sec[:8]
        if magic not in (SACD_MAGIC_AREA, SACD_MAGIC_MULCH):
            return None

        # 실제 덤프 분석:
        # offset 0x0b: 0x08 = flags
        # offset 0x10: 00 0a f0 00 → DSD sample freq (0xAF000 = 716800? → DSD64 marker)
        # offset 0x14: 04 → channel_count (4ch → 2ch stereo pair)
        # offset 0x15: 02 → channel_assignment
        # offset 0x20: 02 00 → track_count (little-endian)
        # offset 0x22: 02 00 → track_count 2ch (little-endian)

        # channels: TWOCHTOC=2ch, MULCHTOC=멀티
        channels = 2 if magic == SACD_MAGIC_AREA else min(max(sec[0x14], 1), 6)

        # DSD 샘플레이트: 항상 DSD64(2822400) — SACD 표준
        dsd_fs     = DSD64_FS
        decimation = 64
        pcm_fs     = 44100

        # ── 트랙 테이블 파싱 ──────────────────────────────────
        # 실제 구조 (덤프 분석):
        #   각 트랙 엔트리 = 8바이트
        #   bytes 0-2: LSN (3바이트 big-endian)
        #   byte  3  : 패딩
        #   bytes 4-6: size in sectors (3바이트 big-endian)
        #   byte  7  : 패딩
        #
        #   예) 25 19 26 00  00 09 00 00
        #       LSN=0x251926=2431270  size=0x000900=2304
        #
        # Area TOC는 여러 섹터에 걸칠 수 있음 (큰 앨범)
        # → 여러 섹터를 이어붙여 스캔

        # 파일 전체 섹터 수 파악
        try:
            f.seek(0, 2)
            file_size = f.tell()
            total_sectors = file_size // SACD_SECTOR_SIZE
        except Exception:
            total_sectors = 0xFFFFFFFF

        # Area TOC 섹터 크기: 최대 16섹터 이어붙여 스캔
        blob = bytearray()
        for i in range(16):
            try:
                blob.extend(_read_sector(f, area_lsn + i))
            except Exception:
                break

        raw_tracks = []
        tbl_offset = 0x40
        MIN_VALID_LSN = area_lsn + 10  # Area TOC 이후 섹터부터 유효

        # ── 트랙 테이블 두 가지 해석을 시도:
        # 해석A: 3바이트 BE LSN (sector 번호)
        # 해석B: 4바이트 BE "byte address" → ÷2048 하면 LSN

        # ── 트랙 테이블 파싱 ──────────────────────────────────────────────
        # 실제 SACD ISO 구조 (덤프 확인):
        #   area_lsn+0 (544): TWOCHTOC  — Area TOC 헤더
        #   area_lsn+1 (545): SACDTRL1  — 트랙 리스트 1 (실제 트랙 테이블)
        #   area_lsn+2 (546): SACDTRL2  — 트랙 리스트 2
        #   area_lsn+3 (547): SACD_IGL  — Index/Gap 리스트
        #   area_lsn+5 (549): SACDTTxt  — 텍스트 메타데이터
        #
        # SACDTRL1 섹터 구조:
        #   0x00-0x07: 'SACDTRL1' 매직
        #   0x08+    : 트랙 엔트리 (각 8바이트)
        #              bytes 0-3: BE byte_address → ÷2048 = LSN
        #              bytes 4-7: BE size_in_sectors
        #
        # TWOCHTOC 0x40의 첫 엔트리(25 19 26 00 / 00 09 00 00)는
        # 전체 Area 시작/크기를 가리키는 포인터이고 개별 트랙 테이블이 아님

        # SACDTRL1 섹터 찾기
        trl1_sec = None
        for i in range(1, 10):
            s = blob[i * SACD_SECTOR_SIZE: (i+1) * SACD_SECTOR_SIZE]
            if s[:8] == b'SACDTRL1':
                trl1_sec = s
                break

        raw_tracks = []
        if trl1_sec is not None:
            # SACDTRL1 구조: 0x08부터 4바이트 BE LSN 배열
            # 마지막 값은 end marker (다음 엔트리와 차이로 마지막 트랙 크기 계산)
            # 예: 00 00 05 2c  00 01 87 2c  00 02 94 46 ... 00 0a bf 78  00 00 00 00
            #      LSN=1324     LSN=100140   LSN=169030 ...  end=704376   term=0
            lsn_list = []
            off = 0x08
            while off + 4 <= len(trl1_sec):
                lsn_val = struct.unpack_from('>I', trl1_sec, off)[0]
                if lsn_val == 0 and lsn_list:
                    break  # 종료 마커
                if lsn_val > 0:
                    lsn_list.append(lsn_val)
                elif lsn_val == 0 and not lsn_list:
                    off += 4
                    continue
                off += 4

            # 인접 LSN 차이로 트랙 크기 계산 (마지막 값은 end marker)
            # lsn_list = [start1, start2, ..., startN, end_marker]
            for i in range(len(lsn_list) - 1):
                lsn_s = lsn_list[i]
                lsn_e = lsn_list[i + 1]
                size  = lsn_e - lsn_s
                if size > 0 and lsn_s < total_sectors:
                    raw_tracks.append({'lsn': lsn_s, 'size': size})
        else:
            # fallback: TWOCHTOC 0x40 스캔 (구버전 ISO 호환)
            off = 0x40
            while off + 8 <= SACD_SECTOR_SIZE:
                raw = blob[off:off+8]
                byte_addr = struct.unpack_from('>I', raw, 0)[0]
                size_sec  = struct.unpack_from('>I', raw, 4)[0]
                lsn = byte_addr // SACD_SECTOR_SIZE
                if lsn >= MIN_VALID_LSN and lsn < total_sectors and size_sec > 0:
                    raw_tracks.append({'lsn': lsn, 'size': size_sec})
                elif byte_addr == 0 and size_sec == 0 and raw_tracks:
                    break
                off += 8

        # LSN 순서 정렬
        raw_tracks.sort(key=lambda x: x['lsn'])

        # 인접 LSN 차이로 size 재계산
        tracks = []
        for i, t in enumerate(raw_tracks):
            if i + 1 < len(raw_tracks):
                real_size = raw_tracks[i+1]['lsn'] - t['lsn']
            else:
                real_size = t['size']
            if real_size > 0:
                tracks.append({'lsn': t['lsn'], 'size': real_size, 'index': i})

        if not tracks:
            return None

        return {
            'dsd_fs':     dsd_fs,
            'pcm_fs':     pcm_fs,
            'decimation': decimation,
            'channels':   max(1, min(channels, 6)),
            'tracks':     tracks,
        }
    except Exception as e:
        print(f"[SACD] _parse_area_toc error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# SACDTTxt 텍스트 필드 파서
# ─────────────────────────────────────────────────────────────
def _parse_sacd_text_field(chunk: bytes, field_id=None) -> str:
    """
    SACDTTxt 텍스트 블록에서 트랙 제목 추출

    실제 덤프 분석:
      chunk[0]    : 0x08 = field_type (track title=0x01, album=0x00, artist=0x02...)
                    또는 레코드 헤더
      chunk[1]    : 0x00 = 언어 인덱스
      chunk[2-3]  : 0x00 0x20 = 다음 필드 오프셋 or 크기

    실제로는 각 텍스트 청크가:
      [type 1B][lang_idx 1B][next_off 2B][text...null]
    구조이고, type에 따라 track title / album / artist 구분

    간단하게: 헤더 4바이트 건너뛰고 첫 null-terminated 문자열 추출
    UTF-16BE 또는 ASCII로 시도
    """
    if not chunk or len(chunk) < 4:
        return ''

    # 헤더 건너뛰기: 첫 2~4바이트가 메타 정보
    # 실제 텍스트는 첫 번째 non-zero ASCII 또는 UTF-16BE 시작점
    # 방법: 4바이트씩 건너뛰며 유효한 텍스트 찾기

    # 실제 SACDTTxt 필드 구조 (바이트 분석):
    #   byte 0   : 0x08 = field_type
    #   byte 1   : 0x00 = lang_index
    #   byte 2   : 0x00 = encoding (0=ISO-8859-1/ASCII)
    #   byte 3   : 0x20 = 다음 필드까지 오프셋
    #   byte 4+  : null-terminated ASCII/ISO-8859-1 텍스트
    #
    # 예) 08 00 00 20 4d 61 6e 20 4f 6e ... 00
    #                  M  a  n     O  n        \0
    # → skip=4, ASCII null-terminated

    # 1. skip=4, ASCII/UTF-8
    if len(chunk) > 4:
        data = chunk[4:]
        nul = data.find(b'\x00')
        if nul > 1:
            try:
                t = data[:nul].decode('latin-1', errors='ignore').strip()
                if t and len(t) > 1:
                    return t
            except Exception:
                pass

    # 2. 필드 내에서 출력 가능한 ASCII 연속 구간 탐색 (fallback)
    best = ''
    i = 0
    while i < len(chunk):
        b = chunk[i]
        if 0x20 <= b <= 0x7e or b >= 0xa0:  # printable ASCII or latin-1
            j = i
            while j < len(chunk) and (0x20 <= chunk[j] <= 0x7e or chunk[j] >= 0xa0):
                j += 1
            candidate = chunk[i:j]
            if len(candidate) > len(best):
                try:
                    best = candidate.decode('latin-1', errors='ignore').strip()
                except Exception:
                    pass
            i = j
        else:
            i += 1
    if len(best) > 2:
        return best

    return ''


# ─────────────────────────────────────────────────────────────
# 트랙 메타데이터 추출 (Text TOC)
# ─────────────────────────────────────────────────────────────
def _extract_track_titles(f, master_lsn: int, track_count: int) -> List[str]:
    """SACDTTxt 섹터에서 트랙 제목 추출 (없으면 Track N 반환)

    실제 SACDTTxt 덤프:
      0x00-0x07: 'SACDTTxt'
      0x08-0x1f: 오프셋 테이블 (각 2바이트 big-endian, 트랙별 텍스트 시작 위치)
                 예: 10 00  10 44  10 78  10 b8  10 f0  11 24  11 60  11 a8  11 f0
                 → 0x1000, 0x1044, 0x1078 ...  (섹터 내 절대 오프셋)
      각 오프셋 위치부터: 텍스트 블록 (UTF-16BE 또는 ASCII)
    """
    titles = [f"Track {i+1}" for i in range(track_count)]
    try:
        # SACDTTxt 탐색: master_lsn 근처 (510~530) 및 area_lsn 근처 (544~560)
        txt_sec = None
        txt_lsn = None
        search_start = [master_lsn, master_lsn - 10, 510, 540]
        for base in search_start:
            if txt_sec:
                break
            for delta in range(0, 30):
                lsn = base + delta
                if lsn < 0:
                    continue
                try:
                    sec = _read_sector(f, lsn)
                    if sec[:8] == SACD_MAGIC_TRACK:
                        txt_sec = sec
                        txt_lsn = lsn
                        break
                except Exception:
                    pass

        if txt_sec is None:
            return titles

        # 오프셋 테이블: 0x08부터 각 2바이트
        # 실제 덤프: 10 00  10 44  10 78  10 b8  10 f0  11 24  11 60  11 a8  11 f0
        # → 0x1000, 0x1044, 0x1078 ... (섹터 블롭 내 바이트 오프셋)
        # 0이 나오면 테이블 끝

        # 오프셋 테이블: 0x08부터 각 2바이트 BE
        # 실제 덤프: 10 00  10 44  10 78 ... 11 f0
        # 오프셋은 SACDTTxt 섹터 시작 기준 바이트 오프셋
        # (0x1000 = 4096 → 섹터 549로부터 4096바이트 = 2번째 섹터 처음)
        offsets = []
        for i in range(32):
            tbl_off = 0x08 + i * 2
            if tbl_off + 2 > len(txt_sec):
                break
            off = struct.unpack_from('>H', txt_sec, tbl_off)[0]
            if off == 0 and offsets:
                break
            if off > 0:
                offsets.append(off)

        # 전체 텍스트 블록: txt_lsn부터 필요한 만큼 읽기
        max_off = max(offsets) if offsets else 0
        n_sectors = (max_off // SACD_SECTOR_SIZE) + 2
        txt_blob = bytearray()
        for i in range(n_sectors):
            try:
                txt_blob.extend(_read_sector(f, txt_lsn + i))
            except Exception:
                break

        for i in range(min(track_count, len(offsets))):
            start = offsets[i]
            end   = offsets[i+1] if i+1 < len(offsets) else start + 256
            if start >= len(txt_blob):
                continue
            chunk = bytes(txt_blob[start:min(end, len(txt_blob))])

            # SACDTTxt 텍스트 블록 구조:
            # byte 0   : type (0x08 = track title, 0x09 = artist, ...)
            # byte 1   : 언어 코드 관련 플래그
            # byte 2-3 : 필드 크기 or 인코딩 플래그
            # 이후     : 텍스트 데이터 (여러 필드가 연속)
            #
            # 필드 내부 구조: [field_id 1B][encoding 1B][lang 2B][text...][0x00]
            # encoding: 0x00=ISO-8859-1, 0x01=UTF-16BE, 0x02=UTF-8
            #
            # 트랙 제목만 추출: field_id=0x01(track title)을 찾아서 파싱

            title = _parse_sacd_text_field(chunk, field_id=0x01)
            if not title:
                # fallback: 첫 번째 텍스트 필드 아무거나
                title = _parse_sacd_text_field(chunk, field_id=None)
            if title:
                titles[i] = title
    except Exception as e:
        print(f"[SACD] title extract error: {e}")
    return titles


# ─────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────
class SACDDecoder:
    """SACD ISO 파일 파서 및 DSD→PCM 디코더"""

    SUPPORTED_EXTENSIONS = {'.iso'}

    @staticmethod
    def is_sacd_file(filepath: str) -> bool:
        p = Path(filepath)
        if p.suffix.lower() != '.iso':
            return False
        # 매직 바이트 확인
        try:
            with open(filepath, 'rb') as f:
                sec = _read_sector(f, SACD_LSN_MASTER)
                if sec[:8] == SACD_MAGIC_MASTER:
                    return True
                sec = _read_sector(f, 512)
                return sec[:8] == SACD_MAGIC_MASTER
        except Exception:
            return False

    def get_track_list(self, filepath: str) -> List[Dict]:
        """
        ISO에서 트랙 목록 반환
        각 항목: {index, title, duration_sec, channels, dsd_fs, pcm_fs, lsn, size}
        """
        tracks = []
        try:
            with open(filepath, 'rb') as f:
                mtoc = _parse_master_toc(f)
                if not mtoc:
                    return []

                # 2채널 영역 우선, 없으면 멀티채널
                area = _parse_area_toc(f, mtoc['twoch_lsn'])
                if not area:
                    area = _parse_area_toc(f, mtoc['mulch_lsn'])
                if not area:
                    return []

                tc = len(area['tracks'])
                titles = _extract_track_titles(f, mtoc.get('master_lsn', SACD_LSN_MASTER), tc)

                for i, t in enumerate(area['tracks']):
                    # 재생 시간 추정:
                    # DSD64 = 2,822,400 bits/sec/ch → 352,800 bytes/sec/ch
                    # 2ch: 705,600 bytes/sec
                    # 섹터당 2048 bytes
                    bytes_per_sec = (area['dsd_fs'] // 8) * area['channels']
                    sector_bytes  = t['size'] * SACD_SECTOR_SIZE
                    duration      = sector_bytes / bytes_per_sec if bytes_per_sec > 0 else 0

                    tracks.append({
                        'index':       i,
                        'title':       titles[i] if i < len(titles) else f"Track {i+1}",
                        'album':       mtoc.get('album_title', ''),
                        'duration':    duration,
                        'channels':    area['channels'],
                        'dsd_fs':      area['dsd_fs'],
                        'pcm_fs':      area['pcm_fs'],
                        'decimation':  area['decimation'],
                        'lsn':         t['lsn'],
                        'size':        t['size'],
                        'filepath':    filepath,
                    })
        except Exception as e:
            print(f"[SACD] get_track_list error: {e}")
        return tracks

    def decode_streaming(self, track_info: Dict,
                         chunk_callback: Callable,
                         done_callback:  Optional[Callable] = None,
                         error_callback: Optional[Callable] = None,
                         stop_event:     Optional[threading.Event] = None,
                         stopped_event:  Optional[threading.Event] = None):
        """
        스트리밍 디코드
        chunk_callback(pcm: np.ndarray, sample_rate: int, info: dict)
        """
        if stop_event is None:
            stop_event = threading.Event()
        t = threading.Thread(
            target=self._stream_worker,
            args=(track_info, chunk_callback, done_callback,
                  error_callback, stop_event, stopped_event),
            daemon=True,
        )
        t.start()
        return t

    # ─────────────────────────────────────────
    # 내부 스트리밍 워커
    # ─────────────────────────────────────────
    CHUNK_SECTORS = 512   # 한 번에 읽을 섹터 수 (512 × 2048 = 1MB, FIR 워밍업 충분)

    def _stream_worker(self, track_info: Dict,
                       chunk_cb, done_cb, error_cb,
                       stop_ev: threading.Event,
                       stopped_ev: Optional[threading.Event]):
        filepath   = track_info['filepath']
        lsn        = track_info['lsn']
        size       = track_info['size']
        channels   = track_info['channels']
        decimation = track_info['decimation']
        pcm_fs     = track_info['pcm_fs']
        first      = True

        try:
            with open(filepath, 'rb') as f:
                remaining = size
                cur_lsn   = lsn
                while remaining > 0 and not stop_ev.is_set():
                    sectors_to_read = min(self.CHUNK_SECTORS, remaining)
                    f.seek(cur_lsn * SACD_SECTOR_SIZE)
                    raw = f.read(sectors_to_read * SACD_SECTOR_SIZE)
                    if not raw:
                        break

                    # SACD 섹터 헤더(32바이트) 제거 후 DSD 데이터만 추출
                    SACD_HDR = 32
                    dsd_data = bytearray()
                    n_secs = len(raw) // SACD_SECTOR_SIZE
                    for si in range(n_secs):
                        sec = raw[si*SACD_SECTOR_SIZE : (si+1)*SACD_SECTOR_SIZE]
                        dsd_data.extend(sec[SACD_HDR:])
                    raw = bytes(dsd_data)

                    pcm = _dsd_bits_to_pcm(raw, channels, decimation)
                    if len(pcm) == 0:
                        cur_lsn   += sectors_to_read
                        remaining -= sectors_to_read
                        continue

                    info = {}
                    if first:
                        info = {
                            'sample_rate': pcm_fs,
                            'channels':    channels,
                            'format':      f"DSD{decimation*44100//44100}",
                            'bit_depth':   1,
                            'title':       track_info.get('title', ''),
                            'album':       track_info.get('album', ''),
                        }
                        first = False

                    chunk_cb(pcm, pcm_fs, info)

                    cur_lsn   += sectors_to_read
                    remaining -= sectors_to_read

            if done_cb and not stop_ev.is_set():
                done_cb()
        except Exception as e:
            if error_cb:
                error_cb(str(e))
        finally:
            if stopped_ev:
                stopped_ev.set()
