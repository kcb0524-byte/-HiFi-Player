#!/usr/bin/env python3
"""Jeff Beck ISO 오디오 섹터 심층 분석 — DSD 비트 구조 확인"""
import struct, sys

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"
SECTOR_SIZE = 2048

def hexdump(data, n=32):
    return ' '.join(f'{b:02X}' for b in data[:n])

def run_avg_bits(data, bitorder='big', max_bytes=512):
    runs, cur, l = [], None, 0
    for b in data[:max_bytes]:
        bits = [(b>>(7-i))&1 for i in range(8)] if bitorder=='big' else [(b>>i)&1 for i in range(8)]
        for bit in bits:
            if cur is None: cur=bit; l=1
            elif bit==cur: l+=1
            else: runs.append(l); cur=bit; l=1
    if l: runs.append(l)
    return sum(runs)/len(runs) if runs else 0

def rev_bits(b):
    return int(f'{b:08b}'[::-1], 2)

with open(ISO, 'rb') as f:
    # ── 1. LSN 648 패킷 상세 ──────────────────────────────
    f.seek(648 * SECTOR_SIZE)
    sec = f.read(SECTOR_SIZE)
    hdr=sec[0]; fi=(hdr>>3)&7; pi=hdr&7
    print(f"=== LSN 648: hdr=0x{hdr:02X} dst={(hdr>>7)&1} fi={fi} pi={pi} ===")
    ptr=1; pkts=[]
    for _ in range(pi):
        b0=sec[ptr];b1=sec[ptr+1];ptr+=2
        pkts.append(((b0>>7)&1,(b0>>3)&7,(b0&7)<<8|b1))
    ptr+=fi*4
    print(f"오디오 데이터 시작 오프셋: {ptr}")
    raw_audio=bytearray()
    for i,(fs,dt,pl) in enumerate(pkts):
        data=sec[ptr:ptr+pl]
        rl=run_avg_bits(bytes(data),'big',min(pl,256))
        ones=sum(bin(b).count('1') for b in data[:256])/(min(pl,256)*8) if data else 0
        print(f"  pkt[{i}] fs={fs} dt={dt} len={pl}: 1비율={ones:.3f} run={rl:.2f}  첫8B={hexdump(data,8)}")
        if dt in (1,2): raw_audio.extend(data)
        ptr+=pl

    print()
    print(f"첫 섹터 raw_audio: {len(raw_audio)}B")
    print(f"원본 첫 32B: {hexdump(raw_audio,32)}")

    # ── 2. 비트 변형 테스트 ───────────────────────────────
    print()
    print("=== 비트 변형별 런 길이 (높을수록 저주파=음악) ===")
    test_data = bytes(raw_audio[:2048])
    variants = {
        '원본(big)':    (test_data, 'big'),
        '원본(little)': (test_data, 'little'),
        '비트반전(big)': (bytes(b^0xFF for b in test_data), 'big'),
        '비트순서역(big)': (bytes(rev_bits(b) for b in test_data), 'big'),
        '비트순서역(lit)': (bytes(rev_bits(b) for b in test_data), 'little'),
    }
    for name,(data,order) in variants.items():
        rl = run_avg_bits(data, order, 512)
        ones = sum(bin(b).count('1') for b in data[:256])/(256*8)
        print(f"  {name:20s}: run={rl:.2f}  1비율={ones:.3f}")

    # ── 3. 채널 분리 방식 테스트 ─────────────────────────
    print()
    print("=== 채널 분리 방식별 런 길이 ===")
    # 여러 섹터에서 오디오 모음
    all_audio = bytearray()
    for lsn in range(648, 680):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        hdr=sec[0]
        if (hdr>>7)&1: continue
        fi=(hdr>>3)&7; pi=hdr&7
        ptr=1; pkts=[]
        for _ in range(pi):
            b0=sec[ptr];b1=sec[ptr+1];ptr+=2
            pkts.append(((b0>>7)&1,(b0>>3)&7,(b0&7)<<8|b1))
        ptr+=fi*4
        for fs,dt,pl in pkts:
            if dt in (1,2): all_audio.extend(sec[ptr:ptr+pl])
            ptr+=pl
        if len(all_audio)>65536: break

    print(f"수집된 오디오: {len(all_audio)}B")
    # 바이트 인터리브 2ch
    ch0=bytes(all_audio[0::2]); ch1=bytes(all_audio[1::2])
    print(f"  2ch 인터리브 ch0 big:  {run_avg_bits(ch0,'big',512):.2f}")
    print(f"  2ch 인터리브 ch1 big:  {run_avg_bits(ch1,'big',512):.2f}")
    print(f"  2ch 인터리브 ch0 lit:  {run_avg_bits(ch0,'little',512):.2f}")
    # 패킷별 채널 (각 패킷=단일채널 가능성)
    print(f"  전체 연속 big:         {run_avg_bits(bytes(all_audio),'big',512):.2f}")
    print(f"  전체 연속 lit:         {run_avg_bits(bytes(all_audio),'little',512):.2f}")
    # 앞절반=ch0, 뒤절반=ch1
    h=len(all_audio)//2
    print(f"  앞절반 ch0 big:        {run_avg_bits(bytes(all_audio[:h]),'big',512):.2f}")
    print(f"  뒤절반 ch1 big:        {run_avg_bits(bytes(all_audio[h:]),'big',512):.2f}")

    # ── 4. frame_start 패킷의 데이터 vs 중간 패킷 비교 ──
    print()
    print("=== frame_start=1 패킷 vs 일반 패킷 데이터 비교 ===")
    fs1_data=bytearray(); fsN_data=bytearray()
    for lsn in range(648, 700):
        f.seek(lsn * SECTOR_SIZE)
        sec = f.read(SECTOR_SIZE)
        hdr=sec[0]
        if (hdr>>7)&1: continue
        fi=(hdr>>3)&7; pi=hdr&7
        ptr=1; pkts=[]
        for _ in range(pi):
            b0=sec[ptr];b1=sec[ptr+1];ptr+=2
            pkts.append(((b0>>7)&1,(b0>>3)&7,(b0&7)<<8|b1))
        ptr+=fi*4
        for fs,dt,pl in pkts:
            if dt in (1,2):
                if fs==1 and len(fs1_data)<4096: fs1_data.extend(sec[ptr:ptr+pl])
                elif fs==0 and len(fsN_data)<4096: fsN_data.extend(sec[ptr:ptr+pl])
            ptr+=pl
        if len(fs1_data)>4096 and len(fsN_data)>4096: break

    print(f"  frame_start=1: {len(fs1_data)}B, run={run_avg_bits(bytes(fs1_data),'big',512):.2f}, 첫8B={hexdump(fs1_data,8)}")
    print(f"  frame_start=0: {len(fsN_data)}B, run={run_avg_bits(bytes(fsN_data),'big',512):.2f}, 첫8B={hexdump(fsN_data,8)}")

    # ── 5. DFF/DSF 파일이 있다면 비교 ───────────────────
    print()
    print("=== 분석 완료 ===")
    print("런 길이 > 3.0 → 저주파 음악 신호 (DSD 정상)")
    print("런 길이 ≈ 2.0 → 랜덤/압축/잘못된 인터프리테이션")
