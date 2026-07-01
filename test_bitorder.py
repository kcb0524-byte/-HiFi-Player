#!/usr/bin/env python3
"""비트 순서 테스트 — numpy 없이 순수 Python"""
import struct, math

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

# 오디오 데이터 추출 (LSN 648~680, raw DSD 섹터들)
audio = bytearray()
with open(ISO, 'rb') as f:
    for lsn in range(648, 680):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        hdr = sec[0]
        dst = (hdr >> 7) & 1
        fi  = (hdr >> 3) & 7
        pi  = hdr & 7
        if dst:
            continue
        ptr = 1
        pkt_dt, pkt_pl = [], []
        for _ in range(pi):
            b0 = sec[ptr]; b1 = sec[ptr+1]; ptr += 2
            pkt_dt.append((b0 >> 3) & 7)
            pkt_pl.append((b0 & 7) << 8 | b1)
        ptr += fi * 4
        for j in range(len(pkt_dt)):
            plen = pkt_pl[j]
            if pkt_dt[j] in (1, 2):
                audio.extend(sec[ptr:ptr+plen])
            ptr += plen

print(f"오디오 바이트: {len(audio)}")
print(f"처음 16바이트: {bytes(audio[:16]).hex()}")

# 간단한 DSD→진폭 추정 (채널 0만, 첫 1024바이트)
# 각 바이트의 1 비트 개수 → 0.5 기준 편차
def avg_ones(data, bitorder='big'):
    total = 0
    count = 0
    for b in data[:1024]:
        if bitorder == 'big':
            bits = [(b >> (7-i)) & 1 for i in range(8)]
        else:
            bits = [(b >> i) & 1 for i in range(8)]
        # 채널0만 (2채널 인터리브에서 짝수 바이트)
        total += sum(bits)
        count += 8
    return total / count if count > 0 else 0

# ch0만 추출
ch0 = bytes(audio[0::2][:1024])
ones_big = avg_ones(ch0, 'big')
ones_lit = avg_ones(ch0, 'little')

print(f"\n비트 1의 비율 (0.5=무음, 편차클수록 신호있음):")
print(f"  big-endian:    {ones_big:.4f}  (편차: {abs(ones_big-0.5):.4f})")
print(f"  little-endian: {ones_lit:.4f}  (편차: {abs(ones_lit-0.5):.4f})")

# 간단한 저주파 통과 — 연속 1의 런 길이 히스토그램
def run_lengths(data, bitorder='big'):
    runs = []
    current = None
    length = 0
    for b in data[:512]:
        if bitorder == 'big':
            bits = [(b >> (7-i)) & 1 for i in range(8)]
        else:
            bits = [(b >> i) & 1 for i in range(8)]
        for bit in bits:
            if bit == current:
                length += 1
            else:
                if current is not None:
                    runs.append(length)
                current = bit
                length = 1
    return runs

runs_big = run_lengths(ch0, 'big')
runs_lit = run_lengths(ch0, 'little')

avg_big = sum(runs_big)/len(runs_big) if runs_big else 0
avg_lit = sum(runs_lit)/len(runs_lit) if runs_lit else 0
print(f"\n평균 런 길이 (길수록 저주파 신호 = 음악):")
print(f"  big-endian:    {avg_big:.2f}")
print(f"  little-endian: {avg_lit:.2f}")
print(f"\n→ {'big' if avg_big > avg_lit else 'little'}-endian이 더 음악적 신호")
