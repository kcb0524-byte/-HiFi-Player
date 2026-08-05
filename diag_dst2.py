#!/usr/bin/env python3
"""
diag_dst2.py — DST 비트 순서 테스트 진단
===========================================
Jeff Beck SACD ISO DST 디코딩 실패 원인 파악:
  비트 역전 O (현재) vs 비트 역전 X (DST_NO_BITREV=1)

사용법:
  # 현재 방식 (C에서 비트 역전)
  python3 diag_dst2.py "/Volumes/KCB SSD/Jeff Beck.../Analogue Productions - Blow By Blow.iso"

  # 비트 역전 없음 테스트 (Python에서 미리 역전해 C의 역전 상쇄)
  DST_NO_BITREV=1 python3 diag_dst2.py "/Volumes/KCB SSD/Jeff Beck.../Analogue Productions - Blow By Blow.iso"
"""

import sys
import struct
import os

SECTOR_SIZE = 2048

# ── ISO 경로 ──────────────────────────────────────────────────────
if len(sys.argv) < 2:
    # 기본 경로 (변경 필요)
    ISO = "/Volumes/KCB SSD/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
else:
    ISO = sys.argv[1]

if not os.path.exists(ISO):
    print(f"오류: ISO 파일 없음: {ISO}", file=sys.stderr)
    sys.exit(1)

print(f"ISO: {ISO}", file=sys.stderr, flush=True)
print(f"DST_NO_BITREV={os.environ.get('DST_NO_BITREV','0')}", file=sys.stderr, flush=True)

# ── 오디오 시작 LSN 찾기 ──────────────────────────────────────────
# Master TOC(섹터 510) → TWOCHTOC LSN → 오디오 트랙 시작 LSN
def find_audio_start_lsn(iso_path: str) -> int:
    with open(iso_path, 'rb') as f:
        # Master TOC
        f.seek(510 * SECTOR_SIZE)
        mtoc = f.read(SECTOR_SIZE)
        twoch_lsn = struct.unpack_from('>I', mtoc, 0x40)[0]
        print(f"[TOC] TWOCHTOC LSN: {twoch_lsn}", file=sys.stderr, flush=True)

        # TWOCHTOC에서 트랙 시작 LSN 찾기
        # 방법: twoch_lsn 이후 섹터를 스캔해서 첫 DST 오디오 섹터 위치 탐색
        # (정확한 TOC 파싱 대신 실용적 스캔)
        for offset in range(0, 200):
            lsn = twoch_lsn + offset
            f.seek(lsn * SECTOR_SIZE)
            sec = f.read(SECTOR_SIZE)
            hdr = sec[0]
            is_tc  = (hdr >> 7) & 1
            dst    = (hdr >> 6) & 1
            pi     = hdr & 7
            if not is_tc and dst and pi > 0:
                print(f"[TOC] 첫 DST 오디오 섹터 LSN: {lsn} (offset +{offset})",
                      file=sys.stderr, flush=True)
                return lsn
        # 못 찾으면 fallback
        print(f"[TOC] DST 섹터 미발견, fallback LSN={twoch_lsn+5}", file=sys.stderr, flush=True)
        return twoch_lsn + 5

start_lsn = find_audio_start_lsn(ISO)

# ── 오디오 섹터 데이터 수집 (250섹터 = ~100 DST 프레임 분량) ───────
NUM_SECTORS = 250
print(f"[SCAN] LSN {start_lsn} ~ {start_lsn+NUM_SECTORS-1} ({NUM_SECTORS}섹터) 읽기...",
      file=sys.stderr, flush=True)

with open(ISO, 'rb') as f:
    f.seek(start_lsn * SECTOR_SIZE)
    sectors_data = f.read(NUM_SECTORS * SECTOR_SIZE)

# ── dst_ctypes 임포트 ─────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dst_ctypes import extract_dst_frames, DSTDecoder, is_dst_available

if not is_dst_available():
    print("오류: libdst.dylib 없음 또는 로드 실패", file=sys.stderr)
    sys.exit(1)

# ── 디코딩 실행 ───────────────────────────────────────────────────
dec = DSTDecoder(channels=2, fs_factor=64)
ok = 0; fail = 0
frame_sizes = []

print("[DECODE] 프레임 디코딩 시작...", file=sys.stderr, flush=True)

for frame_bytes, frame_idx, is_raw in extract_dst_frames(sectors_data, channels=2):
    if is_raw:
        continue   # Raw DSD는 스킵
    result = dec.decode_frame(frame_bytes)
    frame_sizes.append(len(frame_bytes))
    if result is not None:
        ok += 1
    else:
        fail += 1

del dec

print(f"\n[RESULT] 총 {ok+fail}프레임: OK={ok}, FAIL={fail}", file=sys.stderr, flush=True)
if frame_sizes:
    print(f"[RESULT] 프레임 크기: min={min(frame_sizes)}, max={max(frame_sizes)}, "
          f"avg={sum(frame_sizes)//len(frame_sizes)}", file=sys.stderr, flush=True)
print(f"[RESULT] (자세한 에러 분포는 [DST_SUMMARY] 라인 참조)", file=sys.stderr, flush=True)
