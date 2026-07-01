"""헤더 크기별로 max 값 비교 테스트"""
import sys, struct
import numpy as np
sys.path.insert(0, '/sessions/youthful-determined-noether/mnt/outputs/hifi_player')
from dsd_decoder import _get_fir, _bits_to_pcm

SECTOR = 2048

def test_decode(iso_path, track_lsn, hdr_size, channels=2, n_sectors=4):
    fir = _get_fir(64)
    dsd_data = bytearray()
    with open(iso_path, 'rb') as f:
        for i in range(n_sectors):
            f.seek((track_lsn + i) * SECTOR)
            sec = f.read(SECTOR)
            dsd_data.extend(sec[hdr_size:])
    
    arr = np.frombuffer(bytes(dsd_data), dtype=np.uint8)
    usable = (len(arr) // channels) * channels
    arr = arr[:usable]
    
    results = {}
    for bitorder in ['little', 'big']:
        pcm_chs = []
        for ch in range(channels):
            ch_bytes = arr[ch::channels]
            bits = np.unpackbits(ch_bytes, bitorder=bitorder).astype(np.float32)
            pcm = _bits_to_pcm(bits, 64, fir)
            pcm_chs.append(pcm)
        mn = min(len(c) for c in pcm_chs)
        pcm_all = np.column_stack([c[:mn] for c in pcm_chs])
        results[bitorder] = (np.abs(pcm_all).max(), np.abs(pcm_all).mean())
    
    return results

iso = "/Volumes/ HD/임시 음악/Bill Withers - Bill Withers' Greatest Hits (1981) [SACD] (2016 MFSL Remaster ISO)/2015 MFSL Inc. - Bill Withers' Greatest Hits.iso"
track_lsn = 1252

print("헤더 크기별 / bitorder별 max 비교:")
for hdr in [0, 4, 8, 16, 32, 64]:
    r = test_decode(iso, track_lsn, hdr)
    for bo, (mx, mn_v) in r.items():
        print(f"  hdr={hdr:2d}  bitorder={bo:6s}  max={mx:.4f}  mean={mn_v:.4f}")
    print()
