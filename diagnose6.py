#!/usr/bin/env python3
"""
Jeff Beck ISO — SACDTRL1 실제 구조 파악
"""
import struct

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

def hexdump(data, length=128, offset=0):
    for i in range(0, min(length, len(data)), 16):
        chunk = data[i:i+16]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        asc_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"  {offset+i:04X}: {hex_part:<47}  {asc_part}")

with open(ISO, 'rb') as f:
    # Master TOC에서 twoch_lsn 읽기
    f.seek(510 * SECTOR_SIZE)
    master = f.read(SECTOR_SIZE)
    twoch_lsn = struct.unpack_from('>I', master, 0x40)[0]
    print(f"twoch_lsn = {twoch_lsn} (0x{twoch_lsn:X})")

    # TWOCHTOC 섹터 덤프
    print(f"\n=== TWOCHTOC (sector {twoch_lsn}) ===")
    f.seek(twoch_lsn * SECTOR_SIZE)
    twochtoc = f.read(SECTOR_SIZE)
    hexdump(twochtoc, 128)

    # 다음 섹터들 시그니처 확인
    print(f"\n=== 섹터 시그니처 ({twoch_lsn}~{twoch_lsn+10}) ===")
    for i in range(11):
        lsn = twoch_lsn + i
        f.seek(lsn * SECTOR_SIZE)
        sig = f.read(8)
        print(f"  sector {lsn}: {sig} ({sig.hex()})")

    # SACDTRL1 찾기
    trl1_lsn = None
    for i in range(1, 10):
        lsn = twoch_lsn + i
        f.seek(lsn * SECTOR_SIZE)
        sig = f.read(8)
        if sig == b'SACDTRL1':
            trl1_lsn = lsn
            break

    if trl1_lsn:
        print(f"\n=== SACDTRL1 (sector {trl1_lsn}) ===")
        f.seek(trl1_lsn * SECTOR_SIZE)
        trl1 = f.read(SECTOR_SIZE)
        hexdump(trl1, 256)

        # LSN 값 파싱 시도 — 여러 해석
        print("\n-- 4바이트 BE 해석 (offset 0x08~) --")
        for off in range(0x08, 0x08 + 80, 4):
            val = struct.unpack_from('>I', trl1, off)[0]
            print(f"  off {off:04X}: {val:10d}  (0x{val:08X})  /2048={val//2048}")

    # SACDTTxt 찾기
    print(f"\n=== SACDTTxt 검색 ===")
    for i in range(2, 20):
        lsn = twoch_lsn + i
        f.seek(lsn * SECTOR_SIZE)
        sig = f.read(8)
        if sig == b'SACDTTxt':
            print(f"  SACDTTxt at sector {lsn}")
            f.seek(lsn * SECTOR_SIZE)
            txt = f.read(SECTOR_SIZE)
            hexdump(txt, 256)
            break
