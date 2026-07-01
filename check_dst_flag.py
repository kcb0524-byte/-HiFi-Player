#!/usr/bin/env python3
"""
DST ISO 여부 확인 — Master TOC / Area TOC 플래그
+ DST 프레임 sync word 탐색
"""
import struct

JEFF = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

def hexdump(data, n=64):
    lines = []
    for i in range(0, min(n, len(data)), 16):
        h = ' '.join(f'{b:02X}' for b in data[i:i+16])
        a = ''.join(chr(b) if 32<=b<127 else '.' for b in data[i:i+16])
        lines.append(f"  {i:04X}: {h:<48}  |{a}|")
    return '\n'.join(lines)

with open(JEFF, 'rb') as f:
    # ── Master TOC 전체 덤프 ────────────────────────────
    f.seek(510 * SECTOR_SIZE)
    mtoc = f.read(SECTOR_SIZE)
    print("=== Master TOC (LSN 510) 첫 128B ===")
    print(hexdump(mtoc, 128))

    print()
    # ── Area TOC (LSN 544) 전체 덤프 ──────────────────
    f.seek(544 * SECTOR_SIZE)
    atoc = f.read(SECTOR_SIZE)
    print("=== Area TOC (LSN 544 TWOCHTOC) 첫 128B ===")
    print(hexdump(atoc, 128))

    print()
    # Area TOC의 DST 관련 플래그
    # offset 0x0A-0x0B: area_description (bit flags)
    area_desc = struct.unpack_from('>H', atoc, 0x0A)[0]
    print(f"area_description = 0x{area_desc:04X} = {area_desc:016b}")
    print(f"  bit 15 (dst_encoded?): {(area_desc>>15)&1}")
    print(f"  bit 14: {(area_desc>>14)&1}")
    print(f"  bit 13: {(area_desc>>13)&1}")
    print(f"  기타 플래그들: {area_desc & 0xFF:08b}")

    # offset 0x10: sample_freq
    sf = struct.unpack_from('>I', atoc, 0x10)[0]
    print(f"sample_freq = 0x{sf:08X} = {sf}")

    # offset 0x14: channel_count
    print(f"channel_count = {atoc[0x14]}")

    # offset 0x18-0x1F: 추가 flags
    print(f"offset 0x18-0x1F: {' '.join(f'{atoc[0x18+i]:02X}' for i in range(8))}")

    print()
    # ── SACDTRL1 (LSN 545) ────────────────────────────
    f.seek(545 * SECTOR_SIZE)
    trl1 = f.read(SECTOR_SIZE)
    print("=== SACDTRL1 (LSN 545) 첫 64B ===")
    print(hexdump(trl1, 64))

    print()
    # ── DST 프레임 sync 탐색 ──────────────────────────
    # DST spec: 프레임은 sync word로 시작
    # DSDIFF DST chunk: 'DSTF' magic
    # ISO DST: sector header bit7=1 (dst_encoded)

    # LSN 640~647은 이전에 DST라고 확인된 섹터
    print("=== DST 섹터 (LSN 640~647) 헤더 확인 ===")
    for lsn in range(640, 648):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(16)
        hdr = sec[0]
        dst = (hdr>>7)&1
        fi  = (hdr>>3)&7
        pi  = hdr&7
        print(f"  LSN {lsn}: hdr=0x{hdr:02X} dst={dst} fi={fi} pi={pi}  "
              f"next8B: {' '.join(f'{sec[i]:02X}' for i in range(1,9))}")

    print()
    # LSN 640 (DST섹터) vs LSN 648 (오디오섹터) 비교
    f.seek(640 * SECTOR_SIZE)
    dst_sec = f.read(SECTOR_SIZE)
    f.seek(648 * SECTOR_SIZE)
    audio_sec = f.read(SECTOR_SIZE)

    print("=== DST 섹터 (LSN 640) vs 오디오 섹터 (LSN 648) 비교 ===")
    print("DST 섹터 (hdr bit7=1) 첫 64B:")
    print(hexdump(dst_sec, 64))
    print()
    print("오디오 섹터 (hdr bit7=0) 첫 64B:")
    print(hexdump(audio_sec, 64))

    print()
    # ── 핵심: 오디오 섹터 dt=2 데이터의 엔트로피 vs DST 섹터 비교 ──
    def entropy_check(data, name):
        from collections import Counter
        cnt = Counter(data[:256])
        import math
        total = sum(cnt.values())
        h = -sum((v/total)*math.log2(v/total) for v in cnt.values() if v>0)
        ones = sum(bin(b).count('1') for b in data[:256])/(256*8)
        print(f"  {name}: 엔트로피={h:.2f}bits/byte (최대8), 1비율={ones:.3f}")

    print("=== 엔트로피 비교 (8에 가까울수록 압축/암호화된 데이터) ===")
    # dt=2 오디오
    hdr=audio_sec[0]; fi=(hdr>>3)&7; pi=hdr&7
    ptr=1+pi*2+fi*4
    dt2_data = audio_sec[ptr:ptr+256]
    entropy_check(dt2_data, "오디오 섹터 dt=2 첫256B")

    # DST 섹터 데이터
    hdr2=dst_sec[0]; fi2=(hdr2>>3)&7; pi2=hdr2&7
    ptr2=1+pi2*2+fi2*4
    entropy_check(dst_sec[ptr2:ptr2+256], "DST 섹터 데이터 첫256B")

    # DSD silence (0x69) 참고값
    silence = bytes([0x69]*256)
    entropy_check(silence, "DSD 무음(0x69) 참고값  ")

    # 정상 DSD 참고: 연속적인 부드러운 값
    import random
    random.seed(42)
    # 정상 DSD는 낮은 주파수 → 긴 런 → 낮은 엔트로피
    normal_dsd = bytes([0xFF]*8 + [0x00]*8)*16  # 극단적 저주파
    entropy_check(normal_dsd, "저주파DSD(참고값)      ")
