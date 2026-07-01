#!/usr/bin/env python3
"""모든 data_type별 데이터 내용 확인"""
ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

def hexdump(data, n=32):
    return ' '.join(f'{b:02X}' for b in data[:n])

def run_avg(data):
    if not data: return 0
    runs, cur, l = [], data[0]>>7&1, 1
    for b in data[:256]:
        for i in range(7,-1,-1):
            bit = (b>>i)&1
            if bit==cur: l+=1
            else: runs.append(l); cur=bit; l=1
    return sum(runs)/len(runs) if runs else 0

# data_type별 누적
dt_data = {}
with open(ISO, 'rb') as f:
    for lsn in range(648, 700):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        hdr = sec[0]
        fi = (hdr >> 3) & 7
        pi = hdr & 7
        if (hdr>>7)&1: continue

        ptr = 1
        pkt_dt, pkt_pl = [], []
        for _ in range(pi):
            b0=sec[ptr]; b1=sec[ptr+1]; ptr+=2
            pkt_dt.append((b0>>3)&7)
            pkt_pl.append((b0&7)<<8|b1)
        ptr += fi * 4

        for j in range(len(pkt_dt)):
            plen = pkt_pl[j]
            dt = pkt_dt[j]
            data = sec[ptr:ptr+plen]
            if dt not in dt_data and plen > 8:
                dt_data[dt] = data
            ptr += plen

print("=== data_type별 첫 데이터 샘플 ===")
for dt in sorted(dt_data.keys()):
    data = dt_data[dt]
    rl = run_avg(data)
    ones = sum(bin(b).count('1') for b in data[:256]) / (256*8)
    print(f"\ndt={dt} (len={len(data)}):")
    print(f"  hex: {hexdump(data, 24)}")
    print(f"  런 길이 평균: {rl:.2f}  1비트 비율: {ones:.3f}")
    if rl > 3.0:
        print(f"  → 저주파 신호 (음악적)")
    elif rl < 2.1:
        print(f"  → 랜덤/압축 데이터")

# data_type 분포
print("\n=== LSN 648~680 data_type 분포 ===")
dt_bytes = {}
with open(ISO, 'rb') as f:
    for lsn in range(648, 680):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        hdr = sec[0]
        fi = (hdr >> 3) & 7
        pi = hdr & 7
        if (hdr>>7)&1: continue
        ptr = 1
        pkt_dt, pkt_pl = [], []
        for _ in range(pi):
            b0=sec[ptr]; b1=sec[ptr+1]; ptr+=2
            pkt_dt.append((b0>>3)&7)
            pkt_pl.append((b0&7)<<8|b1)
        ptr += fi * 4
        for j in range(len(pkt_dt)):
            dt = pkt_dt[j]
            dt_bytes[dt] = dt_bytes.get(dt, 0) + pkt_pl[j]
            ptr += pkt_pl[j]

for dt, total in sorted(dt_bytes.items()):
    print(f"  dt={dt}: {total} bytes ({total/sum(dt_bytes.values())*100:.1f}%)")
