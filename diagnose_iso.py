#!/usr/bin/env python3
"""
SACD ISO 진단 스크립트
사용법: python3 diagnose_iso.py <파일.iso>
"""
import sys, struct

SECTOR = 2048

def read_sector(f, lsn):
    f.seek(lsn * SECTOR)
    return f.read(SECTOR)

def hexdump(data, limit=64, prefix=''):
    for i in range(0, min(len(data), limit), 16):
        chunk = data[i:i+16]
        hex_part  = ' '.join(f'{b:02x}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"{prefix}  {i:04x}: {hex_part:<47}  {ascii_part}")

def analyze(path):
    print(f"\n{'='*60}")
    print(f"파일: {path}")
    print('='*60)

    with open(path, 'rb') as f:
        f.seek(0, 2)
        file_size = f.tell()
        total_sectors = file_size // SECTOR
        print(f"파일 크기: {file_size:,} bytes ({total_sectors:,} sectors)")

        # ── Master TOC ────────────────────────────────────
        master = None
        for lsn in (510, 511, 512):
            sec = read_sector(f, lsn)
            if sec[:8] == b'SACDMTOC':
                master = sec
                master_lsn = lsn
                print(f"\n[Master TOC] sector={lsn}")
                break
        if master is None:
            print("!! Master TOC를 찾을 수 없음 — SACD ISO가 아닌 파일")
            return

        # Album title (offset 0x10~0x3f)
        album_raw = master[0x10:0x40]
        album = album_raw.rstrip(b'\x00').decode('utf-8', errors='replace').strip()
        print(f"  Album title raw: {album_raw[:32].hex()}")
        print(f"  Album title    : {repr(album)}")

        twoch_lsn  = struct.unpack_from('>I', master, 0x40)[0]
        twoch_size = struct.unpack_from('>I', master, 0x44)[0]
        mulch_lsn  = struct.unpack_from('>I', master, 0x50)[0]
        mulch_size = struct.unpack_from('>I', master, 0x54)[0]
        print(f"  2ch  area: LSN={twoch_lsn} size={twoch_size}")
        print(f"  Multi area: LSN={mulch_lsn} size={mulch_size}")

        # ── Area TOC ──────────────────────────────────────
        for area_label, area_lsn in [('2ch', twoch_lsn), ('Multi', mulch_lsn)]:
            if area_lsn == 0:
                continue
            sec = read_sector(f, area_lsn)
            magic = sec[:8]
            magic_str = magic.rstrip(b'\x00').decode('ascii', errors='replace')
            print(f"\n[{area_label} Area TOC] sector={area_lsn} magic='{magic_str}'")
            if magic not in (b'TWOCHTOC', b'MULCHTOC'):
                print("  !! 유효한 Area TOC 아님")
                continue

            print(f"  첫 128바이트 dump:")
            hexdump(sec, 128, '')

            version    = struct.unpack_from('>H', sec, 0x08)[0]
            area_desc  = struct.unpack_from('>H', sec, 0x0a)[0]
            channels   = sec[0x14]
            freq_raw   = struct.unpack_from('>I', sec, 0x10)[0]
            track_cnt1 = struct.unpack_from('>H', sec, 0x16)[0]
            track_cnt2 = struct.unpack_from('>H', sec, 0x20)[0]
            track_cnt3 = struct.unpack_from('>H', sec, 0x22)[0]

            print(f"\n  version   : 0x{version:04x}")
            print(f"  area_desc : 0x{area_desc:04x}  (bit5-7=frame_format, 0=DSD/1=DST)")
            # frame_format is in bits [5:3] of area_desc high byte
            frame_fmt = (area_desc >> 8) & 0x07
            print(f"  frame_format (bits): {frame_fmt}  {'→ DST 압축!' if frame_fmt != 0 else '→ Raw DSD (정상)'}")
            print(f"  channels  : {channels}")
            print(f"  freq_raw  : 0x{freq_raw:08x} = {freq_raw}")
            print(f"  track_cnt : 0x16={track_cnt1}  0x20={track_cnt2}  0x22={track_cnt3}")

            # ── SACDTRL1 스캔 ──
            print(f"\n  [SACDTRL1 스캔]")
            trl1_found = False
            blob = bytearray()
            for i in range(16):
                try:
                    blob.extend(read_sector(f, area_lsn + i))
                except:
                    break

            for i in range(1, 10):
                s = bytes(blob[i*SECTOR:(i+1)*SECTOR])
                if s[:8] == b'SACDTRL1':
                    print(f"    SACDTRL1 발견: area_lsn+{i}")
                    print(f"    첫 80바이트:")
                    hexdump(s, 80, '')
                    trl1_found = True
                    # LSN 파싱
                    lsn_list = []
                    off = 0x08
                    while off + 4 <= len(s):
                        v = struct.unpack_from('>I', s, off)[0]
                        if v == 0 and lsn_list:
                            break
                        if v > 0:
                            lsn_list.append(v)
                        elif v == 0 and not lsn_list:
                            off += 4
                            continue
                        off += 4
                    print(f"    LSN 목록: {lsn_list}")
                    break
            if not trl1_found:
                print("    SACDTRL1 없음")
                # TWOCHTOC 0x40 폴백 스캔
                print("    0x40 fallback 스캔:")
                off = 0x40
                entries = []
                while off + 8 <= SECTOR:
                    byte_addr = struct.unpack_from('>I', sec, off)[0]
                    size_sec  = struct.unpack_from('>I', sec, off+4)[0]
                    lsn_v = byte_addr // SECTOR
                    if byte_addr == 0 and size_sec == 0 and entries:
                        break
                    if byte_addr > 0:
                        entries.append((lsn_v, size_sec))
                        print(f"      off=0x{off:04x}: byte_addr=0x{byte_addr:08x} lsn={lsn_v} size={size_sec}")
                    off += 8

            # ── SACDTTxt 스캔 ──
            print(f"\n  [SACDTTxt 스캔]")
            for i in range(1, 16):
                s = bytes(blob[i*SECTOR:(i+1)*SECTOR])
                if s[:8] == b'SACDTTxt':
                    print(f"    SACDTTxt 발견: area_lsn+{i}")
                    print(f"    첫 128바이트:")
                    hexdump(s, 128, '')
                    break
            else:
                print("    SACDTTxt 없음")

            # ── 첫 번째 트랙 DSD 데이터 샘플 ──
            print(f"\n  [첫 트랙 DSD 데이터 분석]")
            # 첫 SACDTRL1 LSN 사용
            if trl1_found and lsn_list:
                first_lsn = lsn_list[0]
            elif area_lsn > 0:
                first_lsn = area_lsn + 10
            else:
                continue

            if first_lsn < total_sectors:
                f.seek(first_lsn * SECTOR)
                raw_sector = f.read(SECTOR)

                print(f"    Track 1 sector (LSN={first_lsn}) 첫 64바이트 (헤더 포함):")
                hexdump(raw_sector, 64, '')

                # 헤더 32바이트 제거 후 DSD 데이터
                dsd = raw_sector[32:32+256] if len(raw_sector) >= 288 else raw_sector[32:]
                avg = sum(dsd) / len(dsd) if dsd else 0
                print(f"\n    DSD 데이터 (offset 32~) 첫 32바이트:")
                hexdump(dsd, 32, '')
                print(f"    DSD 바이트 평균: {avg:.1f}  (정상 Raw DSD ≈ 128, DST/헤더 ≈ 다양)")

                # DST 싱크 패턴 체크
                if len(dsd) >= 2:
                    b0, b1 = dsd[0], dsd[1]
                    dst_hint = ''
                    if (b0 == 0x7f and b1 == 0xfe) or (b0 == 0xfe and b1 == 0x7f):
                        dst_hint = ' ← DST 싱크 패턴! DST 압축 가능성 높음'
                    elif (b0 == 0x1f and b1 == 0xff) or (b0 == 0xff and b1 == 0x1f):
                        dst_hint = ' ← DST 싱크(역순) 가능성'
                    print(f"    첫 2바이트: 0x{b0:02x} 0x{b1:02x}{dst_hint}")

                # 헤더 0, 4, 8 바이트 오프셋 시 DSD 평균 비교
                print(f"\n    헤더 오프셋별 평균 바이트값 (Raw DSD는 ≈128이어야 함):")
                for off in [0, 4, 8, 12, 16, 32]:
                    d = raw_sector[off:off+256]
                    a = sum(d)/len(d) if d else 0
                    marker = ' ◀ 128에 가장 가까움' if abs(a - 128) < 5 else ''
                    print(f"      offset {off:2d}: avg={a:6.1f}{marker}")

    print(f"\n{'='*60}")
    print("진단 완료")
    print('='*60)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("사용법: python3 diagnose_iso.py <파일.iso>")
        print("       python3 diagnose_iso.py /path/to/file1.iso /path/to/file2.iso")
        sys.exit(1)
    for path in sys.argv[1:]:
        try:
            analyze(path)
        except Exception as e:
            print(f"\n오류: {e}")
            import traceback; traceback.print_exc()
