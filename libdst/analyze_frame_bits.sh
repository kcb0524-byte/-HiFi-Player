#!/bin/bash
# 첫 DST 프레임의 헤더 비트 분석
python3 << 'PYEOF'
ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

# 추출 로직 (test_dst2.c와 동일)
frames = []
frame_buf = bytearray()
in_frame = False
carry_buf = bytearray()
carry_need = 0
carry_fs = carry_dt = 0

with open(ISO, 'rb') as f:
    for lsn in range(647, 900):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        if not sec: continue
        hdr = sec[0]
        if (hdr >> 7) & 1: continue
        fi = (hdr >> 3) & 7
        pi = hdr & 7
        ptr = 1
        pkts = []
        for _ in range(pi):
            if ptr + 2 > len(sec): break
            b0, b1 = sec[ptr], sec[ptr+1]; ptr += 2
            pkts.append(((b0>>7)&1, (b0>>3)&7, (b0&7)<<8|b1))
        ptr += fi * 4
        payload = sec[ptr:]
        sptr = 0

        if carry_need > 0:
            take = min(len(payload) - sptr, carry_need)
            carry_buf += payload[sptr:sptr+take]
            carry_need -= take; sptr += take
            if carry_need == 0:
                if carry_dt in (1,2):
                    if carry_fs:
                        if in_frame and frame_buf: frames.append(bytes(frame_buf))
                        frame_buf = bytearray(carry_buf); in_frame = True
                    elif in_frame: frame_buf += carry_buf
                carry_buf = bytearray()

        for fs, dt, pl in pkts:
            avail = len(payload) - sptr
            if avail >= pl:
                pkt_data = payload[sptr:sptr+pl]; sptr += pl
                if dt in (1,2):
                    if fs:
                        if in_frame and frame_buf: frames.append(bytes(frame_buf))
                        frame_buf = bytearray(pkt_data); in_frame = True
                    elif in_frame: frame_buf += pkt_data
            else:
                carry_fs, carry_dt = fs, dt
                carry_buf = bytearray(payload[sptr:]); carry_need = pl - avail; break

    if in_frame and frame_buf: frames.append(bytes(frame_buf))

print(f"추출 프레임: {len(frames)}")
for fi, f in enumerate(frames[:5]):
    b = f[0]
    bit0 = (b >> 7) & 1  # DST compressed flag
    bit1 = (b >> 6) & 1  # Same Segmentation
    bit2 = (b >> 5) & 1  # Same Segmentation For All Channels  
    bit3 = (b >> 4) & 1  # End Of Channel Segmentation
    print(f"F{fi}({len(f)}B) 첫바이트=0x{b:02X} bit[7..0]={b:08b}")
    print(f"  bit7(DST=1/DSD=0)={bit0}  bit6(SameSeg)={bit1}  bit5(SameSegAll)={bit2}  bit4(EndSeg)={bit3}")
    print(f"  첫16B: {' '.join(f'{x:02X}' for x in f[:16])}")

    # ffmpeg dstdec.c 동작 시뮬레이션
    if bit0 == 0:
        print(f"  → 비압축 DSD 경로 (첫바이트 bit7=0)")
    else:
        print(f"  → DST 압축 경로")
        if bit1 == 0:
            print(f"  → 'Not Same Segmentation' 오류 발생!")
        elif bit2 == 0:
            print(f"  → 'Not Same Segmentation For All Channels' 오류!")
        elif bit3 == 0:
            print(f"  → 'Not End Of Channel Segmentation' 오류!")
        else:
            print(f"  → 정상 DST 프레임")
    print()
PYEOF
