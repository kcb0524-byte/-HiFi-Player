#!/bin/bash
python3 << 'PYEOF'
ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

frames = []
frame_buf = bytearray()
in_frame = False
carry_buf = bytearray()
carry_need = 0
carry_fs = carry_dt = 0

with open(ISO, 'rb') as f:
    for lsn in range(647, 2000):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        if not sec: continue
        hdr = sec[0]
        if (hdr >> 7) & 1: continue
        fi=(hdr>>3)&7; pi=hdr&7; ptr=1
        pkts=[]
        for _ in range(pi):
            if ptr+2>len(sec): break
            b0,b1=sec[ptr],sec[ptr+1]; ptr+=2
            pkts.append(((b0>>7)&1,(b0>>3)&7,(b0&7)<<8|b1))
        ptr+=fi*4; payload=sec[ptr:]; sptr=0
        if carry_need>0:
            take=min(len(payload)-sptr,carry_need)
            carry_buf+=payload[sptr:sptr+take]; carry_need-=take; sptr+=take
            if carry_need==0:
                if carry_dt in(1,2):
                    if carry_fs:
                        if in_frame and frame_buf: frames.append(bytes(frame_buf))
                        frame_buf=bytearray(carry_buf); in_frame=True
                    elif in_frame: frame_buf+=carry_buf
                carry_buf=bytearray()
        for fs,dt,pl in pkts:
            avail=len(payload)-sptr
            if avail>=pl:
                pd=payload[sptr:sptr+pl]; sptr+=pl
                if dt in(1,2):
                    if fs:
                        if in_frame and frame_buf: frames.append(bytes(frame_buf))
                        frame_buf=bytearray(pd); in_frame=True
                    elif in_frame: frame_buf+=pd
            else:
                carry_fs,carry_dt=fs,dt
                carry_buf=bytearray(payload[sptr:]); carry_need=pl-avail; break
    if in_frame and frame_buf: frames.append(bytes(frame_buf))

print(f"총 프레임: {len(frames)}")

# 각 프레임 분류
uncompressed = []
dst_compressed = []
for i, f in enumerate(frames):
    if not f: continue
    b = f[0]
    if (b >> 7) == 0:
        uncompressed.append((i, f))
    else:
        dst_compressed.append((i, f))

print(f"비압축 DSD: {len(uncompressed)}개")
print(f"DST 압축:   {len(dst_compressed)}개")

def run_avg(data, n=512):
    runs, cur, l = [], None, 0
    for byte in bytes(data[:n]):
        for i in range(7,-1,-1):
            bit=(byte>>i)&1
            if cur is None: cur=bit;l=1
            elif bit==cur: l+=1
            else: runs.append(l);cur=bit;l=1
    if l: runs.append(l)
    return sum(runs)/len(runs) if runs else 0

print("\n=== 비압축 DSD 프레임 분석 ===")
for i, (fi, f) in enumerate(uncompressed[:5]):
    # ffmpeg dstdec.c: bit7=0 → data[1:]이 raw DSD
    raw_dsd = f[1:]
    # 채널 수 추정: 2채널이면 홀/짝 바이트가 각 채널
    # frame_size = nb_samples * channels * 4 (float format)
    # 실제로는 DSD bytes: nb_samples/8 * channels
    # DST_SAMPLES_PER_FRAME(2822400) = 588*512 = 301056 bits = 37632 bytes total
    # 2채널: 37632 / 2 = 18816 bytes/ch
    print(f"F{fi}({len(f)}B) 비압축DSD raw={len(raw_dsd)}B")
    
    # 2채널 인터리브 가정: ch0=짝수, ch1=홀수
    ch0 = bytes(raw_dsd[0::2])
    ch1 = bytes(raw_dsd[1::2])
    print(f"  ch0 run={run_avg(ch0):.2f}  ch1 run={run_avg(ch1):.2f}")
    print(f"  ch0 첫8B: {' '.join(f'{b:02X}' for b in ch0[:8])}")
    
    # 단순 순서도 시도
    r_all = run_avg(raw_dsd)
    print(f"  전체 run={r_all:.2f}")

print("\n=== DST 압축 프레임 첫바이트 패턴 ===")
for i,(fi,f) in enumerate(dst_compressed[:10]):
    b=f[0]
    print(f"F{fi}({len(f)}B) 0x{b:02X}={b:08b} bit6={( b>>6)&1}")
PYEOF
