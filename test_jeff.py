#!/usr/bin/env python3
"""Jeff Beck ISO 재생 테스트 — 새 패킷 파서 검증"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from sacd_decoder import SACDDecoder, _dsd_bits_to_pcm

ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"

dec = SACDDecoder()
tracks = dec.get_track_list(ISO)
print(f"트랙 수: {len(tracks)}")
for t in tracks:
    print(f"  [{t['index']+1}] {t['title']}  LSN={t['lsn']}  size={t['size']}  dur={t['duration']:.1f}s")

if not tracks:
    print("ERROR: 트랙 없음")
    sys.exit(1)

# 트랙 1의 첫 512섹터로 오디오 데이터 추출 테스트
t = tracks[0]
print(f"\n트랙 1 첫 512섹터 오디오 추출 테스트 (LSN {t['lsn']})...")

import struct
SECTOR_SIZE = 2048

def extract_audio(iso_path, lsn, n_sectors, channels):
    result = bytearray()
    with open(iso_path, 'rb') as f:
        for i in range(n_sectors):
            f.seek((lsn + i) * SECTOR_SIZE)
            sec = f.read(SECTOR_SIZE)
            if not sec:
                break
            hdr = sec[0]
            dst_encoded       = (hdr >> 7) & 1
            frame_info_count  = (hdr >> 3) & 7
            packet_info_count = hdr & 7

            if dst_encoded:
                continue  # 타임코드 섹터 건너뜀

            ptr = 1
            pkt_dt = []
            pkt_pl = []
            for _ in range(packet_info_count):
                if ptr + 2 > len(sec): break
                b0 = sec[ptr]; b1 = sec[ptr+1]; ptr += 2
                pkt_dt.append((b0 >> 3) & 7)
                pkt_pl.append((b0 & 7) << 8 | b1)

            ptr += frame_info_count * 4

            for i2 in range(len(pkt_dt)):
                plen = pkt_pl[i2]
                if ptr + plen > len(sec): break
                if pkt_dt[i2] in (1, 2):
                    result.extend(sec[ptr:ptr+plen])
                ptr += plen
    return bytes(result)

# 32섹터만 테스트
audio = extract_audio(ISO, t['lsn'], 32, t['channels'])
print(f"추출된 오디오 바이트 (32섹터): {len(audio)}")

if len(audio) == 0:
    print("ERROR: 오디오 데이터 없음")
    sys.exit(1)

# PCM 변환 — 앞 4KB만
from dsd_decoder import _get_fir, _bits_to_pcm

channels = t['channels']
fir = _get_fir(64)
sample = audio[:4096]  # 4KB만
arr = np.frombuffer(sample, dtype=np.uint8)
usable = (len(arr) // channels) * channels
arr = arr[:usable]

ch0 = arr[0::channels]
bits = np.unpackbits(ch0).astype(np.float32)
pcm = _bits_to_pcm(bits, 64, fir)

amp = float(np.abs(pcm).max())
rms = float(np.sqrt(np.mean(pcm**2)))
print(f"PCM 샘플 수: {len(pcm)}")
print(f"PCM 최대 진폭: {amp:.4f}")
print(f"PCM RMS: {rms:.4f}")

if amp > 0.001:
    print("✓ 오디오 신호 감지됨! 재생 가능")
else:
    print("✗ 진폭이 너무 낮음 — 파싱 문제")
    # 오디오 바이트 샘플 출력
    print(f"  audio[0:32] = {audio[:32].hex()}")
