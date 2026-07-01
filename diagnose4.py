#!/usr/bin/env python3
"""
Jeff Beck ISO — DST 섹터 분포 전수조사
: 실제 트랙 LSN 범위에서 dst_encoded=1인 섹터 비율 확인
"""
import struct

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

# 1. Master TOC에서 트랙 LSN 목록 읽기
def read_toc(f):
    # Master TOC: sector 510
    f.seek(510 * SECTOR_SIZE)
    master = f.read(SECTOR_SIZE)

    # SACD_SECTOR_SIZE offset 들에서 2ch TOC LSN 찾기
    # Master TOC: offset 0x58 = twoch_area LSN
    twoch_lsn = struct.unpack_from('>I', master, 0x58)[0]
    print(f"2ch TOC LSN: {twoch_lsn}")

    # 2ch TOC: sector twoch_lsn
    f.seek(twoch_lsn * SECTOR_SIZE)
    twoch = f.read(SECTOR_SIZE)

    # TWOCHTOC: track count at offset 1, track LSNs at offset 8+
    # sacd_disc.h: sacdtoc_t
    track_count = twoch[1]
    print(f"Track count: {track_count}")

    track_lsns = []
    for i in range(track_count):
        lsn = struct.unpack_from('>I', twoch, 8 + i * 8)[0]
        track_lsns.append(lsn)
        print(f"  Track {i+1}: LSN {lsn}")

    return track_lsns

# 2. 특정 LSN 범위에서 dst_encoded 비율 조사
def scan_dst(f, start_lsn, count=200):
    dst_count = 0
    raw_count = 0
    for i in range(count):
        f.seek((start_lsn + i) * SECTOR_SIZE)
        data = f.read(1)
        if not data:
            break
        hdr = data[0]
        dst_encoded = (hdr >> 7) & 1
        if dst_encoded:
            dst_count += 1
        else:
            raw_count += 1
    total = dst_count + raw_count
    print(f"  LSN {start_lsn}~{start_lsn+total-1}: DST={dst_count}, raw={raw_count} (DST {dst_count/total*100:.1f}%)")
    return dst_count

with open(ISO, 'rb') as f:
    try:
        track_lsns = read_toc(f)
    except Exception as e:
        print(f"TOC 읽기 실패: {e}")
        track_lsns = [645]  # fallback

    print("\n=== DST 섹터 분포 스캔 ===")
    for i, lsn in enumerate(track_lsns[:3]):  # 첫 3트랙만
        print(f"Track {i+1} (LSN {lsn}):")
        scan_dst(f, lsn, 100)

    # 645 근방도 스캔
    print("\nLSN 640~680 스캔:")
    for lsn in range(640, 680):
        f.seek(lsn * SECTOR_SIZE)
        data = f.read(1)
        if data:
            hdr = data[0]
            dst = (hdr >> 7) & 1
            pic = (hdr >> 3) & 7
            ppc = hdr & 7
            if dst:
                print(f"  LSN {lsn}: hdr=0x{hdr:02X} DST=1 fi={pic} pi={ppc}")
