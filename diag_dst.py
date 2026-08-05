#!/usr/bin/env python3
"""
diag_dst.py — DST 디코딩 WAV 진단 도구
사용: python3 diag_dst.py /path/to/file.iso [max_frames]
결과: diag_output.wav (처음 N프레임 디코딩 결과 → 실제로 들어볼 수 있음)

음악이 들리면 → 디코더 정상, 앱 파이프라인 문제
노이즈/무음만 → DST 디코더 버그
"""
import sys, os, struct, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from dst_ctypes import is_dst_available, DSTDecoder, extract_dst_frames
from dsd_decoder import dsd_bytes_to_pcm_sacd

SACD_SECTOR = 2048

# ── 1. 라이브러리 확인 ─────────────────────────────────────────
ok = is_dst_available()
print(f"[1] DST 라이브러리: {'OK' if ok else 'FAIL — libdst.dylib 없음'}")
if not ok:
    sys.exit(1)

# ── 2. ISO 경로 ────────────────────────────────────────────────
iso_path = sys.argv[1] if len(sys.argv) > 1 else None
MAX_FRAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 200

if not iso_path:
    import glob
    isos = (glob.glob(os.path.expanduser("~/**/*.iso"), recursive=True) +
            glob.glob("/Volumes/**/*.iso", recursive=True))
    if not isos:
        print("[!] 사용법: python3 diag_dst.py /path/to/file.iso")
        sys.exit(1)
    iso_path = isos[0]
print(f"[2] ISO: {iso_path}")
print(f"    최대 {MAX_FRAMES} 프레임 디코딩 ({MAX_FRAMES/75:.1f}초)")

# ── 3. 섹터 읽기 (Master TOC → SACDTRL1 → 첫 트랙 오디오 LSN) ─────────────
def find_audio_lsn(path):
    """
    Master TOC → Area TOC LSN 찾기 → SACDTRL1 파싱 → 첫 트랙 실제 LSN 반환

    오류 원인:
      - Master TOC의 0x40 값은 Area TOC 헤더 시작 (TWOCHTOC 섹터, 예: LSN 544)
      - 실제 트랙 오디오는 그보다 훨씬 뒤에 있음 (예: LSN 1324~)
      - SACDTRL1 섹터 (Area TOC + 1)에 트랙 LSN 목록이 있음
    """
    MTOC_MAGIC  = b'SACDMTOC'
    TRL1_MAGIC  = b'SACDTRL1'

    with open(path, 'rb') as f:
        # ① Master TOC 찾기
        area_toc_lsn = None
        for try_lsn in [510, 520, 530, 511, 512]:
            f.seek(try_lsn * SACD_SECTOR)
            sec = f.read(SACD_SECTOR)
            if len(sec) >= 8 and sec[:8] == MTOC_MAGIC:
                area_toc_lsn = struct.unpack_from('>I', sec, 0x40)[0]
                area_size    = struct.unpack_from('>I', sec, 0x44)[0]
                print(f"    Master TOC @ LSN {try_lsn}: Area TOC LSN={area_toc_lsn} size={area_size}")
                break

        if area_toc_lsn is None:
            print("    [경고] Master TOC 미발견 — LSN 0부터 읽기 (fallback)")
            return 0, 4096

        # ② SACDTRL1 섹터 찾기 (Area TOC + 1~5 내에 있음)
        first_track_lsn = None
        total_track_sectors = None
        for offset in range(1, 10):
            f.seek((area_toc_lsn + offset) * SACD_SECTOR)
            trl = f.read(SACD_SECTOR)
            if len(trl) >= 8 and trl[:8] == TRL1_MAGIC:
                print(f"    SACDTRL1 @ LSN {area_toc_lsn + offset}")
                # 0x08부터 4바이트 BE LSN 목록 (첫 값=Track1 시작, 마지막 값=end marker)
                lsn_list = []
                off = 0x08
                while off + 4 <= len(trl):
                    val = struct.unpack_from('>I', trl, off)[0]
                    if val == 0 and lsn_list:
                        break
                    if val > 0:
                        lsn_list.append(val)
                    off += 4

                if lsn_list:
                    first_track_lsn = lsn_list[0]
                    # 마지막 값은 end_marker → 전체 트랙 영역 크기
                    if len(lsn_list) > 1:
                        total_track_sectors = lsn_list[-1] - lsn_list[0]
                    else:
                        total_track_sectors = area_size
                    print(f"    트랙 LSN 목록: {lsn_list}")
                    print(f"    → 첫 트랙 시작 LSN={first_track_lsn}")
                break

        if first_track_lsn is None:
            print(f"    [경고] SACDTRL1 미발견 — Area TOC LSN {area_toc_lsn}부터 읽기 (fallback)")
            return area_toc_lsn, area_size

        return first_track_lsn, total_track_sectors or area_size

start_lsn, area_size = find_audio_lsn(iso_path)
READ_SECTORS = min(area_size, 3000)  # 최대 ~6MB (첫 트랙 기준)
print(f"[3] LSN {start_lsn}부터 {READ_SECTORS}섹터 읽기")

with open(iso_path, 'rb') as f:
    f.seek(start_lsn * SACD_SECTOR)
    data = f.read(READ_SECTORS * SACD_SECTOR)

actual_sectors = len(data) // SACD_SECTOR
print(f"    실제 읽음: {actual_sectors}섹터 ({len(data)//1024}KB)")

# ── 4. 프레임 추출 + 디코딩 ────────────────────────────────────
channels = 2
frame_dsd_size = (588 * 64 // 8) * channels  # DSD64 스테레오 = 9408 bytes/frame

dec = DSTDecoder(channels=channels, fs_factor=64)
dsd_buf = bytearray()
last_good = b'\x55' * frame_dsd_size

stats = {'ok': 0, 'fail': 0, 'noise_ch0': 0, 'noise_ch1': 0, 'sizes': []}
frame_count = 0

print(f"\n[4] 프레임 디코딩 (stderr 무시하고 아래 결과 확인):")
print(f"    {'#':>4} {'크기':>6} {'결과':>5} {'Ch0 패턴':>18} {'Ch1 패턴':>18} {'판정'}")
print(f"    {'-'*80}")

# extract_dst_frames는 stderr에 SEC_DBG/FRAME_DBG 출력함 (정상)
for frame_data, frame_idx, is_raw in extract_dst_frames(data, channels=channels):
    if is_raw:
        continue  # rawDSD 섹터는 이 진단에서 스킵

    if frame_count >= MAX_FRAMES:
        break

    dsd = dec.decode_frame(frame_data)
    stats['sizes'].append(len(frame_data))

    if dsd is None:
        stats['fail'] += 1
        dsd_buf.extend(last_good)
        if frame_count < 20:
            print(f"    {frame_count:4d} {len(frame_data):6d} {'FAIL':>5}")
    else:
        stats['ok'] += 1
        last_good = bytes(dsd)
        dsd_buf.extend(dsd)

        # Ch0, Ch1 노이즈 분석 (첫 64바이트 기준)
        ch0_bytes = bytes(dsd[0::2][:64])
        ch1_bytes = bytes(dsd[1::2][:64])

        # 실제 코럽트 노이즈 감지:
        # - 0x55/0xAA = DSD 무음(직류 0) → 정상 신호일 수 있으므로 무시
        # - 0x00/0xFF = DSD ±포화 상태 → 진짜 오류 패턴
        # 단순 반복 패턴 감지: 64바이트 중 고유값이 2개 이하이고
        # 그 값이 {0x00, 0xFF, 0x55, 0xAA} 조합이면 의심
        def is_corrupt(b):
            unique = set(b)
            corrupt_set = {0x00, 0xFF, 0x55, 0xAA}
            # 고유값이 3개 미만이고 전부 corrupt_set이면 의심
            if len(unique) <= 2 and unique.issubset(corrupt_set):
                # 단, 0x55/0xAA만 있으면 DSD 무음이므로 제외
                if unique.issubset({0x55, 0xAA}):
                    return False, 'silence'
                return True, 'corrupt'
            return False, 'music'

        def noise_ratio(b):
            return sum(1 for x in b if x in (0x55, 0xAA, 0x00, 0xFF)) / len(b)

        nr0 = noise_ratio(ch0_bytes)
        nr1 = noise_ratio(ch1_bytes)
        c0, label0 = is_corrupt(ch0_bytes)
        c1, label1 = is_corrupt(ch1_bytes)
        n0  = c0
        n1  = c1

        if n0: stats['noise_ch0'] += 1
        if n1: stats['noise_ch1'] += 1

        if frame_count < 20:
            verdict = ''
            if n0 and n1:
                verdict = '← 양채널 코럽트!'
            elif n0:
                verdict = f'← Ch0 {label0}'
            elif n1:
                verdict = f'← Ch1 {label1}'
            elif label0 == 'silence' or label1 == 'silence':
                verdict = '(무음 구간)'
            print(f"    {frame_count:4d} {len(frame_data):6d} {'OK':>5}  "
                  f"Ch0={ch0_bytes[:8].hex()} ({nr0:.0%}/{label0})  "
                  f"Ch1={ch1_bytes[:8].hex()} ({nr1:.0%}/{label1})  {verdict}")

    frame_count += 1

print(f"\n[4] 요약:")
print(f"    총 {frame_count}프레임: OK={stats['ok']}, FAIL={stats['fail']}")
if stats['sizes']:
    import statistics
    print(f"    프레임 크기: min={min(stats['sizes'])}, max={max(stats['sizes'])}, "
          f"중앙값={statistics.median(stats['sizes']):.0f}")
ok_frames = stats['ok']
if ok_frames > 0:
    print(f"    성공 프레임 중: Ch0 노이즈={stats['noise_ch0']}/{ok_frames} "
          f"({100*stats['noise_ch0']/ok_frames:.0f}%)")
    print(f"    성공 프레임 중: Ch1 노이즈={stats['noise_ch1']}/{ok_frames} "
          f"({100*stats['noise_ch1']/ok_frames:.0f}%)")

# ── 5. DSD → PCM 변환 ─────────────────────────────────────────
print(f"\n[5] DSD→PCM 변환 중 ({len(dsd_buf)//1024}KB DSD)...")
if not dsd_buf:
    print("[!] DSD 데이터 없음")
    sys.exit(1)

pcm, _, pcm_sr = dsd_bytes_to_pcm_sacd(
    bytes(dsd_buf), channels, decimation=16, dsd_sr=2822400, zi_list=None
)
print(f"    출력: {pcm.shape} @ {pcm_sr}Hz, "
      f"최대진폭={np.abs(pcm).max():.4f}")

if np.abs(pcm).max() < 0.001:
    print("    [경고] 출력 신호 거의 없음 (무음). 디코더 문제 가능성 높음.")
elif np.abs(pcm).max() > 1.5:
    print("    [경고] 출력이 클리핑 수준 이상. 데이터 이상 가능성.")
else:
    print("    [정보] 출력 신호 정상 범위.")

# ── 6. WAV 저장 ────────────────────────────────────────────────
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'diag_output.wav')
pcm_clipped = np.clip(pcm, -1.0, 1.0)
pcm_int16 = (pcm_clipped * 32767).astype(np.int16)

with wave.open(out_path, 'w') as wf:
    wf.setnchannels(channels)
    wf.setsampwidth(2)
    wf.setframerate(pcm_sr)
    wf.writeframes(pcm_int16.tobytes())

duration = pcm.shape[0] / pcm_sr
print(f"\n[6] WAV 저장 완료:")
print(f"    {out_path}")
print(f"    {duration:.2f}초, {channels}채널, {pcm_sr}Hz")

# ── 7. 결론 ────────────────────────────────────────────────────
print("\n" + "="*60)
print("[ 결론 판정 ]")
noise_pct = 100 * stats['noise_ch0'] / max(1, ok_frames)
fail_pct  = 100 * stats['fail'] / max(1, frame_count)

print(f"  디코딩 실패율: {fail_pct:.0f}%")
print(f"  Ch0 노이즈 비율: {noise_pct:.0f}%")

if fail_pct > 30:
    print("  → DST 디코더가 많은 프레임을 실패 처리합니다.")
    print("    원인: 프레임 크기 이상, 또는 DST bitstream 오류")

if noise_pct > 30:
    print("  → 성공한 프레임 중 Ch0가 코럽트 패턴 (0x00/0xFF 포화)")
    print("    원인 후보: 프레임 경계 오류, 디코더 내부 버그")
    print("    (0x55/0xAA 단독 패턴은 DSD 무음으로 정상입니다)")

print()
print("  diag_output.wav를 열어서 들어보세요:")
print("  ✓ 음악 → 디코더는 정상, 앱 파이프라인(PCM 변환/출력) 문제")
print("  ✗ 노이즈 → DST 디코더 버그 (dst_fram.c 수정 필요)")
print("  ✗ 무음 → 0x55 패턴이 실제 음악의 무음 구간 가능성")
print("="*60)
