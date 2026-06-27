"""
DSD Decoder Module
DSF / DFF 파일 파싱 및 PCM 변환
- 올바른 FIR 저역통과 필터 (fc=0.5, 256탭 Blackman window)
- 스트리밍 방식: 첫 청크만 변환 후 즉시 재생, 나머지는 백그라운드 처리
"""

import struct
import threading
import numpy as np
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# FIR 필터 계수 (모듈 로드 시 1회만 계산)
# ─────────────────────────────────────────────────────────────
def _build_fir(decimation: int, n_taps: int = 4096) -> np.ndarray:
    """
    Blackman window sinc 저역통과 필터
    정규화 주파수는 입력 샘플레이트(DSD) 기준:
    fc = 0.45 / decimation  → 데시메이션 후 나이퀴스트의 90% 차단
    예) decimation=64: fc = 0.45/64 ≈ 0.00703
    """
    # fc = 0.30 / decimation → 차단주파수 ≈ 13,230 Hz (DSD64 기준)
    # 노이즈셰이핑된 DSD(24-192rip 등)는 고주파 양자화 노이즈가 강하므로
    # 0.45 대신 0.30으로 더 강하게 차단
    fc = 0.30 / decimation
    n = np.arange(n_taps) - n_taps // 2
    h = np.sinc(2 * fc * n)           # sinc(2*fc*n)
    h *= np.blackman(n_taps)           # Blackman window (사이드로브 -74dB)
    h /= np.sum(h)                     # 직류 이득 = 1
    return h.astype(np.float32)

_FIR_CACHE: dict = {}

def _get_fir(decimation: int) -> np.ndarray:
    if decimation not in _FIR_CACHE:
        _FIR_CACHE[decimation] = _build_fir(decimation)
    return _FIR_CACHE[decimation]


class DSDDecoder:
    SUPPORTED_EXTENSIONS = {'.dsf', '.dff'}

    @staticmethod
    def is_dsd_file(filepath: str) -> bool:
        return Path(filepath).suffix.lower() in DSDDecoder.SUPPORTED_EXTENSIONS

    # ─────────────────────────────────────────────
    # 공개 API
    # ─────────────────────────────────────────────
    def decode_streaming(self, filepath: str, chunk_callback,
                         done_callback=None, error_callback=None,
                         stop_event: threading.Event = None,
                         seek_to_sample: int = 0,
                         stopped_event: threading.Event = None):
        """
        스트리밍 디코드: 첫 청크 즉시 반환 후 나머지를 백그라운드 스레드에서 처리
        chunk_callback(pcm_chunk: np.ndarray, sample_rate: int, info: dict)
          - 첫 호출에만 info 딕셔너리 포함 (메타데이터/포맷 정보)
        done_callback()  — 완료 시
        error_callback(msg: str) — 오류 시
        stop_event — set() 시 디코딩 즉시 중단
        stopped_event — 디코더 스레드가 실제로 종료되면 set()
        """
        if stop_event is None:
            stop_event = threading.Event()
        ext = Path(filepath).suffix.lower()
        t = threading.Thread(
            target=self._stream_worker,
            args=(filepath, ext, chunk_callback, done_callback, error_callback, stop_event, seek_to_sample, stopped_event),
            daemon=True,
        )
        t.start()
        return t

    def decode(self, filepath: str) -> dict:
        """전체 디코드 (하위 호환용 — 스트리밍 불필요 시 사용)"""
        ext = Path(filepath).suffix.lower()
        if ext == '.dsf':
            return self._decode_dsf(filepath)
        elif ext == '.dff':
            return self._decode_dff(filepath)
        raise ValueError(f"지원하지 않는 DSD 형식: {ext}")

    # ─────────────────────────────────────────────
    # 스트리밍 워커
    # ─────────────────────────────────────────────
    def _stream_worker(self, filepath, ext, chunk_cb, done_cb, error_cb, stop_event, seek_to_sample=0, stopped_event=None):
        # 마지막 10개 청크를 버퍼링해서 fade-out 적용
        chunk_buf = []   # [(pcm, sr, info), ...]
        original_chunk_cb = chunk_cb

        def intercepting_chunk_cb(pcm, sr, info):
            # info가 있는 첫 번째 청크는 즉시 전달 (first_chunk_event 해제용)
            # 그래야 audio_engine의 first_chunk_event.wait()이 풀림
            if info is not None and not chunk_buf:
                original_chunk_cb(pcm, sr, info)
                return
            chunk_buf.append((pcm, sr, info))
            # 버퍼에 11개 이상 쌓이면 앞것부터 확정 전달
            if len(chunk_buf) > 10:
                c = chunk_buf.pop(0)
                original_chunk_cb(c[0], c[1], c[2])

        try:
            if ext == '.dsf':
                self._stream_dsf(filepath, intercepting_chunk_cb, stop_event, seek_to_sample)
            else:
                self._stream_dff(filepath, intercepting_chunk_cb, stop_event)

            if not stop_event.is_set():
                # 버퍼에 남은 청크들 (마지막 10개)에 fade-out 적용: 1.0 → 0.0
                n = len(chunk_buf)
                last_sr = 44100
                last_ch = 2
                for i, (pcm, sr, info) in enumerate(chunk_buf):
                    pcm = pcm.copy()
                    start_vol = 1.0 - (i / n)
                    end_vol   = 1.0 - ((i + 1) / n)
                    ramp = np.linspace(start_vol, end_vol, len(pcm), dtype=np.float32).reshape(-1, 1)
                    pcm *= ramp
                    original_chunk_cb(pcm, sr, info)
                    last_sr = sr
                    last_ch = pcm.shape[1] if pcm.ndim > 1 else 1

                # 하드웨어 버퍼를 무음으로 완전히 덮기 위해 0.3초 무음 청크 추가
                silence_samples = int(last_sr * 0.3)
                silence = np.zeros((silence_samples, last_ch), dtype=np.float32)
                original_chunk_cb(silence, last_sr, None)

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
    def _stream_dsf(self, filepath: str, chunk_cb, stop_event: threading.Event = None, seek_to_sample: int = 0):
        with open(filepath, 'rb') as f:
            # DSD chunk: id(4) + chunk_size(8) + total_file_size(8) + metadata_offset(8) = 28 bytes
            if f.read(4) != b'DSD ':
                raise ValueError("DSF 파일 시그니처 오류")
            f.read(24)  # chunk_size(8) + total_size(8) + metadata_offset(8)

            # fmt chunk: id(4) + chunk_size(8) + 내용(52bytes) = 64 bytes 총
            fmt_id = f.read(4)
            if fmt_id != b'fmt ':
                raise ValueError(f"DSF fmt chunk 오류 (읽은 값: {fmt_id!r}, 오프셋: {f.tell()-4})")
            fmt_chunk_start = f.tell() - 4          # 'fmt ' id 시작 위치
            fmt_size = struct.unpack('<Q', f.read(8))[0]  # DSF: id+size+내용 포함 총 크기
            fmt_chunk_end = fmt_chunk_start + fmt_size     # 다음 chunk 시작 위치
            f.read(4)   # format_version
            f.read(4)   # format_id
            f.read(4)   # channel_type
            channel_count   = struct.unpack('<I', f.read(4))[0]
            sample_rate     = struct.unpack('<I', f.read(4))[0]
            bits_per_sample = struct.unpack('<I', f.read(4))[0]
            sample_count    = struct.unpack('<Q', f.read(8))[0]
            block_size      = struct.unpack('<I', f.read(4))[0]
            f.seek(fmt_chunk_end)  # fmt chunk 정확한 끝으로 이동

            # data chunk: id(4) + chunk_size(8)
            data_id = f.read(4)
            if data_id != b'data':
                raise ValueError(f"DSF data chunk 오류 (읽은 값: {data_id!r}, 오프셋: {f.tell()-4})")
            data_chunk_size = struct.unpack('<Q', f.read(8))[0] - 12  # 헤더 12바이트 제외

            decimation = 64
            pcm_rate   = sample_rate // decimation
            fir        = _get_fir(decimation)
            duration   = sample_count / sample_rate

            # 메타데이터 (첫 청크에만 포함)
            info = {
                'sample_rate':     pcm_rate,
                'dsd_sample_rate': sample_rate,
                'channels':        channel_count,
                'bits_per_sample': bits_per_sample,
                'duration':        duration,
                'format':          'DSF',
                'dsd_rate':        _dsd_rate_string(sample_rate),
            }

            bytes_per_block = block_size * channel_count
            # 한 번에 처리할 블록 수 (약 0.5초 분량)
            target_pcm_samples = pcm_rate // 2
            blocks_per_chunk   = max(1, target_pcm_samples * decimation // (block_size * 8))
            read_size          = bytes_per_block * blocks_per_chunk

            # seek: DSD 샘플 → 바이트 오프셋으로 변환 후 블록 경계로 정렬
            data_start = f.tell()
            if seek_to_sample > 0:
                # DSD샘플 → 바이트: sample_count는 채널당 샘플, 1샘플=1bit
                # bytes_per_dsd_sample = channel_count / 8
                bytes_per_dsd_sample = channel_count / 8.0
                # PCM 샘플 → DSD 샘플 (decimation 배)
                dsd_sample = seek_to_sample * decimation
                byte_offset = int(dsd_sample * bytes_per_dsd_sample)
                # 블록 경계로 정렬
                byte_offset = (byte_offset // bytes_per_block) * bytes_per_block
                byte_offset = min(byte_offset, max(0, int(sample_count * bytes_per_dsd_sample) - bytes_per_block))
                if byte_offset > 0:
                    f.seek(data_start + byte_offset)

            first = True
            buf   = b''
            while True:
                if stop_event and stop_event.is_set():
                    return
                raw = f.read(read_size)
                if not raw:
                    break
                buf += raw
                # 완전한 블록 단위만 처리
                usable = (len(buf) // bytes_per_block) * bytes_per_block
                if usable == 0:
                    continue
                chunk_data = buf[:usable]
                buf = buf[usable:]

                pcm = _dsf_blocks_to_pcm(
                    np.frombuffer(chunk_data, dtype=np.uint8),
                    channel_count, block_size, decimation, fir
                )
                if pcm is not None and len(pcm) > 0:
                    chunk_cb(pcm, pcm_rate, info if first else None)
                    first = False

            # 남은 버퍼 처리
            if buf:
                usable = (len(buf) // bytes_per_block) * bytes_per_block
                if usable > 0:
                    pcm = _dsf_blocks_to_pcm(
                        np.frombuffer(buf[:usable], dtype=np.uint8),
                        channel_count, block_size, decimation, fir
                    )
                    if pcm is not None and len(pcm) > 0:
                        chunk_cb(pcm, pcm_rate, None)

    # ─────────────────────────────────────────────
    # DFF 스트리밍
    # ─────────────────────────────────────────────
    def _stream_dff(self, filepath: str, chunk_cb, stop_event: threading.Event = None):
        # DFF는 전체 파싱이 필요하므로 메모리 맵 활용
        import mmap
        with open(filepath, 'rb') as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

        try:
            pos = 0

            def rh(p):
                cid   = mm[p:p+4].decode('ascii', errors='replace')
                csz   = struct.unpack('>Q', mm[p+4:p+12])[0]
                return cid, csz, p + 12

            cid, csz, pos = rh(0)
            if cid != 'FRM8':
                raise ValueError("DFF FRM8 오류")
            pos += 4  # FORM type ('DSD ')

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
                        if psz % 2: pp += 1

                elif cid == 'DSD ':
                    dsd_offset = np_
                    dsd_size   = csz2

                elif cid == 'ID3 ':
                    metadata = _parse_id3_bytes(bytes(mm[np_:np_+csz2]))

                pos = np_ + csz2
                if csz2 % 2: pos += 1

            if dsd_size == 0:
                raise ValueError("DFF: DSD data chunk 없음")

            decimation = 64
            pcm_rate   = sample_rate // decimation
            fir        = _get_fir(decimation)
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
                **metadata,
            }

            # DFF는 채널 인터리브 없이 연속 비트스트림
            # bytes_per_sample_frame = channel_count (1bit/ch → 1byte per 8 frames)
            target_pcm  = pcm_rate // 2          # 0.5초 청크
            chunk_bytes = target_pcm * decimation * channel_count // 8
            chunk_bytes = max(chunk_bytes, 4096)
            # channel_count 배수 정렬
            chunk_bytes = (chunk_bytes // channel_count) * channel_count

            offset  = dsd_offset
            end_off = dsd_offset + dsd_size
            first   = True

            while offset < end_off:
                if stop_event and stop_event.is_set():
                    return
                take = min(chunk_bytes, end_off - offset)
                raw  = bytes(mm[offset:offset + take])
                offset += take

                pcm = _dff_bytes_to_pcm(
                    np.frombuffer(raw, dtype=np.uint8),
                    channel_count, decimation, fir
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
        return self._decode_dsf(filepath)  # 동일 스트리밍 경로 사용


# ─────────────────────────────────────────────────────────────
# 모듈 레벨 변환 함수
# ─────────────────────────────────────────────────────────────

def _dsf_blocks_to_pcm(byte_array: np.ndarray, channels: int,
                        block_size: int, decimation: int,
                        fir: np.ndarray) -> np.ndarray:
    """DSF 블록 구조 → PCM"""
    bytes_per_block = block_size * channels
    n_blocks = len(byte_array) // bytes_per_block
    if n_blocks == 0:
        return None

    pcm_channels = []
    for ch in range(channels):
        bits_list = []
        for b in range(n_blocks):
            start = b * bytes_per_block + ch * block_size
            ch_bytes = byte_array[start:start + block_size]
            bits = np.unpackbits(ch_bytes, bitorder='little').astype(np.float32)
            bits_list.append(bits)
        ch_bits = np.concatenate(bits_list)
        pcm_ch  = _bits_to_pcm(ch_bits, decimation, fir)
        pcm_channels.append(pcm_ch)

    min_len = min(len(c) for c in pcm_channels)
    return np.column_stack([c[:min_len] for c in pcm_channels]).astype(np.float32)


def _dff_bytes_to_pcm(byte_array: np.ndarray, channels: int,
                       decimation: int, fir: np.ndarray) -> np.ndarray:
    """DFF 연속 비트스트림 → PCM (채널 인터리브: L바이트, R바이트 교대)"""
    total_bytes = len(byte_array)
    # channel_count 바이트 단위로 정렬
    usable = (total_bytes // channels) * channels
    if usable == 0:
        return None

    arr = byte_array[:usable]
    pcm_channels = []
    for ch in range(channels):
        ch_bytes = arr[ch::channels]          # 인터리브 분리
        bits     = np.unpackbits(ch_bytes, bitorder='little').astype(np.float32)
        pcm_ch   = _bits_to_pcm(bits, decimation, fir)
        pcm_channels.append(pcm_ch)

    min_len = min(len(c) for c in pcm_channels)
    return np.column_stack([c[:min_len] for c in pcm_channels]).astype(np.float32)


def _bits_to_pcm(bits: np.ndarray, decimation: int,
                 fir: np.ndarray) -> np.ndarray:
    """
    1비트 PDM → PCM
    1. 비트를 +1/-1 신호로 변환
    2. FFT 컨볼루션으로 FIR 저역통과 필터링 (np.convolve 대비 ~10배 빠름)
    3. decimation 배율로 다운샘플링
    """
    signal = (bits * 2.0 - 1.0).astype(np.float32)

    n_out = len(signal) // decimation
    if n_out == 0:
        return np.array([], dtype=np.float32)

    try:
        from scipy.signal import fftconvolve
        filtered = fftconvolve(signal, fir, mode='same')
    except ImportError:
        # scipy 없으면 numpy convolve fallback
        filtered = np.convolve(signal.astype(np.float64), fir.astype(np.float64), mode='same')

    # 데시메이션: decimation 간격으로 샘플 추출
    out = filtered[:n_out * decimation:decimation]
    return out.astype(np.float32)


# ─────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────

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
