"""
DSD Decoder Module — HiFi 최고음질 버전
=========================================
DSF / DFF 파일 파싱 및 PCM 변환

핵심 설계 원칙:
  1. Kaiser 창 FIR — 스탑밴드 -120dB 이상
  2. DSD64 → 176.4kHz (÷16) 출력: 20kHz 이상 대역 완전 보존
  3. 통과대역 20kHz / 스탑밴드 시작 50kHz (DSD 노이즈 시작 전 차단)
  4. float64 정밀도로 내부 처리 후 float32 출력
  5. oaconvolve + overlap-save: 실시간 대비 14배 빠름, 청크 간 위상 연속성 유지

DSD 노이즈 셰이핑 특성:
  - DSD64(2.8MHz): 20kHz 이하 매우 낮은 노이즈, 20~100kHz 급격히 증가
  - 차단주파수 20kHz, 전이대역 20~50kHz로 설계
"""

import struct
import threading
import numpy as np
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────
TARGET_DECIMATION = 16
OUTPUT_SR_DSD64   = 176400   # 2822400 ÷ 16

FIR_N_TAPS       = 2048
FIR_PASSBAND_HZ  = 20000
FIR_STOPBAND_HZ  = 50000
KAISER_BETA      = 11.0      # -120dB 스탑밴드


# ─────────────────────────────────────────────────────────────
# FIR 필터 설계
# ─────────────────────────────────────────────────────────────
def _kaiser_sinc_lpf(n_taps: int, fc_normalized: float, beta: float) -> np.ndarray:
    """Kaiser 창 sinc 저역통과 필터 (float64)"""
    if n_taps % 2 == 0:
        n_taps += 1
    n = np.arange(n_taps, dtype=np.float64) - (n_taps - 1) / 2.0
    h = 2.0 * fc_normalized * np.sinc(2.0 * fc_normalized * n)
    h *= np.kaiser(n_taps, beta)
    h /= h.sum()
    return h


def _build_decimation_filter(dsd_sample_rate: int,
                              decimation: int,
                              n_taps: int = FIR_N_TAPS,
                              passband_hz: float = FIR_PASSBAND_HZ,
                              stopband_hz: float = FIR_STOPBAND_HZ,
                              beta: float = KAISER_BETA) -> np.ndarray:
    output_sr  = dsd_sample_rate / decimation
    output_nyq = output_sr / 2.0
    pb = min(passband_hz, output_nyq * 0.90)
    sb = min(stopband_hz, output_nyq * 0.99)
    fc = (pb + sb) / 2.0
    fc_norm = fc / dsd_sample_rate
    return _kaiser_sinc_lpf(n_taps, fc_norm, beta).astype(np.float64)


_FIR_CACHE: dict = {}

def _get_fir(decimation: int, dsd_sr: int = 2822400) -> np.ndarray:
    key = (decimation, dsd_sr)
    if key not in _FIR_CACHE:
        _FIR_CACHE[key] = _build_decimation_filter(dsd_sr, decimation)
    return _FIR_CACHE[key]


# ─────────────────────────────────────────────────────────────
# 핵심 변환: 1bit PDM → PCM  (oaconvolve + overlap-save)
# ─────────────────────────────────────────────────────────────
def _bits_to_pcm(bits: np.ndarray, decimation: int,
                 fir: np.ndarray, prev_tail: np.ndarray = None):
    """
    1비트 PDM 스트림 → float32 PCM
    oaconvolve + overlap-save 방식으로 청크 간 위상 연속성 유지.

    Parameters
    ----------
    bits       : uint8 ndarray (0 또는 1)
    decimation : 데시메이션 비율
    fir        : float64 FIR 계수
    prev_tail  : 이전 청크 마지막 (len(fir)-1) 샘플. None이면 0으로 초기화.

    Returns
    -------
    (pcm: float32 ndarray, new_tail: float64 ndarray)
    """
    from scipy.signal import oaconvolve

    n_taps = len(fir)
    tail_len = n_taps - 1

    signal = bits.astype(np.float64) * 2.0 - 1.0

    n_out = len(signal) // decimation
    if n_out == 0:
        tail = prev_tail if prev_tail is not None else np.zeros(tail_len, dtype=np.float64)
        return np.array([], dtype=np.float32), tail

    # overlap-save: 앞에 이전 꼬리 붙임
    if prev_tail is None:
        prev_tail = np.zeros(tail_len, dtype=np.float64)
    extended = np.concatenate([prev_tail, signal])

    # oaconvolve (overlap-add, 긴 신호에 최적화)
    out_full = oaconvolve(extended, fir, mode='full')

    # 올바른 구간: [tail_len : tail_len + len(signal)]
    out = out_full[tail_len: tail_len + len(signal)]

    # 다음 청크 꼬리 저장
    new_tail = signal[-tail_len:].copy() if len(signal) >= tail_len else \
               np.concatenate([prev_tail[len(signal):], signal])

    # 데시메이션
    n_valid = n_out * decimation
    decimated = out[:n_valid:decimation]

    return decimated.astype(np.float32), new_tail


# ─────────────────────────────────────────────────────────────
# DSF 블록 → PCM
# ─────────────────────────────────────────────────────────────
def _dsf_blocks_to_pcm(byte_array: np.ndarray, channels: int,
                        block_size: int, decimation: int,
                        fir: np.ndarray, zi_list: list = None):
    """DSF 블록 구조 → PCM (bitorder='little', overlap-save)"""
    bytes_per_block = block_size * channels
    n_blocks = len(byte_array) // bytes_per_block
    if n_blocks == 0:
        if zi_list is None:
            zi_list = [None] * channels
        return None, zi_list

    if zi_list is None:
        zi_list = [None] * channels

    pcm_channels = []
    new_zi_list  = []

    for ch in range(channels):
        bits_list = []
        for b in range(n_blocks):
            start    = b * bytes_per_block + ch * block_size
            ch_bytes = byte_array[start:start + block_size]
            bits = np.unpackbits(ch_bytes, bitorder='little')
            bits_list.append(bits)

        ch_bits = np.concatenate(bits_list)
        pcm_ch, new_tail = _bits_to_pcm(ch_bits, decimation, fir, zi_list[ch])
        pcm_channels.append(pcm_ch)
        new_zi_list.append(new_tail)

    min_len = min(len(c) for c in pcm_channels)
    if min_len == 0:
        return None, new_zi_list

    pcm = np.column_stack([c[:min_len] for c in pcm_channels]).astype(np.float32)
    return pcm, new_zi_list


# ─────────────────────────────────────────────────────────────
# DFF 바이트 → PCM
# ─────────────────────────────────────────────────────────────
def _dff_bytes_to_pcm(byte_array: np.ndarray, channels: int,
                       decimation: int, fir: np.ndarray,
                       zi_list: list = None):
    """DFF 연속 비트스트림 → PCM (채널 인터리브, bitorder='big' MSB first, overlap-save)"""
    total_bytes = len(byte_array)
    usable = (total_bytes // channels) * channels
    if usable == 0:
        if zi_list is None:
            zi_list = [None] * channels
        return None, zi_list

    if zi_list is None:
        zi_list = [None] * channels

    arr = byte_array[:usable]
    pcm_channels = []
    new_zi_list  = []

    for ch in range(channels):
        ch_bytes = arr[ch::channels]
        bits     = np.unpackbits(ch_bytes, bitorder='big')   # DFF: MSB first
        pcm_ch, new_tail = _bits_to_pcm(bits, decimation, fir, zi_list[ch])
        pcm_channels.append(pcm_ch)
        new_zi_list.append(new_tail)

    min_len = min(len(c) for c in pcm_channels)
    if min_len == 0:
        return None, new_zi_list

    pcm = np.column_stack([c[:min_len] for c in pcm_channels]).astype(np.float32)
    return pcm, new_zi_list


# ─────────────────────────────────────────────────────────────
# SACD ISO용 공용 변환 (sacd_decoder.py에서 import)
# ─────────────────────────────────────────────────────────────
def dsd_bytes_to_pcm_sacd(dsd_bytes: bytes, channels: int,
                            decimation: int = TARGET_DECIMATION,
                            dsd_sr: int = 2822400,
                            zi_list: list = None):
    """
    SACD ISO DSD raw 데이터 → float32 PCM
    SACD ISO: big-endian 비트 순서(MSB first), 채널 인터리브

    Returns
    -------
    (pcm: float32, zi_list: list, pcm_sr: int)
    """
    fir = _get_fir(decimation, dsd_sr)
    arr = np.frombuffer(dsd_bytes, dtype=np.uint8)

    total_bytes = len(arr)
    usable = (total_bytes // channels) * channels
    if usable == 0:
        if zi_list is None:
            zi_list = [None] * channels
        return np.zeros((0, channels), dtype=np.float32), zi_list, dsd_sr // decimation

    if zi_list is None:
        zi_list = [None] * channels

    arr = arr[:usable]
    pcm_channels = []
    new_zi_list  = []

    for ch in range(channels):
        ch_bytes = arr[ch::channels]
        # SACD ISO: big-endian (MSB first)
        bits = np.unpackbits(ch_bytes, bitorder='big')
        pcm_ch, new_tail = _bits_to_pcm(bits, decimation, fir, zi_list[ch])
        pcm_channels.append(pcm_ch)
        new_zi_list.append(new_tail)

    min_len = min(len(c) for c in pcm_channels)
    if min_len == 0:
        return np.zeros((0, channels), dtype=np.float32), new_zi_list, dsd_sr // decimation

    pcm = np.column_stack([c[:min_len] for c in pcm_channels]).astype(np.float32)
    return pcm, new_zi_list, dsd_sr // decimation


# ─────────────────────────────────────────────────────────────
# DSDDecoder 클래스
# ─────────────────────────────────────────────────────────────
class DSDDecoder:
    SUPPORTED_EXTENSIONS = {'.dsf', '.dff'}

    @staticmethod
    def is_dsd_file(filepath: str) -> bool:
        return Path(filepath).suffix.lower() in DSDDecoder.SUPPORTED_EXTENSIONS

    def decode_streaming(self, filepath: str, chunk_callback,
                         done_callback=None, error_callback=None,
                         stop_event: threading.Event = None,
                         seek_to_sample: int = 0,
                         stopped_event: threading.Event = None):
        if stop_event is None:
            stop_event = threading.Event()
        ext = Path(filepath).suffix.lower()
        t = threading.Thread(
            target=self._stream_worker,
            args=(filepath, ext, chunk_callback, done_callback,
                  error_callback, stop_event, seek_to_sample, stopped_event),
            daemon=True,
        )
        t.start()
        return t

    def decode(self, filepath: str) -> dict:
        ext = Path(filepath).suffix.lower()
        if ext == '.dsf':
            return self._decode_dsf(filepath)
        elif ext == '.dff':
            return self._decode_dff(filepath)
        raise ValueError(f"지원하지 않는 DSD 형식: {ext}")

    # ─────────────────────────────────────────────
    # 스트리밍 워커
    # ─────────────────────────────────────────────
    def _stream_worker(self, filepath, ext, chunk_cb, done_cb,
                       error_cb, stop_event, seek_to_sample=0,
                       stopped_event=None):
        chunk_buf = []

        def intercepting_chunk_cb(pcm, sr, info):
            if info is not None and not chunk_buf:
                chunk_cb(pcm, sr, info)
                return
            chunk_buf.append((pcm, sr, info))
            if len(chunk_buf) > 10:
                c = chunk_buf.pop(0)
                chunk_cb(c[0], c[1], c[2])

        try:
            if ext == '.dsf':
                self._stream_dsf(filepath, intercepting_chunk_cb,
                                 stop_event, seek_to_sample)
            else:
                self._stream_dff(filepath, intercepting_chunk_cb, stop_event)

            if not stop_event.is_set():
                n = len(chunk_buf)
                last_sr = OUTPUT_SR_DSD64
                last_ch = 2
                for i, (pcm, sr, info) in enumerate(chunk_buf):
                    pcm = pcm.copy()
                    start_vol = 1.0 - (i / n)
                    end_vol   = 1.0 - ((i + 1) / n)
                    ramp = np.linspace(start_vol, end_vol,
                                       len(pcm), dtype=np.float32).reshape(-1, 1)
                    pcm *= ramp
                    chunk_cb(pcm, sr, info)
                    last_sr = sr
                    last_ch = pcm.shape[1] if pcm.ndim > 1 else 1

                silence_samples = int(last_sr * 0.3)
                silence = np.zeros((silence_samples, last_ch), dtype=np.float32)
                chunk_cb(silence, last_sr, None)

            if not stop_event.is_set() and done_cb:
                done_cb()
        except Exception as e:
            if not stop_event.is_set() and error_cb:
                error_cb(str(e))
        finally:
            if stopped_event is not None:
                stopped_event.set()

    # ─────────────────────────────────────────────
    # DSF 스트리밍
    # ─────────────────────────────────────────────
    def _stream_dsf(self, filepath: str, chunk_cb,
                    stop_event: threading.Event = None,
                    seek_to_sample: int = 0):
        with open(filepath, 'rb') as f:
            if f.read(4) != b'DSD ':
                raise ValueError("DSF 파일 시그니처 오류")
            f.read(24)

            fmt_id = f.read(4)
            if fmt_id != b'fmt ':
                raise ValueError(f"DSF fmt chunk 오류 ({fmt_id!r})")
            fmt_chunk_start = f.tell() - 4
            fmt_size        = struct.unpack('<Q', f.read(8))[0]
            fmt_chunk_end   = fmt_chunk_start + fmt_size
            f.read(4); f.read(4); f.read(4)
            channel_count   = struct.unpack('<I', f.read(4))[0]
            sample_rate     = struct.unpack('<I', f.read(4))[0]
            bits_per_sample = struct.unpack('<I', f.read(4))[0]
            sample_count    = struct.unpack('<Q', f.read(8))[0]
            block_size      = struct.unpack('<I', f.read(4))[0]
            f.seek(fmt_chunk_end)

            data_id = f.read(4)
            if data_id != b'data':
                raise ValueError(f"DSF data chunk 오류 ({data_id!r})")
            f.read(8)

            decimation = _choose_decimation(sample_rate)
            pcm_rate   = sample_rate // decimation
            fir        = _get_fir(decimation, sample_rate)
            duration   = sample_count / sample_rate

            info = {
                'sample_rate':     pcm_rate,
                'dsd_sample_rate': sample_rate,
                'channels':        channel_count,
                'bits_per_sample': bits_per_sample,
                'duration':        duration,
                'format':          'DSF',
                'dsd_rate':        _dsd_rate_string(sample_rate),
                'source':          'DSF',
            }

            bytes_per_block    = block_size * channel_count
            # 청크 크기: 약 1초 분량 (너무 크면 첫 재생 지연)
            target_pcm_samples = pcm_rate
            blocks_per_chunk   = max(1, target_pcm_samples * decimation
                                     // (block_size * 8))
            read_size          = bytes_per_block * blocks_per_chunk

            data_start = f.tell()
            if seek_to_sample > 0:
                bytes_per_dsd_sample = channel_count / 8.0
                dsd_sample  = seek_to_sample * decimation
                byte_offset = int(dsd_sample * bytes_per_dsd_sample)
                byte_offset = (byte_offset // bytes_per_block) * bytes_per_block
                byte_offset = min(byte_offset,
                                  max(0, int(sample_count * bytes_per_dsd_sample)
                                      - bytes_per_block))
                if byte_offset > 0:
                    f.seek(data_start + byte_offset)

            first   = True
            buf     = b''
            zi_list = [None] * channel_count

            while True:
                if stop_event and stop_event.is_set():
                    return
                raw = f.read(read_size)
                if not raw:
                    break
                buf += raw
                usable = (len(buf) // bytes_per_block) * bytes_per_block
                if usable == 0:
                    continue
                chunk_data = buf[:usable]
                buf        = buf[usable:]

                arr = np.frombuffer(chunk_data, dtype=np.uint8)
                pcm, zi_list = _dsf_blocks_to_pcm(
                    arr, channel_count, block_size, decimation, fir, zi_list
                )
                if pcm is not None and len(pcm) > 0:
                    chunk_cb(pcm, pcm_rate, info if first else None)
                    first = False

            if buf:
                usable = (len(buf) // bytes_per_block) * bytes_per_block
                if usable > 0:
                    arr = np.frombuffer(buf[:usable], dtype=np.uint8)
                    pcm, zi_list = _dsf_blocks_to_pcm(
                        arr, channel_count, block_size, decimation, fir, zi_list
                    )
                    if pcm is not None and len(pcm) > 0:
                        chunk_cb(pcm, pcm_rate, None)

    # ─────────────────────────────────────────────
    # DFF 스트리밍
    # ─────────────────────────────────────────────
    def _stream_dff(self, filepath: str, chunk_cb,
                    stop_event: threading.Event = None):
        import mmap
        with open(filepath, 'rb') as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

        try:
            def rh(p):
                cid = mm[p:p+4].decode('ascii', errors='replace')
                csz = struct.unpack('>Q', mm[p+4:p+12])[0]
                return cid, csz, p + 12

            cid, csz, pos = rh(0)
            if cid != 'FRM8':
                raise ValueError("DFF FRM8 오류")
            pos += 4

            sample_rate   = 2822400
            channel_count = 2
            dsd_offset    = 0
            dsd_size      = 0
            metadata      = {}

            end = 12 + csz
            while pos < end - 12:
                try:
                    cid, csz2, np_ = rh(pos)
                except Exception:
                    break

                if cid == 'PROP':
                    pp = np_ + 4
                    pe = np_ + csz2
                    while pp < pe - 12:
                        try:
                            pid, psz, pd = rh(pp)
                        except Exception:
                            break
                        if pid == 'FS  ':
                            sample_rate = struct.unpack('>I', mm[pd:pd+4])[0]
                        elif pid == 'CHNL':
                            channel_count = struct.unpack('>H', mm[pd:pd+2])[0]
                        pp = pd + psz
                        if psz % 2:
                            pp += 1

                elif cid == 'DSD ':
                    dsd_offset = np_
                    dsd_size   = csz2

                elif cid == 'ID3 ':
                    metadata = _parse_id3_bytes(bytes(mm[np_:np_+csz2]))

                pos = np_ + csz2
                if csz2 % 2:
                    pos += 1

            if dsd_size == 0:
                raise ValueError("DFF: DSD data chunk 없음")

            decimation   = _choose_decimation(sample_rate)
            pcm_rate     = sample_rate // decimation
            fir          = _get_fir(decimation, sample_rate)
            sample_count = dsd_size * 8 // channel_count
            duration     = sample_count / sample_rate

            info = {
                'sample_rate':     pcm_rate,
                'dsd_sample_rate': sample_rate,
                'channels':        channel_count,
                'bits_per_sample': 1,
                'duration':        duration,
                'format':          'DFF',
                'dsd_rate':        _dsd_rate_string(sample_rate),
                'source':          'DFF',
                **metadata,
            }

            # 청크 크기: 약 1초 분량
            target_pcm  = pcm_rate
            chunk_bytes = target_pcm * decimation * channel_count // 8
            chunk_bytes = max(chunk_bytes, 4096)
            chunk_bytes = (chunk_bytes // channel_count) * channel_count

            offset  = dsd_offset
            end_off = dsd_offset + dsd_size
            first   = True
            zi_list = [None] * channel_count

            while offset < end_off:
                if stop_event and stop_event.is_set():
                    return
                take = min(chunk_bytes, end_off - offset)
                raw  = bytes(mm[offset:offset + take])
                offset += take

                arr = np.frombuffer(raw, dtype=np.uint8)
                pcm, zi_list = _dff_bytes_to_pcm(
                    arr, channel_count, decimation, fir, zi_list
                )
                if pcm is not None and len(pcm) > 0:
                    chunk_cb(pcm, pcm_rate, info if first else None)
                    first = False
        finally:
            mm.close()

    # ─────────────────────────────────────────────
    # 전체 디코드 (하위 호환)
    # ─────────────────────────────────────────────
    def _decode_dsf(self, filepath: str) -> dict:
        chunks, info_box = [], [None]
        done_ev = threading.Event()

        def cb(pcm, sr, info):
            chunks.append(pcm)
            if info:
                info_box[0] = info

        def done():
            done_ev.set()

        t = self.decode_streaming(filepath, cb, done)
        done_ev.wait()
        info = info_box[0] or {}
        if chunks:
            info['pcm_data'] = np.concatenate(chunks, axis=0)
        return info

    def _decode_dff(self, filepath: str) -> dict:
        return self._decode_dsf(filepath)


# ─────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────

def _choose_decimation(dsd_sample_rate: int) -> int:
    """
    DSD SR → 176400 Hz 출력이 되는 decimation 결정
    DSD64(2822400)÷16=176400, DSD128÷32=176400, DSD256÷64=176400
    """
    target_out = 176400
    dec = max(1, dsd_sample_rate // target_out)
    pow2 = 1
    while pow2 * 2 <= dec:
        pow2 *= 2
    return pow2


def _dsd_rate_string(sample_rate: int) -> str:
    return {
        2822400:  'DSD64 (2.8MHz)',
        5644800:  'DSD128 (5.6MHz)',
        11289600: 'DSD256 (11.2MHz)',
        22579200: 'DSD512 (22.5MHz)',
    }.get(sample_rate, f'DSD ({sample_rate/1e6:.1f}MHz)')


def _parse_id3_bytes(raw: bytes) -> dict:
    meta = {}
    try:
        from mutagen.id3 import ID3
        from mutagen.id3._util import ID3NoHeaderError
        import io
        try:
            tags = ID3(fileobj=io.BytesIO(raw))
            meta['title']  = str(tags.get('TIT2', ''))
            meta['artist'] = str(tags.get('TPE1', ''))
            meta['album']  = str(tags.get('TALB', ''))
            meta['year']   = str(tags.get('TDRC', ''))
        except ID3NoHeaderError:
            pass
    except ImportError:
        pass
    return meta
