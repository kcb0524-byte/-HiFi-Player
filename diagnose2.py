"""
제프 벡 ISO 구조 진단 — 실제 트랙 LSN과 섹터 데이터 덤프
"""
import sys, struct, numpy as np

ISO_PATH = sys.argv[1] if len(sys.argv) > 1 else "/Volumes/HD/임시 음악/Jeff Beck.iso"
SECTOR = 2048

def read_sector(f, lsn):
    f.seek(lsn * SECTOR)
    return f.read(SECTOR)

def find_magic(f, magic, search_range=range(500, 560)):
    for lsn in search_range:
        try:
            sec = read_sector(f, lsn)
            if sec[:len(magic)] == magic:
                print(f"  [{magic}] found at LSN={lsn}")
                return lsn, sec
        except: pass
    return None, None

with open(ISO_PATH, 'rb') as f:
    print("=== Master TOC ===")
    mtoc_lsn, mtoc = find_magic(f, b'SACDMTOC', range(508, 520))
    if mtoc:
        twoch = struct.unpack_from('>I', mtoc, 0x40)[0]
        print(f"  2ch area LSN = {twoch} (0x{twoch:x})")

    print("\n=== Area TOC ===")
    area_lsn, area_sec = find_magic(f, b'TWOCHTOC', range(540, 560))
    if area_sec:
        print(f"  Area TOC LSN = {area_lsn}")
        print(f"  bytes[0x10-0x20]: {area_sec[0x10:0x20].hex()}")

    print("\n=== SACDTRL1 ===")
    trl1_lsn, trl1_sec = find_magic(f, b'SACDTRL1', range(540, 560))
    if trl1_sec:
        print(f"  SACDTRL1 LSN = {trl1_lsn}")
        # LSN 배열 파싱
        lsn_list = []
        off = 0x08
        while off + 4 <= len(trl1_sec):
            v = struct.unpack_from('>I', trl1_sec, off)[0]
            if v == 0 and lsn_list: break
            if v > 0: lsn_list.append(v)
            elif v == 0 and not lsn_list: pass
            off += 4
        print(f"  LSN list ({len(lsn_list)} entries): {lsn_list[:12]}")
        
        # 트랙 구간
        f.seek(0, 2)
        total_sec = f.tell() // SECTOR
        print(f"  Total sectors in file: {total_sec}")
        
        tracks = []
        for i in range(len(lsn_list)-1):
            s, e = lsn_list[i], lsn_list[i+1]
            tracks.append({'lsn': s, 'size': e - s})
        print(f"  Tracks: {len(tracks)}")
        for t in tracks[:5]:
            print(f"    LSN={t['lsn']} size={t['size']} sectors (~{t['size']*SECTOR/705600:.1f}sec)")

        # 첫 트랙 첫 섹터 헥스 덤프
        if tracks:
            first_lsn = tracks[0]['lsn']
            print(f"\n=== 첫 트랙 섹터 (LSN={first_lsn}) ===")
            sec0 = read_sector(f, first_lsn)
            print(f"  hex[0:64]: {sec0[:64].hex()}")
            
            # hdr=0 과 hdr=32 amplitude 비교
            from dsd_decoder import _get_fir, _bits_to_pcm
            fir = _get_fir(64)
            for hdr in [0, 8, 12, 16, 32]:
                dsd = bytearray()
                for i in range(8):
                    s = read_sector(f, first_lsn + i)
                    dsd.extend(s[hdr:])
                arr = np.frombuffer(bytes(dsd), np.uint8)
                usable = (len(arr)//2)*2
                arr = arr[:usable]
                bits = np.unpackbits(arr[0::2]).astype(np.float32)
                pcm = _bits_to_pcm(bits, 64, fir)
                amp = float(np.abs(pcm).max()) if len(pcm) else 0
                print(f"  hdr={hdr}: max_amp={amp:.4f}")

    print("\n=== SACDTTxt ===")
    txt_lsn, txt_sec = find_magic(f, b'SACDTTxt', range(540, 600))
    if txt_sec:
        print(f"  SACDTTxt LSN = {txt_lsn}")
        print(f"  bytes[0x08:0x30]: {txt_sec[0x08:0x30].hex()}")

print("\nDone.")
