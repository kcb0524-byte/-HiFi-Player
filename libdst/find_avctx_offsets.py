"""
AVCodecContext 구조체에서 sample_rate, channels, block_align 오프셋 찾기
"""
import ctypes
import struct

libavcodec = ctypes.CDLL("/opt/homebrew/lib/libavcodec.dylib")
libavutil  = ctypes.CDLL("/opt/homebrew/lib/libavutil.dylib")

libavcodec.avcodec_find_decoder_by_name.restype  = ctypes.c_void_p
libavcodec.avcodec_find_decoder_by_name.argtypes = [ctypes.c_char_p]
libavcodec.avcodec_alloc_context3.restype  = ctypes.c_void_p
libavcodec.avcodec_alloc_context3.argtypes = [ctypes.c_void_p]
libavcodec.avcodec_open2.restype  = ctypes.c_int
libavcodec.avcodec_open2.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

codec = libavcodec.avcodec_find_decoder_by_name(b"dst")
ctx   = libavcodec.avcodec_alloc_context3(codec)

# DST DSD64: sample_rate=2822400, channels=2, block_align=4704
# 64바이트씩 덤프해서 어디에 2822400이 들어가는지 확인
TARGET_SR = 2822400
TARGET_CH = 2
TARGET_BA = 4704  # DSD64 프레임 크기

# 먼저 sample_rate=2822400을 ctx에 써보면서 open2가 성공하는 오프셋 탐색
# ffmpeg 소스 기준 AVCodecContext:
#   codec_type(4) + codec_id(4) + codec_tag(4) + pad(4) 
#   + bit_rate(8) + bit_rate_tolerance(4) + global_quality(4) 
#   + compression_level(4) + flags(4) + flags2(4) + pad(4?)
#   + extradata*(8) + extradata_size(4) + ...
#   + time_base(8) + tick(4) ...
#   + width(4) + height(4) ...
#   + sample_rate(4) + channels(4) ...
# 
# 보통 sample_rate는 offset 72~100 근처
# 먼저 ctx 메모리를 읽어서 0이 아닌 값들 확인

print("AVCodecContext 초기값 덤프 (첫 256바이트):")
raw = ctypes.string_at(ctx, 256)
for i in range(0, 256, 16):
    vals = raw[i:i+16]
    ints = [struct.unpack('<i', vals[j:j+4])[0] for j in range(0,16,4)]
    print(f"  +{i:3d}: {' '.join(f'{v:12d}' for v in ints)}")

print()
print("(참고: codec_type=1이 AVMEDIA_TYPE_AUDIO)")
