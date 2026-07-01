#!/usr/bin/env python3
"""
DST 섹터 파서 상세 진단 — dst_cli.c 파싱 로직 검증용
"""
import sys, struct

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048
START_LSN = 645

def parse_sector(data, sec_idx):
    ptr = 0
    hdr = data[ptr]; ptr += 1
    dst_encoded       = (hdr >> 7) & 1
    frame_info_count  = (hdr >> 3) & 7
    packet_info_count = (hdr >> 0) & 7

    print(f"\n=== Sector {sec_idx} (LSN {START_LSN+sec_idx}) ===")
    print(f"  hdr=0x{hdr:02X}  dst_encoded={dst_encoded}  frame_info_count={frame_info_count}  packet_info_count={packet_info_count}")

    pkts = []
    for i in range(packet_info_count):
        b0 = data[ptr]; b1 = data[ptr+1]; ptr += 2
        fs  = (b0 >> 7) & 1
        dt  = (b0 >> 3) & 7
        pl  = (b0 & 7) << 8 | b1
        pkts.append((fs, dt, pl))
        print(f"  pkt[{i}]: frame_start={fs}  data_type={dt}  packet_length={pl}")

    frames = []
    for i in range(frame_info_count):
        fb = data[ptr:ptr+4]; ptr += 4
        sc_v1 = (fb[3] >> 1) & 0x1f   # C코드 현재값
        sc_v2 = (fb[3] >> 2) & 0x1f   # 이전값
        sc_v3 = (fb[3] >> 0) & 0x1f   # 마스크만
        frames.append(sc_v1)
        print(f"  frame[{i}]: raw bytes={fb.hex()}  sc(>>1)={sc_v1}  sc(>>2)={sc_v2}  sc(>>0 &1f)={sc_v3}")

    # 오디오 데이터 오프셋
    audio_offset = ptr
    print(f"  audio data offset={audio_offset}")

    # 각 패킷 데이터 첫 8바이트
    for i, (fs, dt, pl) in enumerate(pkts):
        if dt == 2 and pl > 0:
            chunk = data[ptr:ptr+min(8,pl)]
            print(f"  pkt[{i}] audio data (first 8): {chunk.hex()}")
        ptr += pl

    return pkts, frames

with open(ISO, 'rb') as f:
    for sec_idx in range(10):
        f.seek((START_LSN + sec_idx) * SECTOR_SIZE)
        data = f.read(SECTOR_SIZE)
        parse_sector(data, sec_idx)

# DST_InitDecoder 파라미터 확인용 — dst_init.h에서 ebunch 크기 확인
print("\n\n=== ebunch 구조 확인 (dst_init.c 소스 필요) ===")
import subprocess
r = subprocess.run(['grep', '-n', 'ebunch\|EBUNCH\|sizeof',
                    '/tmp/sacd-ripper/libs/libdstdec/dst_init.h'],
                   capture_output=True, text=True)
print(r.stdout[:2000])
