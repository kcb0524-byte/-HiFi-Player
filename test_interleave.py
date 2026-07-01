#!/usr/bin/env python3
"""채널 인터리브 방식 테스트"""
ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

# dt=2 오디오만 모음
audio = bytearray()
with open(ISO, 'rb') as f:
    for lsn in range(648, 800):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        hdr = sec[0]
        if (hdr>>7)&1: continue
        fi=(hdr>>3)&7; pi=hdr&7
        ptr=1
        pdt,ppl=[],[]
        for _ in range(pi):
            b0=sec[ptr];b1=sec[ptr+1];ptr+=2
            pdt.append((b0>>3)&7)
            ppl.append((b0&7)<<8|b1)
        ptr+=fi*4
        for j in range(len(pdt)):
            if pdt[j]==2 and ppl[j]>0:
                audio.extend(sec[ptr:ptr+ppl[j]])
            ptr+=ppl[j]
        if len(audio)>65536: break

def run_avg(data, step=1, offset=0):
    """step바이트 간격으로 추출한 채널의 런 길이"""
    ch = bytes(data[offset::step])[:4096]
    if not ch: return 0
    runs,cur,l=[],None,0
    for b in ch:
        for i in range(7,-1,-1):
            bit=(b>>i)&1
            if cur is None: cur=bit; l=1
            elif bit==cur: l+=1
            else: runs.append(l);cur=bit;l=1
    if l>0: runs.append(l)
    return sum(runs)/len(runs) if runs else 0

def run_avg_le(data, step=1, offset=0):
    """little-endian 비트 순서"""
    ch = bytes(data[offset::step])[:4096]
    if not ch: return 0
    runs,cur,l=[],None,0
    for b in ch:
        for i in range(8):
            bit=(b>>i)&1
            if cur is None: cur=bit; l=1
            elif bit==cur: l+=1
            else: runs.append(l);cur=bit;l=1
    if l>0: runs.append(l)
    return sum(runs)/len(runs) if runs else 0

print(f"총 오디오: {len(audio)}B")
print(f"첫 32B: {bytes(audio[:32]).hex()}")

print("\n=== 채널 분리 방식별 런 길이 ===")
print("(2.0=노이즈, >3.0=음악 신호)")
print()

# 1. 바이트 인터리브 2ch
print("바이트 인터리브 (ch0=짝수, ch1=홀수):")
print(f"  ch0 big:    {run_avg(audio,2,0):.2f}")
print(f"  ch1 big:    {run_avg(audio,2,1):.2f}")
print(f"  ch0 little: {run_avg_le(audio,2,0):.2f}")
print(f"  ch1 little: {run_avg_le(audio,2,1):.2f}")

# 2. 인터리브 없이 전체
print("\n전체(인터리브 없음):")
print(f"  big:    {run_avg(audio,1,0):.2f}")
print(f"  little: {run_avg_le(audio,1,0):.2f}")

# 3. 앞 절반=ch0, 뒤 절반=ch1 (프레임 분할)
half = len(audio)//2
print("\n프레임 분할 (앞=ch0, 뒤=ch1):")
print(f"  ch0 big:    {run_avg(audio[:half],1,0):.2f}")
print(f"  ch1 big:    {run_avg(audio[half:],1,0):.2f}")

# 4. 패킷별로 ch 교대 가능성
# pkt[0]=ch0+ch1 interleaved per sample(2B), pkt[1]=next frame
# 각 패킷이 단일 채널일 가능성
print("\n패킷 단위 분리: pkt[0]만 (첫 1152B):")
p0 = audio[:1152]
print(f"  전체 big:    {run_avg(p0,1,0):.2f}")
print(f"  짝수B big:   {run_avg(p0,2,0):.2f}")
print(f"  홀수B big:   {run_avg(p0,2,1):.2f}")
