#!/usr/bin/env python3
"""섹터 패킷 상세 분석 — 모든 data_type 확인"""
ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

def hexdump(data, n=32):
    return ' '.join(f'{b:02X}' for b in data[:n])

with open(ISO, 'rb') as f:
    # LSN 648: hdr=0x45, pi=5, 오디오 3331B
    for target_lsn in [648, 649, 650]:
        f.seek(target_lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        hdr = sec[0]
        fi  = (hdr >> 3) & 7
        pi  = hdr & 7
        print(f"\n=== LSN {target_lsn}: hdr=0x{hdr:02X} fi={fi} pi={pi} ===")

        ptr = 1
        pkt_dt, pkt_pl, pkt_fs = [], [], []
        for _ in range(pi):
            b0 = sec[ptr]; b1 = sec[ptr+1]; ptr += 2
            pkt_fs.append((b0 >> 7) & 1)
            pkt_dt.append((b0 >> 3) & 7)
            pkt_pl.append((b0 & 7) << 8 | b1)

        # frame_info
        for i in range(fi):
            fb = sec[ptr:ptr+4]
            print(f"  frame[{i}]: {fb.hex()}")
            ptr += 4

        # 각 패킷
        audio_ptr = ptr
        for j in range(len(pkt_dt)):
            plen = pkt_pl[j]
            data = sec[ptr:ptr+plen]
            print(f"  pkt[{j}]: fs={pkt_fs[j]} dt={pkt_dt[j]} len={plen}")
            print(f"    data: {hexdump(data, 16)}")
            ptr += plen

        # 헤더 크기 계산
        header_size = audio_ptr
        print(f"  헤더 크기: {header_size}바이트")
        print(f"  헤더 이후 첫 16B: {hexdump(sec[header_size:], 16)}")

        # 고정 오프셋 시도 (32바이트)
        print(f"  고정 32B 오프셋 후: {hexdump(sec[32:], 16)}")
