"""
SACD ISO 진단 스크립트 — 실제 ISO 구조를 덤프하고 문제 파악
사용법: python3 diagnose_sacd.py /path/to/file.iso
"""
import sys, struct

SECTOR = 2048

def read_sector(f, lsn):
    f.seek(lsn * SECTOR)
    return f.read(SECTOR)

def hexdump(data, length=64, offset=0):
    for i in range(0, min(length, len(data)), 16):
        chunk = data[i:i+16]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        asc_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"  {offset+i:04x}: {hex_part:<48}  {asc_part}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 diagnose_sacd.py /path/to/file.iso")
        sys.exit(1)
    
    path = sys.argv[1]
    print(f"\n=== SACD ISO 진단: {path} ===\n")
    
    with open(path, 'rb') as f:
        f.seek(0, 2)
        file_size = f.tell()
        total_sectors = file_size // SECTOR
        print(f"파일 크기: {file_size:,} bytes ({total_sectors:,} sectors)\n")
        
        # Master TOC 탐색
        print("--- Master TOC 탐색 ---")
        master_lsn = None
        for lsn in [510, 511, 512, 520, 530]:
            sec = read_sector(f, lsn)
            magic = sec[:8]
            print(f"  섹터 {lsn}: magic={magic} ({magic.hex()})")
            if magic == b'SACDMTOC':
                master_lsn = lsn
                print(f"  → Master TOC 발견!")
                break
        
        if master_lsn is None:
            print("  Master TOC 없음 — SACD ISO가 아닐 수 있음")
            # 첫 몇 섹터 덤프
            for lsn in [0, 1, 510, 511]:
                sec = read_sector(f, lsn)
                print(f"\n섹터 {lsn} 덤프:")
                hexdump(sec, 64)
            return
        
        # Master TOC 덤프
        sec = read_sector(f, master_lsn)
        print(f"\n--- Master TOC (섹터 {master_lsn}) ---")
        hexdump(sec, 128)
        
        twoch_lsn  = struct.unpack_from('>I', sec, 0x40)[0]
        twoch_size = struct.unpack_from('>I', sec, 0x44)[0]
        mulch_lsn  = struct.unpack_from('>I', sec, 0x50)[0]
        mulch_size = struct.unpack_from('>I', sec, 0x54)[0]
        print(f"\n  2ch area LSN={twoch_lsn} (0x{twoch_lsn:x}), size={twoch_size}")
        print(f"  mulch area LSN={mulch_lsn} (0x{mulch_lsn:x}), size={mulch_size}")
        
        # Area TOC
        for area_name, area_lsn in [('2CH', twoch_lsn), ('MULCH', mulch_lsn)]:
            if area_lsn == 0:
                continue
            print(f"\n--- {area_name} Area TOC (섹터 {area_lsn}) ---")
            sec = read_sector(f, area_lsn)
            hexdump(sec, 128)
            
            magic = sec[:8]
            print(f"  magic: {magic}")
            
            # 인접 섹터 매직 확인
            print(f"\n  인접 섹터 매직:")
            for d in range(0, 8):
                s = read_sector(f, area_lsn + d)
                m = s[:8]
                print(f"    섹터 {area_lsn+d}: {m} ({m.hex()})")
            
            # SACDTRL1 찾기
            trl1_sec = None
            for d in range(0, 8):
                s = read_sector(f, area_lsn + d)
                if s[:8] == b'SACDTRL1':
                    trl1_sec = s
                    print(f"\n  SACDTRL1 발견 (섹터 {area_lsn+d})")
                    hexdump(s, 128)
                    break
            
            if trl1_sec:
                print(f"\n  SACDTRL1 트랙 LSN 목록:")
                lsn_list = []
                off = 0x08
                while off + 4 <= len(trl1_sec):
                    v = struct.unpack_from('>I', trl1_sec, off)[0]
                    if v == 0 and lsn_list:
                        break
                    if v > 0:
                        lsn_list.append(v)
                    elif v == 0 and not lsn_list:
                        off += 4
                        continue
                    off += 4
                
                for i, lsn_v in enumerate(lsn_list):
                    print(f"    [{i}] LSN={lsn_v} (0x{lsn_v:x})")
                
                print(f"\n  트랙 구간 (인접 차이):")
                for i in range(len(lsn_list)-1):
                    sz = lsn_list[i+1] - lsn_list[i]
                    dur = sz * SECTOR / (352800 * 2)  # 2ch DSD64
                    print(f"    트랙 {i+1}: LSN={lsn_list[i]}, size={sz} sectors, ~{dur:.1f}s")
            
            # 첫 번째 트랙 섹터 헤더 확인
            if trl1_sec:
                lsn_list2 = []
                off = 0x08
                while off + 4 <= len(trl1_sec):
                    v = struct.unpack_from('>I', trl1_sec, off)[0]
                    if v == 0 and lsn_list2: break
                    if v > 0: lsn_list2.append(v)
                    elif v == 0 and not lsn_list2:
                        off += 4; continue
                    off += 4
                
                if lsn_list2:
                    first_track_lsn = lsn_list2[0]
                    print(f"\n  첫 번째 트랙 섹터 ({first_track_lsn}) 헤더 덤프:")
                    s = read_sector(f, first_track_lsn)
                    hexdump(s, 64)
                    
                    print(f"\  두 번째 섹터 ({first_track_lsn+1}) 헤더 덤프:")
                    s2 = read_sector(f, first_track_lsn+1)
                    hexdump(s2, 64)

if __name__ == '__main__':
    main()
