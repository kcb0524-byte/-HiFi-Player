"""
arm64 ffmpeg (/opt/homebrew) libavcodec으로 DST 디코딩
"""
import ctypes
import sys
import struct

# ── arm64 ffmpeg 라이브러리 로드 ───────────────────────────────
try:
    libavcodec = ctypes.CDLL("/opt/homebrew/lib/libavcodec.dylib")
    libavutil  = ctypes.CDLL("/opt/homebrew/lib/libavutil.dylib")
    print("arm64 libavcodec 로드 성공")
except OSError as e:
    print(f"로드 실패: {e}")
    sys.exit(1)

# DST 디코더 확인
libavcodec.avcodec_find_decoder_by_name.restype  = ctypes.c_void_p
libavcodec.avcodec_find_decoder_by_name.argtypes = [ctypes.c_char_p]
codec = libavcodec.avcodec_find_decoder_by_name(b"dst")
print(f"DST 코덱: {'있음 (0x{:X})'.format(codec) if codec else '없음'}")
if not codec:
    sys.exit(1)

# ── API 바인딩 ────────────────────────────────────────────────
libavcodec.avcodec_alloc_context3.restype  = ctypes.c_void_p
libavcodec.avcodec_alloc_context3.argtypes = [ctypes.c_void_p]
libavcodec.avcodec_open2.restype  = ctypes.c_int
libavcodec.avcodec_open2.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
libavcodec.av_packet_alloc.restype  = ctypes.c_void_p
libavutil.av_frame_alloc.restype  = ctypes.c_void_p
libavcodec.avcodec_send_packet.restype  = ctypes.c_int
libavcodec.avcodec_send_packet.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
libavcodec.avcodec_receive_frame.restype  = ctypes.c_int
libavcodec.avcodec_receive_frame.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
libavcodec.av_packet_unref.argtypes = [ctypes.c_void_p]

# ── AVCodecContext 열기 ──────────────────────────────────────
ctx = libavcodec.avcodec_alloc_context3(codec)
ret = libavcodec.avcodec_open2(ctx, codec, None)
print(f"avcodec_open2: {ret} ({'OK' if ret==0 else 'FAIL'})")
if ret != 0:
    sys.exit(1)

pkt   = libavcodec.av_packet_alloc()
frame = libavutil.av_frame_alloc()
print(f"pkt=0x{pkt:X}  frame=0x{frame:X}")

# ── ISO에서 DST 프레임 추출 (크로스섹터) ─────────────────────
SECTOR_SIZE = 2048
ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"

def extract_frames(iso_path, start_lsn=647, end_lsn=900):
    frames = []
    frame_buf = bytearray()
    in_frame = False
    carry_buf = bytearray()
    carry_need = 0
    carry_fs = carry_dt = 0

    with open(iso_path, 'rb') as f:
        for lsn in range(start_lsn, end_lsn):
            f.seek(lsn * SECTOR_SIZE)
            sec = f.read(SECTOR_SIZE)
            if not sec: continue
            hdr = sec[0]
            if (hdr >> 7) & 1: continue
            fi = (hdr >> 3) & 7
            pi = hdr & 7
            ptr = 1
            pkts = []
            for _ in range(pi):
                if ptr + 2 > len(sec): break
                b0, b1 = sec[ptr], sec[ptr+1]; ptr += 2
                pkts.append(((b0>>7)&1, (b0>>3)&7, (b0&7)<<8|b1))
            ptr += fi * 4
            payload = sec[ptr:]
            sptr = 0

            if carry_need > 0:
                take = min(len(payload) - sptr, carry_need)
                carry_buf += payload[sptr:sptr+take]
                carry_need -= take
                sptr += take
                if carry_need == 0:
                    if carry_dt in (1,2):
                        if carry_fs:
                            if in_frame and frame_buf: frames.append(bytes(frame_buf))
                            frame_buf = bytearray(carry_buf)
                            in_frame = True
                        elif in_frame:
                            frame_buf += carry_buf
                    carry_buf = bytearray()

            for fs, dt, pl in pkts:
                avail = len(payload) - sptr
                if avail >= pl:
                    pkt_data = payload[sptr:sptr+pl]; sptr += pl
                    if dt in (1,2):
                        if fs:
                            if in_frame and frame_buf: frames.append(bytes(frame_buf))
                            frame_buf = bytearray(pkt_data)
                            in_frame = True
                        elif in_frame:
                            frame_buf += pkt_data
                else:
                    carry_fs, carry_dt = fs, dt
                    carry_buf = bytearray(payload[sptr:])
                    carry_need = pl - avail
                    break

    if in_frame and frame_buf:
        frames.append(bytes(frame_buf))
    return frames

print("\n=== DST 프레임 추출 ===")
frames = extract_frames(ISO)
print(f"프레임 수: {len(frames)}")
print(f"크기: {[len(f) for f in frames[:8]]}")

# ── ffmpeg DST 디코딩 ────────────────────────────────────────
def run_avg(data, n=512):
    runs, cur, l = [], None, 0
    for byte in bytes(data[:n]):
        for i in range(7,-1,-1):
            bit = (byte>>i)&1
            if cur is None: cur=bit; l=1
            elif bit==cur: l+=1
            else: runs.append(l); cur=bit; l=1
    if l: runs.append(l)
    return sum(runs)/len(runs) if runs else 0

print("\n=== ffmpeg DST 디코딩 ===")

# AVPacket 구조체 직접 조작
# ffmpeg 8.x AVPacket 레이아웃:
#   +0:  buf (pointer, 8B)
#   +8:  pts (int64, 8B)
#   +16: dts (int64, 8B)
#   +24: data (pointer, 8B)
#   +32: size (int, 4B)
#   ...
# → data @ +24, size @ +32

AV_PKT_DATA = 24
AV_PKT_SIZE = 32

for fi, fd in enumerate(frames[:8]):
    if len(fd) < 50: continue

    # data 포인터와 size 설정
    buf_c = (ctypes.c_uint8 * len(fd))(*fd)
    buf_ptr = ctypes.cast(buf_c, ctypes.c_void_p).value
    ctypes.memmove(pkt + AV_PKT_DATA, struct.pack('<Q', buf_ptr), 8)
    ctypes.memmove(pkt + AV_PKT_SIZE, struct.pack('<i', len(fd)), 4)

    r1 = libavcodec.avcodec_send_packet(ctx, pkt)
    print(f"F{fi}({len(fd)}B) send={r1}", end="")

    if r1 == 0:
        r2 = libavcodec.avcodec_receive_frame(ctx, frame)
        print(f" recv={r2}", end="")
        if r2 == 0:
            # AVFrame: data[0] @ +0, nb_samples @ +80 (ffmpeg8 구조체)
            # 실제 오프셋은 버전마다 다르므로 여러 위치 시도
            for nb_off in [80, 88, 96, 104, 112]:
                try:
                    nb = struct.unpack('<i', ctypes.string_at(frame + nb_off, 4))[0]
                    if 100 < nb < 100000:
                        print(f" nb_samples={nb}@off{nb_off}", end="")
                        break
                except: pass
            # data[0]
            dptr = struct.unpack('<Q', ctypes.string_at(frame, 8))[0]
            if dptr:
                raw = ctypes.string_at(dptr, min(4704, 512))
                print(f" run={run_avg(raw):.2f}", end="")
                print(f" 첫8B: {' '.join(f'{b:02X}' for b in raw[:8])}", end="")
    print()
    libavcodec.av_packet_unref(pkt)

print("\n완료")
