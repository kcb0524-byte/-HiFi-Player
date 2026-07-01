#!/bin/bash
# DST 출력 포맷 분석
python3 << 'PYEOF'
# 첫 8바이트가 0x69 0x69 0x69 0x69 0x96 0x96 0x69 0x69 패턴
# 0x69 = 01101001, 0x96 = 10010110
# 이것은 DSD 무음(사일런스) 패턴: 0x69 반복이 DSD 사일런스
# DSD 사일런스 = 0x55 or 0x69 패턴

b = 0x69
print(f"0x69 = {b:08b}")
print(f"0x96 = {0x96:08b}")
print(f"0x55 = {0x55:08b}")
print(f"0xAA = {0xAA:08b}")

# DSD 특성: run length
# 0x69 = 01101001 → run: 1,2,1,1,1,2 → avg ~1.4
# 0x96 = 10010110 → run: 1,2,1,1,1,2 → avg ~1.4

# 실제 DSD 음악은 run이 길어야 함 (3~6+)
# 지금 1.3~1.4는 0x69/0x96/0xAA 같은 고주파 패턴

# 가능성 1: DSD 비트 역전 (LSB first → MSB first)
def reverse_bits(b):
    return int(f'{b:08b}'[::-1], 2)

sample = [0x69, 0x96, 0xAA, 0x55]
print("\n비트 역전:")
for b in sample:
    r = reverse_bits(b)
    print(f"  0x{b:02X} ({b:08b}) → 0x{r:02X} ({r:08b})")

# 0x69 역전 → 0x96, 0x96 역전 → 0x69 (같은 패턴)
# 0xAA → 0x55, 0x55 → 0xAA

# 가능성 2: 채널 분리가 다른 방식
# DST_FramDSTDecode MuxedDSD: 
# 채널 0 데이터 4704바이트 + 채널 1 데이터 4704바이트 (연속)
# OR
# 인터리브 방식 (4바이트 단위?)

print("\n0x69 run avg 계산:")
data = bytes([0x69]*100)
runs,cur,l=[],None,0
for byte in data:
    for i in range(7,-1,-1):
        bit=(byte>>i)&1
        if cur is None: cur=bit;l=1
        elif bit==cur: l+=1
        else: runs.append(l);cur=bit;l=1
if l: runs.append(l)
print(f"  {sum(runs)/len(runs):.2f}")
PYEOF
