#!/usr/bin/env python3
"""
Jeff Beck ISO — Master TOC 정밀 파싱
scarletbook.h 구조 기반
"""
import struct

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

def hexdump(data, length=64):
    for i in range(0, min(length, len(data)), 16):
        chunk = data[i:i+16]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        asc_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"  {i:04X}: {hex_part:<47}  {asc_part}")

with open(ISO, 'rb') as f:
    # Master TOC는 sector 510
    print("=== Master TOC (sector 510) ===")
    f.seek(510 * SECTOR_SIZE)
    master = f.read(256)
    hexdump(master, 128)

    # sector 511도 확인
    print("\n=== Sector 511 ===")
    f.seek(511 * SECTOR_SIZE)
    s511 = f.read(64)
    hexdump(s511, 64)

    # sector 512 (SACDMasterTOC 두번째 복사본?)
    print("\n=== Sector 512 ===")
    f.seek(512 * SECTOR_SIZE)
    s512 = f.read(64)
    hexdump(s512, 64)

    # SACD ID 찾기 — "SACDMTOC" 시그니처
    print("\n=== 'SACDMTOC' 시그니처 검색 (sector 505~520) ===")
    for s in range(505, 520):
        f.seek(s * SECTOR_SIZE)
        data = f.read(16)
        sig = data[:8]
        print(f"  sector {s}: {sig} ({sig.hex()})")

    # DST 섹터 LSN 640~646 — 이 7섹터가 뭔지 확인
    print("\n=== DST 섹터 LSN 640~646 첫 16바이트 ===")
    for lsn in range(640, 647):
        f.seek(lsn * SECTOR_SIZE)
        data = f.read(48)
        hdr = data[0]
        dst = (hdr >> 7) & 1
        fi  = (hdr >> 3) & 7
        pi  = hdr & 7
        # frame_info bytes
        ptr = 1 + pi*2
        print(f"  LSN {lsn}: hdr=0x{hdr:02X} dst={dst} fi={fi} pi={pi}")
        print(f"    frame_info: {data[ptr:ptr+fi*4].hex()}")
        # audio data
        audio_start = 1 + pi*2 + fi*4
        print(f"    audio[0:16]: {data[audio_start:audio_start+16].hex()}")

    # LSN 647 (첫 raw 섹터)
    print("\n=== LSN 647 (첫 raw DSD 섹터) ===")
    f.seek(647 * SECTOR_SIZE)
    data = f.read(64)
    hdr = data[0]
    print(f"  hdr=0x{hdr:02X}  dst={(hdr>>7)&1}  fi={(hdr>>3)&7}  pi={hdr&7}")
    hexdump(data, 64)
