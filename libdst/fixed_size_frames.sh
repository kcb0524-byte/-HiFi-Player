#!/bin/bash
python3 << 'PYEOF'
import math

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048
FRAME_SIZE = 4704  # DSD64 bytes/ch/frame (1채널 기준)

# 모든 dt=1,2 데이터를 순서대로 수집 (fs 무시, 크로스섹터 지원)
raw_stream = bytearray()
carry_buf = bytearray()
carry_need = 0
carry_dt = 0

with open(ISO, 'rb') as f:
    for lsn in range(647, 1500):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        if not sec: continue
        hdr = sec[0]
        if (hdr>>7)&1: continue
        fi=(hdr>>3)&7; pi=hdr&7; ptr=1
        pkts=[]
        for _ in range(pi):
            if ptr+2>len(sec): break
            b0,b1=sec[ptr],sec[ptr+1]; ptr+=2
            pkts.append(((b0>>3)&7,(b0&7)<<8|b1))  # dt, pl (fs 무시)
        ptr+=fi*4; payload=sec[ptr:]; sptr=0

        if carry_need>0:
            take=min(len(payload)-sptr,carry_need)
            carry_buf+=payload[sptr:sptr+take]; carry_need-=take; sptr+=take
            if carry_need==0:
                if carry_dt in(1,2): raw_stream.extend(carry_buf)
                carry_buf=bytearray()

        for dt,pl in pkts:
            avail=len(payload)-sptr
            if avail>=pl:
                if dt in(1,2): raw_stream.extend(payload[sptr:sptr+pl])
                sptr+=pl
            else:
                carry_dt=dt
                carry_buf=bytearray(payload[sptr:]); carry_need=pl-avail; break

print(f"수집된 총 데이터: {len(raw_stream)}B")
print(f"예상 프레임 수 (4704B 기준): {len(raw_stream)//FRAME_SIZE}")

def run_avg(data, n=1024):
    runs,cur,l=[],None,0
    for byte in bytes(data[:n]):
        for i in range(7,-1,-1):
            bit=(byte>>i)&1
            if cur is None: cur=bit;l=1
            elif bit==cur: l+=1
            else: runs.append(l);cur=bit;l=1
    if l: runs.append(l)
    return sum(runs)/len(runs) if runs else 0

def entropy(data, n=512):
    cnt=[0]*256
    for b in bytes(data[:n]): cnt[b]+=1
    n2=min(n,len(data))
    return -sum(c/n2*math.log2(c/n2) for c in cnt if c>0)

# 고정 크기 4704B 청크로 분석
print("\n=== 고정 4704B 청크 분석 ===")
for i in range(min(8, len(raw_stream)//FRAME_SIZE)):
    chunk = raw_stream[i*FRAME_SIZE:(i+1)*FRAME_SIZE]
    ra = run_avg(chunk)
    ent = entropy(chunk)
    b0 = chunk[0]
    print(f"청크{i}: run={ra:.2f}  entropy={ent:.2f}  첫바이트=0x{b0:02X}={b0:08b}")

# 첫 청크가 비압축이면 data[1:]이 raw DSD
print("\n=== 첫 청크를 비압축DSD로 해석 ===")
chunk0 = raw_stream[:FRAME_SIZE]
print(f"첫바이트 bit7={( chunk0[0]>>7)&1}")
if (chunk0[0]>>7)==0:
    raw_dsd = chunk0[1:]
    ch0 = bytes(raw_dsd[0::2])
    ch1 = bytes(raw_dsd[1::2])
    print(f"ch0 run={run_avg(ch0):.2f}  ch1 run={run_avg(ch1):.2f}")
    print(f"ch0 첫8B: {' '.join(f'{b:02X}' for b in ch0[:8])}")

# 2채널이므로 실제 프레임 크기는 4704*2=9408바이트일 수도
print("\n=== 고정 9408B (2ch) 청크 분석 ===")
FRAME2 = 4704 * 2
for i in range(min(5, len(raw_stream)//FRAME2)):
    chunk = raw_stream[i*FRAME2:(i+1)*FRAME2]
    ra = run_avg(chunk)
    ent = entropy(chunk)
    b0 = chunk[0]
    print(f"청크{i}: run={ra:.2f}  entropy={ent:.2f}  첫바이트=0x{b0:02X}={b0:08b}")
    if (b0>>7)==0:
        raw_dsd = chunk[1:]
        ch0 = bytes(raw_dsd[0::2])
        print(f"  비압축DSD ch0 run={run_avg(ch0):.2f}")
PYEOF
