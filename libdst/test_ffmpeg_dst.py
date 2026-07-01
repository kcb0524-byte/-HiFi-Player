"""
ffmpeg libavcodec의 DST 디코더를 ctypes로 직접 호출
macOS /usr/local/lib/libavcodec.dylib 사용
"""
import ctypes
import sys
import os

# ── ffmpeg 라이브러리 로드 ──────────────────────────────────────
try:
    libavcodec = ctypes.CDLL("/usr/local/lib/libavcodec.dylib")
    libavutil  = ctypes.CDLL("/usr/local/lib/libavutil.dylib")
    print("라이브러리 로드 성공")
except OSError as e:
    print(f"라이브러리 로드 실패: {e}")
    sys.exit(1)

# ── API 바인딩 ────────────────────────────────────────────────
libavcodec.avcodec_find_decoder_by_name.restype  = ctypes.c_void_p
libavcodec.avcodec_find_decoder_by_name.argtypes = [ctypes.c_char_p]
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

# ── ISO에서 DST 프레임 추출 (크로스섹터 지원) ─────────────────
SECTOR_SIZE = 2048
ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"

def extract_frames(iso_path, start_lsn=647, end_lsn=900):
    """크로스섹터 지원 DST 프레임 추출"""
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
            if not sec or len(sec) < 1:
                continue
            hdr = sec[0]
            if (hdr >> 7) & 1:
                continue  # 타임코드
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

            # carry 마무리
            if carry_need > 0:
                take = min(len(payload) - sptr, carry_need)
                carry_buf += payload[sptr:sptr+take]
                carry_need -= take
                sptr += take
                if carry_need == 0:
                    _push(carry_fs, carry_dt, bytes(carry_buf), frames, frame_buf if True else None)
                    # 직접 처리
                    if carry_dt in (1,2):
                        if carry_fs:
                            if in_frame and frame_buf:
                                frames.append(bytes(frame_buf))
                            frame_buf.clear()
                            in_frame = True
                        if in_frame:
                            frame_buf += carry_buf
                    carry_buf = bytearray()

            for fs, dt, pl in pkts:
                avail = len(payload) - sptr
                if avail >= pl:
                    pkt = payload[sptr:sptr+pl]; sptr += pl
                    if dt in (1,2):
                        if fs:
                            if in_frame and frame_buf:
                                frames.append(bytes(frame_buf))
                            frame_buf = bytearray(pkt)
                            in_frame = True
                        elif in_frame:
                            frame_buf += pkt
                else:
                    carry_fs, carry_dt = fs, dt
                    carry_buf = bytearray(payload[sptr:])
                    carry_need = pl - avail
                    sptr = len(payload)
                    break

    if in_frame and frame_buf:
        frames.append(bytes(frame_buf))
    return frames

# ── 코덱 초기화 ───────────────────────────────────────────────
print("=== ffmpeg DST 디코더 초기화 ===")
codec = libavcodec.avcodec_find_decoder_by_name(b"dst")
print(f"코덱: 0x{codec:X}" if codec else "ERROR: DST 코덱 없음")
if not codec: sys.exit(1)

ctx = libavcodec.avcodec_alloc_context3(codec)
ret = libavcodec.avcodec_open2(ctx, codec, None)
print(f"avcodec_open2: {ret} ({'OK' if ret==0 else 'FAIL'})")
if ret != 0: sys.exit(1)

# ── 패킷/프레임 할당 ─────────────────────────────────────────
pkt   = libavcodec.av_packet_alloc()
frame = libavutil.av_frame_alloc()
print(f"pkt=0x{pkt:X}  frame=0x{frame:X}")

# ── DST 프레임 추출 ─────────────────────────────────────────
print("\n=== DST 프레임 추출 중... ===")
frames = extract_frames(ISO)
print(f"추출된 프레임: {len(frames)}")
print(f"크기들: {[len(f) for f in frames[:8]]}")

# ── DST 디코딩 ───────────────────────────────────────────────
print("\n=== DST 디코딩 (첫 3프레임) ===")

# AVPacket 구조체에서 data/size 필드 설정
# ffmpeg 8.x: AVPacket.data @ offset 32, .size @ offset 40
import struct as st

def run_avg(data, n=512):
    b = data[:n]
    runs, cur, l = [], None, 0
    for byte in b:
        for i in range(7,-1,-1):
            bit = (byte>>i)&1
            if cur is None: cur=bit; l=1
            elif bit==cur: l+=1
            else: runs.append(l); cur=bit; l=1
    if l: runs.append(l)
    return sum(runs)/len(runs) if runs else 0

for fi, frame_data in enumerate(frames[:5]):
    if len(frame_data) < 100:
        print(f"프레임{fi}: {len(frame_data)}B 너무 작음, 건너뜀")
        continue

    # AVPacket.data와 .size 설정
    buf = ctypes.create_string_buffer(frame_data)
    # pkt 구조체에 직접 쓰기
    pkt_ptr = ctypes.cast(pkt, ctypes.POINTER(ctypes.c_uint8))
    # data 포인터 (offset 32)
    data_ptr = ctypes.cast(buf, ctypes.c_void_p).value
    ctypes.memmove(pkt + 32, st.pack('<Q', data_ptr), 8)
    # size (offset 40)
    ctypes.memmove(pkt + 40, st.pack('<i', len(frame_data)), 4)

    ret = libavcodec.avcodec_send_packet(ctx, pkt)
    print(f"프레임{fi}: {len(frame_data)}B  send_packet={ret}", end="")

    if ret == 0:
        ret2 = libavcodec.avcodec_receive_frame(ctx, frame)
        print(f"  receive_frame={ret2}", end="")
        if ret2 == 0:
            # AVFrame.nb_samples @ offset 112
            nb = st.unpack('<i', ctypes.string_at(frame + 112, 4))[0]
            fmt= st.unpack('<i', ctypes.string_at(frame + 116, 4))[0]
            print(f"  nb_samples={nb}  fmt={fmt}")
            # data[0] @ offset 0
            dptr = st.unpack('<Q', ctypes.string_at(frame, 8))[0]
            if dptr and nb > 0:
                raw = ctypes.string_at(dptr, min(nb, 4704))
                ra = run_avg(raw)
                print(f"  → run_avg={ra:.2f}  첫8B: {' '.join(f'{b:02X}' for b in raw[:8])}")
        else:
            print()
    else:
        print()
    libavcodec.av_packet_unref(pkt)

print("\n완료")
