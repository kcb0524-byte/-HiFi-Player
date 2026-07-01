#!/usr/bin/env python3
"""순수 Python — numpy/scipy 없이 패킷 파싱만 테스트"""
import struct

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048
START_LSN = 645  # 트랙1 시작

audio_bytes = 0
dst_skipped = 0

with open(ISO, 'rb') as f:
    for i in range(32):
        lsn = START_LSN + i
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)

        hdr = sec[0]
        dst_encoded       = (hdr >> 7) & 1
        frame_info_count  = (hdr >> 3) & 7
        packet_info_count = hdr & 7

        if dst_encoded:
            dst_skipped += 1
            continue

        ptr = 1
        pkt_dt, pkt_pl = [], []
        for _ in range(packet_info_count):
            b0 = sec[ptr]; b1 = sec[ptr+1]; ptr += 2
            pkt_dt.append((b0 >> 3) & 7)
            pkt_pl.append((b0 & 7) << 8 | b1)
        ptr += frame_info_count * 4

        sec_audio = 0
        for j in range(len(pkt_dt)):
            plen = pkt_pl[j]
            if pkt_dt[j] in (1, 2):
                sec_audio += plen
            ptr += plen

        audio_bytes += sec_audio
        print(f"LSN {lsn}: hdr=0x{hdr:02X} dst={dst_encoded} pi={packet_info_count} audio={sec_audio}B")

print(f"\nDST 건너뜀: {dst_skipped}섹터")
print(f"총 오디오 바이트: {audio_bytes}")
print(f"예상 재생시간(DSD64 2ch): {audio_bytes/(352800):.2f}초")
