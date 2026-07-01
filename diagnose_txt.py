#!/usr/bin/env python3
"""SACDTTxt LSN 581 파싱"""
import struct

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048
TXT_LSN = 581

def hexdump(data, length=256):
    for i in range(0, min(length, len(data)), 16):
        chunk = data[i:i+16]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        asc_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"  {i:04X}: {hex_part:<47}  {asc_part}")

with open(ISO, 'rb') as f:
    # SACDTTxt 섹터들 읽기 (581~590)
    blob = bytearray()
    for lsn in range(TXT_LSN, TXT_LSN + 10):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        sig = sec[:8]
        print(f"LSN {lsn}: {sig}")
        if sig == b'SACDTTxt':
            blob.extend(sec)
        elif blob:  # SACDTTxt 이후 연속 섹터
            blob.extend(sec)

    print(f"\n=== SACDTTxt 첫 섹터 (LSN {TXT_LSN}) ===")
    f.seek(TXT_LSN * SECTOR_SIZE)
    txt = f.read(SECTOR_SIZE)
    hexdump(txt, 512)

    # 오프셋 테이블 파싱
    print("\n=== 오프셋 테이블 (0x08~) ===")
    offsets = []
    for i in range(40):
        off = struct.unpack_from('>H', txt, 0x08 + i*2)[0]
        print(f"  [{i:2d}] 0x{0x08+i*2:04X}: offset=0x{off:04X} ({off})")
        if off == 0 and i > 0:
            break
        if off > 0:
            offsets.append(off)

    print(f"\n=== 각 오프셋 텍스트 추출 ===")
    for i, off in enumerate(offsets[:12]):
        if off >= len(blob):
            print(f"  [{i}] off=0x{off:04X} — 범위 초과")
            continue
        chunk = blob[off:off+64]
        print(f"  [{i}] off=0x{off:04X}: {chunk[:32].hex()}")
        # 여러 해석 시도
        # 1. offset+4 부터 null-terminated ASCII
        if len(chunk) > 4:
            data = chunk[4:]
            nul = data.find(b'\x00')
            txt_ascii = data[:nul].decode('latin-1', errors='replace') if nul > 0 else data[:16].decode('latin-1', errors='replace')
            print(f"       ASCII(+4): '{txt_ascii}'")
        # 2. UTF-16BE
        try:
            t = chunk[4:].decode('utf-16-be', errors='ignore').rstrip('\x00')
            if t.isprintable() and len(t) > 1:
                print(f"       UTF16BE: '{t}'")
        except:
            pass
        # 3. 모든 printable 바이트
        printable = ''.join(chr(b) if 32<=b<127 else '.' for b in chunk)
        print(f"       raw: '{printable}'")
