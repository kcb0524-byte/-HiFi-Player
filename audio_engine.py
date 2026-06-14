"""
Audio Engine — miniaudio 기반 HiFi 엔진 v2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[음질 개선 목록]
1. Windows  : WASAPI Exclusive 모드 (OS 믹서 완전 우회, shareMode=exclusive)
              wasapi.noAutoConvertSRC + noDefaultQualitySRC → SRC 비활성화
              wasapi.usage = pro_audio (낮은 레이턴시 스케줄링)
2. macOS    : CoreAudio 독점 모드 — ctypes로 AudioDeviceSetProperty 직접 호출
              kAudioDevicePropertyHogMode (프로세스가 DAC 독점)
              kAudioDevicePropertyBufferFrameSize 최소화
3. 공통     : 트랙 로드 시 DAC 샘플레이트 자동 전환 (SRC 없이 네이티브 SR 출력)
              비트퍼펙트 모드에서 EQ/볼륨/RG 완전 bypass
4. DoP      : DSD over PCM — DSD 비트스트림을 PCM 24-bit 프레임에 패킹
              DoP 마커 0x05/0xFA로 DAC가 DoP를 인식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys
import platform
import threading
import time
import queue
import array
import ctypes
import struct
from typing import Optional, Callable, Generator
import numpy as np

try:
    import miniaudio
    MA_AVAILABLE = True
except ImportError:
    MA_AVAILABLE = False

try:
    import soundfile as sf
    SF_AVAILABLE = True
except ImportError:
    SF_AVAILABLE = False

from dsd_decoder import DSDDecoder
from sacd_decoder import SACDDecoder

# ─────────────────────────────────────────────
# CoreAudio 독점 모드 (macOS 전용)
# ─────────────────────────────────────────────
_IS_MAC = (platform.system() == 'Darwin')
_IS_WIN = (platform.system() == 'Windows')

if _IS_MAC:
    try:
        _ca = ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')
        _cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

        # CoreAudio 공식 상수값 (AudioHardware.h / CoreAudioTypes.h)
        _kAudioObjectPropertyScopeGlobal      = 0x676c6f62  # 'glob'
        _kAudioObjectPropertyScopeOutput      = 0x6f757470  # 'outp'
        _kAudioObjectPropertyElementMain      = 0

        # 정확한 4CC 상수 (Apple AudioHardware.h 기준)
        _kAudio_dOut = 0x644f7574   # 'dOut' — kAudioHardwarePropertyDefaultOutputDevice
        _kAudio_hog  = 0x6f696e6b   # 'oink' — kAudioDevicePropertyHogMode (실제값!)
        _kAudio_buf  = 0x6273697a   # 'bsiz' — kAudioDevicePropertyBufferFrameSize
        _kAudio_srat = 0x6e6f6d73   # 'noms' — kAudioDevicePropertyNominalSampleRate

        class _AudioObjectPropertyAddress(ctypes.Structure):
            _fields_ = [
                ('mSelector', ctypes.c_uint32),
                ('mScope',    ctypes.c_uint32),
                ('mElement',  ctypes.c_uint32),
            ]

        _ca.AudioObjectGetPropertyData.restype  = ctypes.c_int32
        _ca.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32,                           # inObjectID
            ctypes.POINTER(_AudioObjectPropertyAddress),
            ctypes.c_uint32,                           # inQualifierDataSize
            ctypes.c_void_p,                           # inQualifierData
            ctypes.POINTER(ctypes.c_uint32),           # ioDataSize
            ctypes.c_void_p,                           # outData
        ]
        _ca.AudioObjectSetPropertyData.restype  = ctypes.c_int32
        _ca.AudioObjectSetPropertyData.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(_AudioObjectPropertyAddress),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        _CA_AVAILABLE = True
    except Exception as _e:
        print(f'[CoreAudio] ctypes 로드 실패: {_e}')
        _CA_AVAILABLE = False
else:
    _CA_AVAILABLE = False


def _ca_get_default_output_device() -> int:
    """기본 출력 장치 AudioObjectID 반환 (macOS)"""
    if not _CA_AVAILABLE:
        return 0
    prop = _AudioObjectPropertyAddress(
        mSelector=_kAudio_dOut,
        mScope=_kAudioObjectPropertyScopeGlobal,
        mElement=_kAudioObjectPropertyElementMain,
    )
    device_id = ctypes.c_uint32(0)
    size = ctypes.c_uint32(ctypes.sizeof(device_id))
    _kAudioObjectSystemObject = 1
    ret = _ca.AudioObjectGetPropertyData(
        _kAudioObjectSystemObject,
        ctypes.byref(prop),
        0, None,
        ctypes.byref(size),
        ctypes.byref(device_id),
    )
    if ret == 0:
        return device_id.value
    return 0


def _ca_get_device_id_by_name(name: str) -> int:
    """장치 이름으로 CoreAudio AudioObjectID 검색 (macOS)"""
    if not _CA_AVAILABLE:
        return 0
    try:
        # kAudioHardwarePropertyDevices = 'dev '
        _kAudio_devs = struct.unpack('>I', b'dev ')[0]
        _kAudio_name = struct.unpack('>I', b'lnam')[0]  # kAudioObjectPropertyName
        _kAudioObjectSystemObject = 1

        prop = _AudioObjectPropertyAddress(
            mSelector=_kAudio_devs,
            mScope=_kAudioObjectPropertyScopeGlobal,
            mElement=_kAudioObjectPropertyElementMain,
        )
        size = ctypes.c_uint32(0)
        # 먼저 크기 조회
        _ca.AudioObjectGetPropertyDataSize(
            _kAudioObjectSystemObject, ctypes.byref(prop),
            0, None, ctypes.byref(size))
        n = size.value // ctypes.sizeof(ctypes.c_uint32)
        ids = (ctypes.c_uint32 * n)()
        _ca.AudioObjectGetPropertyData(
            _kAudioObjectSystemObject, ctypes.byref(prop),
            0, None, ctypes.byref(size), ids)

        # CoreFoundation으로 장치 이름 읽기
        _cf.CFStringGetCString.restype = ctypes.c_bool
        _cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]

        for dev_id in ids:
            name_prop = _AudioObjectPropertyAddress(
                mSelector=_kAudio_name,
                mScope=_kAudioObjectPropertyScopeGlobal,
                mElement=_kAudioObjectPropertyElementMain,
            )
            cf_str = ctypes.c_void_p(0)
            name_size = ctypes.c_uint32(ctypes.sizeof(cf_str))
            ret = _ca.AudioObjectGetPropertyData(
                dev_id, ctypes.byref(name_prop),
                0, None, ctypes.byref(name_size), ctypes.byref(cf_str))
            if ret == 0 and cf_str.value:
                buf = ctypes.create_string_buffer(256)
                _cf.CFStringGetCString(cf_str.value, buf, 256, 0x08000100)  # kCFStringEncodingUTF8
                dev_name = buf.value.decode('utf-8', errors='replace')
                _cf.CFRelease(cf_str.value)
                if name.lower() in dev_name.lower() or dev_name.lower() in name.lower():
                    return dev_id
    except Exception as e:
        print(f'[CoreAudio] 장치 이름 검색 실패: {e}')
    return 0


def _ca_hog_device(device_id: int) -> int:
    """CoreAudio 독점 모드 획득. 반환값: 이전 hog PID (-1=없음, 성공시 현재 PID)"""
    if not _CA_AVAILABLE or device_id == 0:
        return -1
    prop = _AudioObjectPropertyAddress(
        mSelector=_kAudio_hog,
        mScope=_kAudioObjectPropertyScopeOutput,
        mElement=_kAudioObjectPropertyElementMain,
    )
    pid = ctypes.c_int32(os.getpid())
    size = ctypes.c_uint32(ctypes.sizeof(pid))
    ret = _ca.AudioObjectSetPropertyData(
        device_id,
        ctypes.byref(prop),
        0, None,
        size,
        ctypes.byref(pid),
    )
    if ret == 0:
        print(f'[CoreAudio] 독점 모드 획득 (pid={os.getpid()}, device={device_id})')
        return os.getpid()
    print(f'[CoreAudio] 독점 모드 획득 실패 (ret={ret:#010x}) — 공유 모드로 계속')
    return -1


def _ca_release_hog(device_id: int):
    """CoreAudio 독점 모드 해제"""
    if not _CA_AVAILABLE or device_id == 0:
        return
    prop = _AudioObjectPropertyAddress(
        mSelector=_kAudio_hog,
        mScope=_kAudioObjectPropertyScopeOutput,
        mElement=_kAudioObjectPropertyElementMain,
    )
    pid = ctypes.c_int32(-1)  # -1 = 해제
    size = ctypes.c_uint32(ctypes.sizeof(pid))
    _ca.AudioObjectSetPropertyData(
        device_id,
        ctypes.byref(prop),
        0, None,
        size,
        ctypes.byref(pid),
    )
    print(f'[CoreAudio] 독점 모드 해제 (device={device_id})')


def _ca_set_sample_rate(device_id: int, sample_rate: float) -> bool:
    """CoreAudio 장치 샘플레이트 설정 — NominalSampleRate는 scope=Global"""
    if not _CA_AVAILABLE or device_id == 0:
        return False
    prop = _AudioObjectPropertyAddress(
        mSelector=_kAudio_srat,
        mScope=_kAudioObjectPropertyScopeGlobal,   # Output → Global 로 수정
        mElement=_kAudioObjectPropertyElementMain,
    )
    sr = ctypes.c_double(sample_rate)
    size = ctypes.c_uint32(ctypes.sizeof(sr))
    ret = _ca.AudioObjectSetPropertyData(
        device_id,
        ctypes.byref(prop),
        0, None,
        size,
        ctypes.byref(sr),
    )
    if ret == 0:
        print(f'[CoreAudio] 샘플레이트 → {sample_rate:.0f} Hz')
        return True
    # 일부 DAC/macOS 버전은 직접 SR 설정을 허용하지 않음
    # miniaudio가 PlaybackDevice 열 때 sample_rate를 지정하므로 실질적 문제 없음
    print(f'[CoreAudio] 샘플레이트 직접 설정 불가 — miniaudio가 {sample_rate:.0f} Hz로 장치 오픈 시 적용')
    return False


def _ca_set_buffer_size(device_id: int, frames: int) -> bool:
    """CoreAudio 버퍼 크기 최소화 (레이턴시 감소)"""
    if not _CA_AVAILABLE or device_id == 0:
        return False
    prop = _AudioObjectPropertyAddress(
        mSelector=_kAudio_buf,
        mScope=_kAudioObjectPropertyScopeOutput,
        mElement=_kAudioObjectPropertyElementMain,
    )
    buf = ctypes.c_uint32(frames)
    size = ctypes.c_uint32(ctypes.sizeof(buf))
    ret = _ca.AudioObjectSetPropertyData(
        device_id,
        ctypes.byref(prop),
        0, None,
        size,
        ctypes.byref(buf),
    )
    if ret == 0:
        print(f'[CoreAudio] 버퍼 크기 → {frames} frames')
        return True
    return False


# ─────────────────────────────────────────────
# DoP (DSD over PCM) 유틸리티
# ─────────────────────────────────────────────
_DOP_MARKER_A = 0x05  # 홀수 프레임 마커
_DOP_MARKER_B = 0xFA  # 짝수 프레임 마커

def _pack_dop(dsd_bits: np.ndarray, marker_toggle: list) -> np.ndarray:
    """
    DSD 비트스트림 → DoP PCM 32-bit float 변환
    DoP 규격: 각 32-bit 샘플 = [marker(8bit) | DSD_data(16bit) | 0(8bit)]
    marker가 0x05/0xFA 교대로 나타나면 DAC가 DoP로 인식
    입력: dsd_bits shape (N, ch) uint8 (각 값 0 또는 1)
    출력: float32 shape (N//16, ch)
    """
    # 16 DSD 비트 → 1 DoP PCM 샘플
    n_samples = len(dsd_bits) // 16
    if n_samples == 0:
        return np.zeros((0, dsd_bits.shape[1] if dsd_bits.ndim > 1 else 1), dtype=np.float32)

    ch = dsd_bits.shape[1] if dsd_bits.ndim > 1 else 1
    out = np.zeros((n_samples, ch), dtype=np.int32)

    for i in range(n_samples):
        marker = _DOP_MARKER_A if (marker_toggle[0] % 2 == 0) else _DOP_MARKER_B
        marker_toggle[0] += 1
        for c in range(ch):
            bits = dsd_bits[i*16:(i+1)*16, c] if dsd_bits.ndim > 1 else dsd_bits[i*16:(i+1)*16]
            # 16비트 DSD 데이터를 big-endian으로 패킹
            dsd_word = 0
            for b in bits:
                dsd_word = (dsd_word << 1) | int(b)
            # DoP 32-bit: [marker<<16 | dsd_word]
            val = (marker << 16) | (dsd_word & 0xFFFF)
            # 부호 있는 24-bit 범위로 정규화
            if val & 0x800000:
                val -= 0x1000000
            out[i, c] = val

    # int32 → float32 (-1.0 ~ 1.0)
    return (out.astype(np.float32) / 8388608.0)


class AudioDevice:
    def __init__(self, index, name, max_output_channels, default_samplerate, hostapi_name=''):
        self.index = index
        self.name = name
        self.max_output_channels = max_output_channels
        self.default_samplerate = default_samplerate
        self.hostapi_name = hostapi_name
        self.device_id = None  # miniaudio device_id

    def display_name(self):
        return f"{self.name}  [{self.hostapi_name}]" if self.hostapi_name else self.name


class AudioEngine:
    SUPPORTED_FORMATS = {
        '.flac', '.wav', '.aiff', '.aif', '.mp3', '.m4a', '.aac',
        '.ogg', '.opus', '.wv', '.ape', '.tta', '.wma',
        '.dsf', '.dff', '.iso',
    }

    def __init__(self):
        self._current_file: Optional[str] = None
        self._pcm_data: Optional[np.ndarray] = None   # float64로 저장
        self._sample_rate: int = 44100
        self._channels: int = 2
        self._position: int = 0          # PCM 재생 위치 (샘플)
        self._dsd_position: int = 0      # DSD 재생 위치 (샘플)
        self._total_samples: int = 0
        self._volume: float = 1.0
        self._rg_gain: float = 1.0   # ReplayGain 보정값 (선형 배율)
        self._rg_enabled: bool = True
        self._device_index: Optional[int] = None

        # ── HiFi 출력 품질 옵션 ──
        self._bit_perfect: bool = False      # True: EQ/RG/볼륨 완전 bypass, 원본 그대로 DAC로
        self._dither_enabled: bool = True    # TPDF 디더링 (float64→float32 변환 시)
        self._fixed_output_sr: int = 0       # 0=파일 SR 그대로, >0=강제 업샘플링 SR
        self._upsample_quality: int = 32     # resample_poly window 품질 (높을수록 정밀)

        # ── v2.0 HiFi 독점 모드 옵션 ──
        self._exclusive_mode: bool = True    # Windows=WASAPI Exclusive, macOS=CoreAudio Hog
        self._auto_sr: bool = True           # 트랙 SR에 맞춰 DAC SR 자동 전환
        self._dop_mode: bool = False         # DSD over PCM (DoP 지원 DAC 전용)
        self._dop_marker_toggle: list = [0]  # DoP 마커 홀짝 토글
        self._ca_device_id: int = 0          # macOS CoreAudio 장치 ID
        self._ca_hogged: bool = False        # CoreAudio 독점 중 여부
        self._selected_device_name: str = '' # 선택된 장치 이름 (CoreAudio ID 매핑용)

        # 재생 상태 — generator가 읽는 플래그
        self._state: str = 'idle'        # 'idle' | 'playing' | 'paused'
        self._lock = threading.Lock()

        # DSD
        self._pcm_queue: queue.Queue = queue.Queue(maxsize=10)
        self._decode_done: bool = False
        self._is_dsd: bool = False
        self._decode_stop: threading.Event = threading.Event()
        self._decode_stopped: threading.Event = threading.Event()  # 디코더가 실제로 멈췄음을 알림
        self._decode_stopped.set()  # 초기값: 멈춰 있음
        self._dsd_buf: list = []

        # miniaudio 장치
        self._device: Optional[miniaudio.PlaybackDevice] = None
        self._device_samplerate: int = 0
        self._device_channels: int = 0

        # 전환 중 플래그 — generator가 이 구간에서 무조건 무음 출력
        self._gen_stop = threading.Event()  # 현재 generator 중단 신호
        self._mute_until: float = 0.0       # 이 시각까지 강제 무음 (time.monotonic 기준)
        self._transitioning: bool = False   # True면 generator 무조건 무음
        self._fade_out_frames: int = 0      # 남은 fade-out 프레임 수


        # 콜백
        self.on_position_changed: Optional[Callable] = None
        self.on_playback_finished: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_vu_level: Optional[Callable] = None
        self.on_chunk_ready: Optional[Callable] = None  # (chunk: np.ndarray, sample_rate: int)

        self._dsd_decoder  = DSDDecoder()
        self._sacd_decoder = SACDDecoder()

        # ── 파라메트릭 EQ ──
        # 5밴드: Low Shelf / Peak×3 / High Shelf
        # 각 밴드: (type, freq_hz, gain_db, q)
        self._eq_enabled: bool = False
        self._eq_params: list = [
            ('lowshelf',    60,  0.0, 0.7),
            ('peak',       125,  0.0, 1.0),
            ('peak',       250,  0.0, 1.0),
            ('peak',       500,  0.0, 1.0),
            ('peak',      1000,  0.0, 1.0),
            ('peak',      2000,  0.0, 1.0),
            ('peak',      4000,  0.0, 1.0),
            ('highshelf', 12000, 0.0, 0.7),
        ]
        # generator 스레드가 읽는 계수 (atomic 교체)
        self._eq_sos: Optional[np.ndarray] = None   # shape (n_bands, 6)
        self._eq_lock = threading.Lock()

    # ─────────────────────────────────────────────
    # 장치 관리
    # ─────────────────────────────────────────────
    @staticmethod
    def get_output_devices() -> list:
        devices = []
        if not MA_AVAILABLE:
            return devices
        try:
            all_devs = miniaudio.Devices()
            playback = all_devs.get_playbacks()
            for d in playback:
                dev = AudioDevice(
                    index=d['id'],
                    name=d['name'],
                    max_output_channels=d.get('maxChannels', 2),
                    default_samplerate=d.get('minSampleRate', 44100),
                    hostapi_name='',
                )
                dev.device_id = d['id']
                devices.append(dev)
        except Exception as e:
            print(f'[Device] 장치 목록 조회 실패: {e}')
        return devices

    @staticmethod
    def get_default_output_device() -> Optional[AudioDevice]:
        dev = AudioDevice(
            index=None, name='기본 출력 장치',
            max_output_channels=2,
            default_samplerate=44100,
        )
        return dev

    def set_output_device(self, device_index, device_name: str = ''):
        """출력 장치 변경 — 장치를 바꿔야 하므로 재시작 불가피"""
        was_state = self._state
        self._state = 'idle'
        self._gen_stop.set()
        self._close_device()
        time.sleep(0.05)
        self._device_index = device_index
        self._selected_device_name = device_name  # CoreAudio ID 매핑에 사용
        self._open_device()
        if was_state == 'playing':
            self._restart_generator()
            self._state = 'playing'

    # ─────────────────────────────────────────────
    # 파일 로드
    # ─────────────────────────────────────────────
    def load(self, filepath: str) -> dict:
        # UPnP/DLNA HTTP 스트림: 임시 파일로 다운로드 후 로드
        if filepath.startswith('http://') or filepath.startswith('https://'):
            return self._load_upnp_stream(filepath)

        basename = os.path.basename(filepath)
        if basename.startswith('._'):
            raise RuntimeError(f"macOS 리소스 파일: {basename}")

        # 1. 상태 idle + 전환 플래그
        with self._lock:
            self._transitioning = True
            self._state = 'idle'

        # 2. DSD 디코더 완전히 멈추기
        self._decode_stop.set()
        self._decode_stopped.wait(timeout=2.0)
        self._decode_stop = threading.Event()
        self._decode_stopped = threading.Event()

        # 3. 큐 비우기 (장치는 닫지 않음 — 영구 generator 유지로 팝 노이즈 방지)
        with self._lock:
            self._flush_queue()

        ext = filepath.rsplit('.', 1)[-1].lower()
        prev_sr = self._sample_rate
        prev_ch = self._channels

        if ext in ('dsf', 'dff'):
            info = self._load_dsd(filepath)
        elif ext == 'iso':
            # SACD ISO: track_info가 있으면 해당 트랙, 없으면 첫 번째 트랙
            track_info = getattr(self, '_sacd_track_info', None)
            if track_info is None:
                tracks = self._sacd_decoder.get_track_list(filepath)
                if not tracks:
                    raise RuntimeError("SACD ISO에서 트랙을 찾을 수 없습니다.")
                track_info = tracks[0]
            info = self._load_sacd(filepath, track_info)
            self._sacd_track_info = None  # 사용 후 초기화
        else:
            info = self._load_pcm(filepath)

        # 샘플레이트/채널이 바뀐 경우에만 장치 재시작 (불가피)
        if self._sample_rate != prev_sr or self._channels != prev_ch or self._device is None:
            self._close_device()
            self._open_device()

        self._current_file = filepath
        self._position = 0
        self._dsd_position = 0

        with self._lock:
            self._transitioning = False
            self._fade_out_frames = 0

        return info

    def _flush_queue(self):
        try:
            while True:
                self._pcm_queue.get_nowait()
        except queue.Empty:
            pass
        self._dsd_buf = []

    def _load_pcm_via_ffmpeg(self, filepath: str):
        """ffmpeg subprocess로 PCM 디코딩 (APE, WMA, TTA 등 soundfile 미지원 포맷용)"""
        import subprocess, shutil
        # PyInstaller 번들 내 ffmpeg (macOS: ffmpeg, Windows: ffmpeg.exe)
        _exe_dir = os.path.dirname(sys.executable)
        _bundle_ffmpeg_win = os.path.join(_exe_dir, 'ffmpeg.exe')
        _bundle_ffmpeg_mac = os.path.join(_exe_dir, 'ffmpeg')

        # Windows 추가 탐색 경로
        _win_paths = []
        if _IS_WIN:
            _win_paths = [
                r'C:\ProgramData\chocolatey\bin\ffmpeg.exe',
                r'C:\ffmpeg\bin\ffmpeg.exe',
                r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
                r'C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe',
            ]

        ffmpeg_bin = None
        for candidate in [
            _bundle_ffmpeg_win,
            _bundle_ffmpeg_mac,
            shutil.which('ffmpeg'),
            '/opt/homebrew/bin/ffmpeg',
            '/usr/local/bin/ffmpeg',
            '/usr/bin/ffmpeg',
            *_win_paths,
        ]:
            if candidate and os.path.isfile(candidate):
                ffmpeg_bin = candidate
                break
        if ffmpeg_bin is None:
            if _IS_WIN:
                raise RuntimeError("ffmpeg를 찾을 수 없습니다. 설치 파일에 ffmpeg가 포함되지 않았을 수 있습니다.")
            else:
                raise RuntimeError("ffmpeg를 찾을 수 없습니다. brew install ffmpeg 또는 PATH 확인 필요")

        # ffprobe 탐색 (ffmpeg과 같은 디렉토리 우선)
        _ffmpeg_dir = os.path.dirname(ffmpeg_bin)
        _ffprobe_name = 'ffprobe.exe' if _IS_WIN else 'ffprobe'
        _ffprobe_same_dir = os.path.join(_ffmpeg_dir, _ffprobe_name)

        ffprobe_bin = None
        for candidate in [
            _ffprobe_same_dir,
            shutil.which('ffprobe'),
            '/opt/homebrew/bin/ffprobe',
            '/usr/local/bin/ffprobe',
        ]:
            if candidate and os.path.isfile(candidate):
                ffprobe_bin = candidate
                break
        probe_cmd = [
            ffprobe_bin, '-v', 'quiet', '-print_format', 'json',
            '-show_streams', filepath
        ]
        try:
            probe_out = subprocess.check_output(probe_cmd, stderr=subprocess.DEVNULL)
            import json as _json
            probe_info = _json.loads(probe_out)
            audio_stream = next(
                (s for s in probe_info.get('streams', []) if s.get('codec_type') == 'audio'),
                None
            )
            srate = int(audio_stream['sample_rate']) if audio_stream else 44100
            channels = int(audio_stream.get('channels', 2))
        except Exception:
            srate = 44100
            channels = 2

        # ffmpeg로 원본 샘플레이트 그대로 f64le PCM 추출
        cmd = [
            ffmpeg_bin,
            '-v', 'quiet',
            '-i', filepath,
            '-f', 'f64le',
            '-acodec', 'pcm_f64le',
            '-ar', str(srate),
            '-ac', str(channels),
            'pipe:1'
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0 or not proc.stdout:
            err = proc.stderr.decode(errors='replace')[:300]
            raise RuntimeError(f"ffmpeg 디코딩 실패: {err}")

        raw = np.frombuffer(proc.stdout, dtype=np.float64)
        if len(raw) == 0:
            raise RuntimeError("ffmpeg가 빈 오디오 데이터를 반환했습니다")
        data = raw.reshape(-1, channels)
        return data, srate

    def _load_pcm(self, filepath: str) -> dict:
        if not SF_AVAILABLE:
            raise RuntimeError("soundfile 없음")
        self._is_dsd = False

        ext = filepath.rsplit('.', 1)[-1].lower()
        # soundfile(libsndfile)이 지원하지 않는 포맷 → ffmpeg 폴백
        FFMPEG_FORMATS = {'ape', 'wma', 'tta', 'tak', 'ofr', 'ra', 'rm'}

        if ext in FFMPEG_FORMATS:
            try:
                data, srate = self._load_pcm_via_ffmpeg(filepath)
            except RuntimeError as e:
                raise RuntimeError(f"APE/WMA 재생 실패: {e}")
        else:
            try:
                # float64로 로드 — EQ 연산 정밀도 확보
                data, srate = sf.read(filepath, dtype='float64', always_2d=True)
            except Exception as e:
                # soundfile 실패 시 ffmpeg로 재시도
                print(f"[Audio] soundfile 실패 ({e}), ffmpeg 폴백 시도...")
                data, srate = self._load_pcm_via_ffmpeg(filepath)
        # 피크 레벨 확인 및 정규화
        peak = np.abs(data).max()
        if peak > 1.0:
            data = data / peak
        # 업샘플링 (비트퍼펙트 모드에서도 SR 고정이 설정된 경우에만 적용)
        target_sr = self._fixed_output_sr
        if target_sr > 0 and target_sr != srate:
            data = self._resample(data, srate, target_sr)
            srate = target_sr
        self._pcm_data = data   # float64
        self._sample_rate = srate
        self._channels = data.shape[1]
        self._total_samples = data.shape[0]

        info = self._extract_metadata(filepath)
        info.update({
            'sample_rate': srate,
            'channels': self._channels,
            'duration': self._total_samples / srate,
            'format': filepath.rsplit('.', 1)[-1].upper(),
        })
        try:
            sf_info = sf.info(filepath)
            info['bit_depth'] = sf_info.subtype_info
            info['format_detail'] = sf_info.format_info
        except Exception:
            pass

        # ReplayGain 게인 결정
        rg_db = info.get('replaygain_db')
        if rg_db is not None:
            # 태그 있음: dB → 선형 변환 (프리앰프 +0 dB)
            self._rg_gain = float(10.0 ** (rg_db / 20.0))
            info['rg_source'] = f'Tag ({rg_db:+.1f} dB)'
        else:
            # 태그 없음: RMS 측정으로 자동 계산
            self._rg_gain = self._calc_rg_gain(data)
            gain_db = 20.0 * np.log10(max(self._rg_gain, 1e-9))
            info['rg_source'] = f'Auto ({gain_db:+.1f} dB)'

        print(f"[RG] {filepath.split('/')[-1]} → {info['rg_source']} (×{self._rg_gain:.3f})")
        return info

    def _load_dsd(self, filepath: str) -> dict:
        self._decode_done = False
        self._is_dsd = True
        self._pcm_data = None
        self._dsd_position = 0

        first_chunk_event = threading.Event()
        info_box = [None]
        error_box = [None]
        stop_ev = self._decode_stop

        def chunk_cb(pcm, sr, info):
            if info:
                self._sample_rate = sr
                self._channels = pcm.shape[1] if pcm.ndim > 1 else 1
                self._total_samples = int(info.get('duration', 0) * sr)
                info_box[0] = info
                first_chunk_event.set()
            while not stop_ev.is_set():
                try:
                    self._pcm_queue.put(pcm, timeout=0.1)
                    break
                except queue.Full:
                    continue

        def done_cb():
            self._decode_done = True

        def error_cb(msg):
            error_box[0] = msg
            first_chunk_event.set()

        self._dsd_decoder.decode_streaming(
            filepath, chunk_cb, done_cb, error_cb,
            stop_event=self._decode_stop,
            stopped_event=self._decode_stopped)

        first_chunk_event.wait(timeout=10)
        if error_box[0]:
            raise RuntimeError(error_box[0])
        if info_box[0] is None:
            raise RuntimeError("DSD 로드 실패")

        info = info_box[0]

        # DSD: 스트리밍이라 RMS 측정 불가 → ReplayGain 태그만 읽기
        meta = self._extract_metadata(filepath)
        info.update({k: v for k, v in meta.items() if k not in info})
        rg_db = meta.get('replaygain_db')
        if rg_db is not None:
            self._rg_gain = float(10.0 ** (rg_db / 20.0))
            info['rg_source'] = f'Tag ({rg_db:+.1f} dB)'
        else:
            self._rg_gain = 1.0  # DSD 태그 없으면 보정 없음
            info['rg_source'] = 'No Tag'

        print(f"[RG] {filepath.split('/')[-1]} → DSD {info['rg_source']} (×{self._rg_gain:.3f})")
        return info

    def _load_upnp_stream(self, url: str) -> dict:
        """UPnP/DLNA HTTP 스트림을 임시 파일로 받아 로드"""
        import urllib.request
        import tempfile
        ext = url.split('?')[0].rsplit('.', 1)[-1].lower()
        if not ext or ext not in ('flac', 'wav', 'mp3', 'aiff', 'aif', 'aac', 'm4a', 'ogg'):
            ext = 'flac'  # 기본 확장자

        with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            headers = {'User-Agent': 'HiFiPlayer/1.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            with open(tmp_path, 'wb') as f:
                f.write(data)
        except Exception as e:
            raise RuntimeError(f"UPnP 스트림 로드 실패: {e}")

        # 재귀 호출로 일반 파일처럼 로드
        info = self.load(tmp_path)
        info['upnp_url'] = url
        return info

    def _load_sacd(self, filepath: str, track_info: dict) -> dict:
        """SACD ISO 트랙을 스트리밍 디코드 (DSD→PCM)"""
        self._decode_done = False
        self._is_dsd = True
        self._pcm_data = None
        self._dsd_position = 0

        first_chunk_event = threading.Event()
        info_box  = [None]
        error_box = [None]
        stop_ev   = self._decode_stop

        def chunk_cb(pcm, sr, info):
            if info:
                self._sample_rate   = sr
                self._channels      = pcm.shape[1] if pcm.ndim > 1 else 1
                self._total_samples = int(track_info.get('duration', 0) * sr)
                info_box[0]         = info
                first_chunk_event.set()
            while not stop_ev.is_set():
                try:
                    self._pcm_queue.put(pcm, timeout=0.1)
                    break
                except queue.Full:
                    continue

        def done_cb():
            self._decode_done = True

        def error_cb(msg):
            error_box[0] = msg
            first_chunk_event.set()

        self._sacd_decoder.decode_streaming(
            track_info, chunk_cb, done_cb, error_cb,
            stop_event=self._decode_stop,
            stopped_event=self._decode_stopped)

        first_chunk_event.wait(timeout=10)
        if error_box[0]:
            raise RuntimeError(error_box[0])
        if info_box[0] is None:
            raise RuntimeError("SACD ISO 로드 실패")

        info = info_box[0]
        info.update({
            'title':    track_info.get('title', ''),
            'album':    track_info.get('album', ''),
            'duration': track_info.get('duration', 0),
        })
        self._rg_gain = 1.0
        info['rg_source'] = 'No Tag (SACD)'
        return info

    def _extract_metadata(self, filepath: str) -> dict:
        meta = {}
        try:
            from mutagen import File as MutagenFile
            tags = MutagenFile(filepath, easy=True)
            if tags:
                meta['title']       = str(tags.get('title',       [''])[0])
                meta['artist']      = str(tags.get('artist',      [''])[0])
                meta['album']       = str(tags.get('album',       [''])[0])
                meta['year']        = str(tags.get('date',        [''])[0])
                meta['genre']       = str(tags.get('genre',       [''])[0])
                meta['tracknumber'] = str(tags.get('tracknumber', [''])[0])

                # ReplayGain 태그 읽기 (track gain 우선, 없으면 album gain)
                rg_db = None
                for key in ('replaygain_track_gain', 'replaygain_album_gain'):
                    val = tags.get(key, [''])[0]
                    if val:
                        try:
                            rg_db = float(str(val).replace('dB', '').replace('dB', '').strip())
                            break
                        except ValueError:
                            pass
                # easy=True로 못 읽는 경우 raw 태그에서 재시도
                if rg_db is None:
                    try:
                        raw = MutagenFile(filepath, easy=False)
                        if raw and raw.tags:
                            for key in raw.tags.keys():
                                kl = key.lower()
                                if 'replaygain_track_gain' in kl or 'replaygain_album_gain' in kl:
                                    v = str(raw.tags[key])
                                    try:
                                        rg_db = float(v.replace('dB','').strip())
                                        break
                                    except ValueError:
                                        pass
                    except Exception:
                        pass
                meta['replaygain_db'] = rg_db  # None이면 태그 없음

                # 커버아트 추출
                meta['cover_data'] = AudioEngine._extract_cover(filepath)

        except Exception:
            pass
        return meta

    @staticmethod
    def _extract_cover(filepath: str) -> bytes:
        """파일 태그에서 커버아트 bytes 추출. 없으면 None."""
        try:
            ext = filepath.rsplit('.', 1)[-1].lower()

            if ext in ('flac',):
                from mutagen.flac import FLAC
                audio = FLAC(filepath)
                if audio.pictures:
                    return audio.pictures[0].data

            elif ext in ('mp3',):
                from mutagen.id3 import ID3
                tags = ID3(filepath)
                for key in tags.keys():
                    if key.startswith('APIC'):
                        return tags[key].data

            elif ext in ('aiff', 'aif'):
                from mutagen.aiff import AIFF
                audio = AIFF(filepath)
                if audio.tags:
                    for key in audio.tags.keys():
                        if key.startswith('APIC'):
                            return audio.tags[key].data

            elif ext in ('m4a', 'aac', 'mp4'):
                from mutagen.mp4 import MP4
                audio = MP4(filepath)
                if 'covr' in audio.tags:
                    covers = audio.tags['covr']
                    if covers:
                        return bytes(covers[0])

            elif ext in ('ogg', 'opus'):
                from mutagen.oggvorbis import OggVorbis
                from mutagen.flac import Picture
                import base64
                audio = OggVorbis(filepath)
                if 'metadata_block_picture' in audio:
                    pic = Picture(base64.b64decode(audio['metadata_block_picture'][0]))
                    return pic.data

            # 범용 폴백
            from mutagen import File as MutagenFile
            raw = MutagenFile(filepath, easy=False)
            if raw:
                if hasattr(raw, 'pictures') and raw.pictures:
                    return raw.pictures[0].data
                if raw.tags:
                    for key in raw.tags.keys():
                        if key.startswith('APIC'):
                            return raw.tags[key].data
                    if 'covr' in raw.tags:
                        covers = raw.tags['covr']
                        if covers:
                            return bytes(covers[0])
        except Exception as e:
            print(f'[Cover] {e}')
        return None

    @staticmethod
    def _calc_rg_gain(data: np.ndarray, target_lufs: float = -18.0) -> float:
        """PCM 데이터의 RMS를 측정해 target_lufs에 맞는 선형 게인 반환.
        최대 ±12 dB 보정으로 클리핑 방지."""
        rms = float(np.sqrt(np.mean(data ** 2)))
        if rms < 1e-9:
            return 1.0
        rms_db = 20.0 * np.log10(rms)
        gain_db = target_lufs - rms_db
        gain_db = max(-12.0, min(12.0, gain_db))  # ±12 dB 제한
        return float(10.0 ** (gain_db / 20.0))

    def set_rg_enabled(self, enabled: bool):
        self._rg_enabled = enabled

    # ─────────────────────────────────────────────
    # 재생 제어
    # ─────────────────────────────────────────────
    def play(self):
        if self._pcm_data is None and not self._is_dsd:
            return
        self._open_device()
        with self._lock:
            self._state = 'playing'

    def pause(self):
        with self._lock:
            if self._state == 'playing':
                self._state = 'paused'

    def resume(self):
        with self._lock:
            if self._state == 'paused':
                self._state = 'playing'

    def stop(self):
        self._state = 'idle'
        self._position = 0
        self._dsd_position = 0

    def seek(self, position_sec: float):
        if self._pcm_data is None and not self._is_dsd:
            return

        target_sample = max(0, int(position_sec * self._sample_rate))

        # 전환 시작
        with self._lock:
            was_playing = (self._state == 'playing')
            self._transitioning = True
            self._state = 'idle'

        if self._is_dsd:
            # DSD: 디코더 완전히 멈추기
            self._decode_stop.set()
            self._decode_stopped.wait(timeout=2.0)
            self._decode_stop = threading.Event()
            self._decode_stopped = threading.Event()
            self._decode_done = False
            self._dsd_position = target_sample

        with self._lock:
            self._flush_queue()

        # 장치 닫아서 HAL 버퍼 초기화
        self._close_device()

        if self._is_dsd:
            ready_event = threading.Event()
            stop_ev = self._decode_stop

            def chunk_cb(pcm, sr, info):
                while not stop_ev.is_set():
                    try:
                        self._pcm_queue.put(pcm, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                ready_event.set()

            def done_cb():
                self._decode_done = True
                ready_event.set()

            def error_cb(msg):
                ready_event.set()

            self._dsd_decoder.decode_streaming(
                self._current_file, chunk_cb, done_cb, error_cb,
                stop_event=stop_ev,
                seek_to_sample=target_sample,
                stopped_event=self._decode_stopped)

            ready_event.wait(timeout=3.0)
        else:
            self._position = max(0, min(target_sample, self._total_samples - 1))

        # 장치 새로 열기 (버퍼 깨끗한 상태)
        self._open_device()

        with self._lock:
            self._transitioning = False
            self._fade_out_frames = 0

        if was_playing:
            with self._lock:
                self._state = 'playing'

    def set_volume(self, volume: float):
        self._volume = max(0.0, min(1.0, volume))


    @property
    def is_playing(self) -> bool:
        return self._state == 'playing'

    @property
    def is_paused(self) -> bool:
        return self._state == 'paused'

    @property
    def current_position(self) -> float:
        if self._sample_rate == 0:
            return 0.0
        pos = self._dsd_position if self._is_dsd else self._position
        return pos / self._sample_rate

    @property
    def duration(self) -> float:
        if self._sample_rate == 0:
            return 0.0
        return self._total_samples / self._sample_rate

    # ─────────────────────────────────────────────
    # miniaudio 장치 관리
    # ─────────────────────────────────────────────
    def _open_device(self, force_restart: bool = False):
        """
        v2.0 장치 오픈:
        - Windows: WASAPI Exclusive 모드 (OS 믹서 우회)
        - macOS  : CoreAudio 독점 모드 (Hog) + 샘플레이트 직접 설정
        - 공통   : 트랙 SR에 맞춰 DAC SR 자동 전환 (auto_sr=True)
        force_restart=True: 항상 닫고 새로 열기
        force_restart=False: SR/채널 같으면 재사용
        """
        if not MA_AVAILABLE:
            return

        out_channels = min(self._channels, 2)
        # DoP 모드: DSD를 PCM으로 패킹하므로 출력 SR = DSD SR / 16
        if self._dop_mode and self._is_dsd:
            out_sr = max(176400, self._sample_rate // 16)
        elif self._fixed_output_sr > 0:
            out_sr = self._fixed_output_sr
        else:
            out_sr = self._sample_rate

        if not force_restart and (
                self._device is not None and
                self._device_samplerate == out_sr and
                self._device_channels == out_channels):
            return  # 재사용

        # 기존 장치 완전히 닫기
        self._close_device()

        self._device_samplerate = out_sr
        self._device_channels = out_channels

        # ── macOS: CoreAudio 버퍼 최소화만 적용 ──────────────────────
        # Hog(독점)는 장치 라우팅을 고정시켜 출력 장치 변경을 방해하므로 사용 안 함
        # miniaudio + REALTIME 스레드 + 50ms 버퍼로 충분한 품질 확보
        if _IS_MAC:
            # 선택 장치의 CoreAudio ID로 버퍼 크기만 최소화
            ca_dev = 0
            if self._selected_device_name:
                ca_dev = _ca_get_device_id_by_name(self._selected_device_name)
            if ca_dev == 0:
                ca_dev = _ca_get_default_output_device()
            if ca_dev:
                self._ca_device_id = ca_dev
                _ca_set_buffer_size(ca_dev, 512)
            self._ca_hogged = False  # Hog 미사용

        device_id = None
        if self._device_index is not None:
            device_id = self._device_index

        # ── 시도 순서: WASAPI Exclusive → WASAPI Shared → 기본값 ──
        open_attempts = []

        if _IS_WIN and self._exclusive_mode and MA_AVAILABLE:
            open_attempts.append(('wasapi_exclusive', device_id))

        # 공유 모드(fallback) — 항상 포함
        open_attempts.append(('shared', device_id))

        # device_id 지정 시, 그것도 실패하면 기본 장치로 한 번 더
        if device_id is not None:
            open_attempts.append(('shared', None))

        last_error = None
        for mode, dev_id in open_attempts:
            try:
                if mode == 'wasapi_exclusive':
                    self._device = _WasapiExclusiveDevice(
                        sample_rate=out_sr,
                        nchannels=out_channels,
                        device_id=dev_id,
                    )
                else:
                    # WASAPI shared / CoreAudio / 기본 백엔드
                    backends = []
                    if _IS_MAC:
                        backends = [miniaudio.Backend.COREAUDIO]
                    elif _IS_WIN:
                        backends = [miniaudio.Backend.WASAPI]

                    self._device = miniaudio.PlaybackDevice(
                        output_format=miniaudio.SampleFormat.FLOAT32,
                        nchannels=out_channels,
                        sample_rate=out_sr,
                        buffersize_msec=100,
                        device_id=dev_id,
                        backends=backends or [],
                        thread_prio=miniaudio.ThreadPriority.HIGHEST,
                    )

                print(f'[Device] 열림({mode}) — SR={out_sr} ch={out_channels} '
                      f'dev_id={dev_id}')
                self._start_permanent_generator()
                last_error = None
                break  # 성공

            except Exception as e:
                print(f'[Device] {mode} 실패({e})')
                self._device = None
                last_error = e

        if last_error is not None and self.on_error:
            self.on_error(f'오디오 장치를 열 수 없습니다: {last_error}')

    def _close_device(self):
        # macOS CoreAudio 독점 해제
        if _IS_MAC and self._ca_hogged and self._ca_device_id:
            _ca_release_hog(self._ca_device_id)
            self._ca_hogged = False
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    def _start_permanent_generator(self):
        """앱 시작 시 단 한 번 호출 — generator는 앱 종료까지 살아있음"""
        if self._device is None:
            return
        gen = self._permanent_generator()
        next(gen)
        self._device.start(gen)

    def _permanent_generator(self):
        """
        영구 generator — 절대 종료되지 않음.
        _lock으로 메인스레드와 동기화하여 이전 데이터 누출 방지.
        """
        out_ch = self._device_channels
        sr = self._device_samplerate
        _finished_fired = [False]

        frames = yield  # 장치 첫 요청

        # 샘플레이트에 비례한 최소 청크 크기 (약 10ms)
        min_chunk = max(512, int(sr * 0.01))

        # EQ 상태 (biquad zi) — generator 생애 동안 유지
        _eq_zi: Optional[np.ndarray] = None   # (n_bands, out_ch, 2)
        _eq_sos_cached: Optional[np.ndarray] = None

        while True:
            n = max(frames or 512, min_chunk)

            # ─── fade-out 처리: transitioning 직전 프레임들을 부드럽게 fade ───
            with self._lock:
                fof = self._fade_out_frames

            if fof > 0:
                with self._lock:
                    if self._is_dsd:
                        chunk = self._get_dsd_chunk(n, out_ch)
                    else:
                        chunk = self._get_pcm_chunk(n)
                    if chunk is not None:
                        chunk = self._fix_channels(chunk, out_ch).astype(np.float64)
                        if not self._bit_perfect:
                            _vol = self._volume * (self._rg_gain if self._rg_enabled else 1.0)
                            chunk = chunk * _vol
                        actual = len(chunk)
                        fade_len = min(actual, fof)
                        ramp = np.linspace(fof / max(fof, 1), 0.0, fade_len).reshape(-1, 1)
                        chunk[:fade_len] *= ramp
                        if actual > fade_len:
                            chunk[fade_len:] = 0.0
                        self._fade_out_frames = max(0, fof - actual)
                        if self._is_dsd:
                            self._dsd_position += actual
                        else:
                            self._position += actual
                        if actual < n:
                            pad = np.zeros((n - actual, out_ch), dtype=np.float64)
                            chunk = np.concatenate([chunk, pad], axis=0)
                        if self._dither_enabled and not self._bit_perfect:
                            chunk = AudioEngine._apply_dither(chunk)
                        chunk = np.clip(chunk, -1.0, 1.0).astype(np.float32)
                    else:
                        self._fade_out_frames = 0
                        chunk = np.zeros((n, out_ch), dtype=np.float32)
                frames = yield chunk
                continue

            # ─── 전환 중 또는 무음 타이머 구간: 무조건 무음 ───
            if self._transitioning or time.monotonic() < self._mute_until:
                frames = yield np.zeros((n, out_ch), dtype=np.float32)
                continue

            with self._lock:
                state = self._state

            if state != 'playing':
                _finished_fired[0] = False
                frames = yield np.zeros((n, out_ch), dtype=np.float32)
                continue

            # _lock 안에서 state 확인 + 데이터 읽기를 원자적으로 처리
            with self._lock:
                if self._state != 'playing':
                    # lock 획득 사이에 상태가 바뀐 경우
                    frames = yield np.zeros((n, out_ch), dtype=np.float32)
                    continue

                if self._is_dsd:
                    chunk = self._get_dsd_chunk(n, out_ch)
                else:
                    chunk = self._get_pcm_chunk(n)

                if chunk is None:
                    self._state = 'idle'
                    do_fire = not _finished_fired[0]
                    _finished_fired[0] = True
                else:
                    _finished_fired[0] = False
                    do_fire = False
                    chunk = self._fix_channels(chunk, out_ch).astype(np.float64)
                    actual = len(chunk)
                    if self._is_dsd:
                        self._dsd_position += actual
                    else:
                        self._position += actual
                    if actual < n:
                        pad = np.zeros((n - actual, out_ch), dtype=np.float64)
                        chunk = np.concatenate([chunk, pad], axis=0)
                    pos = self._dsd_position if self._is_dsd else self._position

            if do_fire:
                threading.Thread(target=self._fire_finished, daemon=True).start()
                frames = yield np.zeros((n, out_ch), dtype=np.float32)
                continue

            # VU / 위치 / 주파수 콜백 — EQ/볼륨 적용 전 원본 레벨 기준
            if self.on_vu_level:
                try:
                    l = float(np.sqrt(np.mean(chunk[:, 0] ** 2)))
                    r = float(np.sqrt(np.mean(chunk[:, 1] ** 2))) if out_ch > 1 else l
                    self.on_vu_level(min(l * 8.0, 1.0), min(r * 8.0, 1.0))
                except Exception:
                    pass

            if self.on_chunk_ready:
                try:
                    self.on_chunk_ready(chunk.astype(np.float32), sr)
                except Exception:
                    pass

            if self.on_position_changed:
                try:
                    self.on_position_changed(pos / sr, self._total_samples / sr)
                except Exception:
                    pass

            # ── DoP 모드: DSD 비트를 PCM 프레임으로 패킹 ──
            if self._dop_mode and self._is_dsd:
                dop_out = _pack_dop(chunk, self._dop_marker_toggle)
                if len(dop_out) < n:
                    pad = np.zeros((n - len(dop_out), out_ch), dtype=np.float32)
                    dop_out = np.concatenate([dop_out, pad], axis=0)
                frames = yield dop_out[:n].astype(np.float32)
                continue

            # ── 비트퍼펙트 모드: 모든 처리 bypass, 원본 그대로 ──
            if self._bit_perfect:
                frames = yield np.clip(chunk, -1.0, 1.0).astype(np.float32)
                continue

            # ── EQ 적용 (float64 유지) ──
            if self._eq_enabled:
                with self._eq_lock:
                    cur_sos = self._eq_sos
                if cur_sos is not None:
                    if cur_sos is not _eq_sos_cached:
                        _eq_sos_cached = cur_sos
                        _eq_zi = np.zeros((cur_sos.shape[0], out_ch, 2), dtype=np.float64)
                    try:
                        chunk, _eq_zi = AudioEngine._apply_eq_sos(cur_sos, chunk, _eq_zi)
                    except Exception:
                        pass

            # ── 볼륨 + ReplayGain 적용 (float64) ──
            _vol = self._volume * (self._rg_gain if self._rg_enabled else 1.0)
            chunk = chunk * _vol

            # ── TPDF 디더링 (float64 → float32 직전) ──
            if self._dither_enabled:
                chunk = AudioEngine._apply_dither(chunk)

            frames = yield np.clip(chunk, -1.0, 1.0).astype(np.float32)

    def _restart_generator(self):
        """곡 전환/seek 시 호출 — generator 교체 없이 state만 변경"""
        # 아무것도 안 함 — _permanent_generator가 _state를 보고 스스로 처리
        pass

    # ─────────────────────────────────────────────
    # 데이터 청크 헬퍼
    # ─────────────────────────────────────────────
    def _get_pcm_chunk(self, frames: int) -> Optional[np.ndarray]:
        remaining = self._total_samples - self._position
        if remaining <= 0:
            return None
        n = min(frames, remaining)
        return self._pcm_data[self._position:self._position + n]

    def _get_dsd_chunk(self, frames: int, out_ch: int) -> Optional[np.ndarray]:
        result = []
        needed = frames

        if self._dsd_buf:
            seg = self._dsd_buf[0]
            if len(seg) >= needed:
                result.append(seg[:needed])
                self._dsd_buf[0] = seg[needed:] if len(seg) > needed else None
                if self._dsd_buf[0] is None:
                    self._dsd_buf.pop(0)
                return np.concatenate(result, axis=0)
            else:
                result.append(seg)
                needed -= len(seg)
                self._dsd_buf.pop(0)

        while needed > 0:
            try:
                chunk = self._pcm_queue.get_nowait()
                if len(chunk) >= needed:
                    result.append(chunk[:needed])
                    leftover = chunk[needed:]
                    if len(leftover) > 0:
                        self._dsd_buf.insert(0, leftover)
                    needed = 0
                else:
                    result.append(chunk)
                    needed -= len(chunk)
            except queue.Empty:
                if self._decode_done and not result:
                    return None
                if needed > 0:
                    result.append(np.zeros((needed, out_ch), dtype=np.float32))
                    needed = 0
                break

        if not result:
            return None
        return np.concatenate(result, axis=0)

    @staticmethod
    def _fix_channels(chunk: np.ndarray, out_ch: int) -> np.ndarray:
        if chunk.ndim == 1:
            chunk = chunk.reshape(-1, 1)
        ch = chunk.shape[1]
        if ch < out_ch:
            chunk = np.repeat(chunk, out_ch // max(ch, 1), axis=1)[:, :out_ch]
        elif ch > out_ch:
            chunk = chunk[:, :out_ch]
        return chunk

    def _fire_finished(self):
        if self.on_playback_finished:
            try:
                self.on_playback_finished()
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # HiFi 품질 옵션 setter
    # ─────────────────────────────────────────────
    def set_bit_perfect(self, enabled: bool):
        """비트퍼펙트 모드 — EQ/RG/볼륨보정 완전 bypass, 원본 데이터 그대로 DAC"""
        self._bit_perfect = enabled
        print(f"[HiFi] 비트퍼펙트 {'ON' if enabled else 'OFF'}")

    def set_dither_enabled(self, enabled: bool):
        """TPDF 디더링 on/off"""
        self._dither_enabled = enabled

    def set_fixed_output_sr(self, sr: int):
        """출력 샘플레이트 고정 (0=파일 SR 그대로). 변경 시 현재 파일 재로드 필요."""
        self._fixed_output_sr = sr

    def set_exclusive_mode(self, enabled: bool):
        """
        Windows: WASAPI Exclusive (OS 믹서 우회)
        macOS  : CoreAudio Hog Mode (장치 독점)
        변경 시 장치를 닫고 새로 열어야 함 — 재생 중이면 자동 재시작
        """
        if self._exclusive_mode == enabled:
            return
        self._exclusive_mode = enabled
        was_playing = self._state == 'playing'
        self._state = 'idle'
        self._close_device()
        time.sleep(0.05)
        self._open_device(force_restart=True)
        if was_playing:
            self._state = 'playing'
        print(f"[HiFi] Exclusive 모드 {'ON' if enabled else 'OFF'}")

    def set_auto_sr(self, enabled: bool):
        """트랙 SR에 맞춰 DAC SR 자동 전환 on/off"""
        self._auto_sr = enabled
        print(f"[HiFi] 자동 SR 전환 {'ON' if enabled else 'OFF'}")

    def set_dop_mode(self, enabled: bool):
        """
        DoP (DSD over PCM) 모드 on/off
        DoP 지원 DAC (iFi, Chord, Schiit 등)에서만 의미 있음
        DSD 파일 재생 시 PCM 변환 대신 DoP 패킹으로 전송
        """
        self._dop_mode = enabled
        self._dop_marker_toggle = [0]
        print(f"[HiFi] DoP 모드 {'ON' if enabled else 'OFF'}"
              f"{' (DoP 지원 DAC 필요)' if enabled else ''}")

    def get_hifi_status(self) -> dict:
        """현재 HiFi 음질 상태 반환 (UI 표시용)"""
        return {
            'exclusive': self._exclusive_mode,
            'ca_hogged': self._ca_hogged,
            'auto_sr': self._auto_sr,
            'bit_perfect': self._bit_perfect,
            'dither': self._dither_enabled,
            'dop': self._dop_mode,
            'output_sr': self._device_samplerate,
            'source_sr': self._sample_rate,
            'backend': getattr(self._device, 'backend', 'N/A') if self._device else 'N/A',
        }

    @staticmethod
    def _resample(data: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        """scipy resample_poly — 고품질 다상 필터 업/다운샘플링 (float64 유지)"""
        from math import gcd
        g = gcd(src_sr, dst_sr)
        up, down = dst_sr // g, src_sr // g
        try:
            from scipy.signal import resample_poly
            # window='blackmanharris'로 사이드로브 억제 극대화
            result = resample_poly(data, up, down, axis=0,
                                   window=('kaiser', 14.0))
            return result.astype(np.float64)
        except Exception as e:
            print(f"[HiFi] 업샘플링 실패: {e}")
            return data

    @staticmethod
    def _apply_dither(data: np.ndarray) -> np.ndarray:
        """TPDF(Triangular PDF) 디더 — float64 → float32 변환 직전에 적용.
        두 개의 균등분포 노이즈를 더해 삼각형 PDF 생성.
        진폭: ±1 LSB at 24-bit (약 -144 dBFS) — 사실상 불가청."""
        lsb = 2.0 ** -23  # float32 가수부 23비트 기준 1 LSB
        noise = (np.random.uniform(-lsb, lsb, data.shape) +
                 np.random.uniform(-lsb, lsb, data.shape))
        return data + noise

    def cleanup(self):
        self._decode_stop.set()
        self._gen_stop.set()
        self._state = 'idle'
        time.sleep(0.05)
        self._close_device()

    # ─────────────────────────────────────────────
    # 파라메트릭 EQ
    # ─────────────────────────────────────────────
    def set_eq_enabled(self, enabled: bool):
        self._eq_enabled = enabled
        if enabled:
            self._rebuild_eq_sos()
            print(f"[EQ] ON — sos={self._eq_sos.shape if self._eq_sos is not None else None}")
        else:
            with self._eq_lock:
                self._eq_sos = None
            print("[EQ] OFF")

    def set_eq_params(self, params: list):
        """params: [(type, freq, gain_db, q), ...]"""
        self._eq_params = params
        if self._eq_enabled:
            self._rebuild_eq_sos()
        gains = [f"{p[2]:+.1f}" for p in params]
        print(f"[EQ] params → gains={gains}, enabled={self._eq_enabled}")

    def _rebuild_eq_sos(self):
        sr = self._device_samplerate or self._sample_rate or 44100
        sos = self._compute_eq_sos(self._eq_params, sr)
        with self._eq_lock:
            self._eq_sos = sos
        print(f"[EQ] rebuilt sos sr={sr} shape={sos.shape}")

    @staticmethod
    def _compute_eq_sos(params: list, sr: int) -> np.ndarray:
        """각 밴드의 biquad 계수를 (n_bands, 6) SOS 배열로 반환."""
        import math
        rows = []
        for (ftype, freq, gain_db, q) in params:
            f0   = max(20.0, min(float(freq), sr / 2.0 - 1.0))
            A    = 10.0 ** (gain_db / 40.0)
            w0   = 2.0 * math.pi * f0 / sr
            cw   = math.cos(w0)
            sw   = math.sin(w0)
            alpha = sw / (2.0 * q)

            if ftype == 'peak':
                b0 =  1.0 + alpha * A
                b1 = -2.0 * cw
                b2 =  1.0 - alpha * A
                a0 =  1.0 + alpha / A
                a1 = -2.0 * cw
                a2 =  1.0 - alpha / A
            elif ftype == 'lowshelf':
                sq = 2.0 * math.sqrt(A) * alpha
                b0 =       A * ((A + 1) - (A - 1) * cw + sq)
                b1 = 2.0 * A * ((A - 1) - (A + 1) * cw)
                b2 =       A * ((A + 1) - (A - 1) * cw - sq)
                a0 =            (A + 1) + (A - 1) * cw + sq
                a1 =    -2.0 * ((A - 1) + (A + 1) * cw)
                a2 =            (A + 1) + (A - 1) * cw - sq
            elif ftype == 'highshelf':
                sq = 2.0 * math.sqrt(A) * alpha
                b0 =       A * ((A + 1) + (A - 1) * cw + sq)
                b1 =-2.0 * A * ((A - 1) + (A + 1) * cw)
                b2 =       A * ((A + 1) + (A - 1) * cw - sq)
                a0 =            (A + 1) - (A - 1) * cw + sq
                a1 =  2.0 *    ((A - 1) - (A + 1) * cw)
                a2 =            (A + 1) - (A - 1) * cw - sq
            else:
                # bypass (gain=0 peaking)
                b0, b1, b2, a0, a1, a2 = 1, 0, 0, 1, 0, 0

            # SOS row: [b0/a0, b1/a0, b2/a0, 1, a1/a0, a2/a0]
            rows.append([b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0])
        return np.array(rows, dtype=np.float64)

    @staticmethod
    def _apply_eq_sos(sos: np.ndarray, chunk: np.ndarray,
                      zi: np.ndarray) -> tuple:  # noqa
        """
        scipy.signal.sosfilt 사용 — C 구현으로 빠름, 틱 없음.
        chunk : (N, ch) float32
        zi    : (n_bands, ch, 2) float64  — Direct-Form II 상태
        반환  : (filtered float32, new_zi)
        """
        from scipy.signal import sosfilt
        n_bands = sos.shape[0]
        ch = chunk.shape[1]
        x = chunk.astype(np.float64)   # (N, ch)

        for band in range(n_bands):
            out = np.empty_like(x)
            for c in range(ch):
                # sosfilt zi shape: (n_sections, 2) — 여기선 밴드 하나 = 1 section
                zi_in  = zi[band, c].reshape(1, 2)
                y, zo  = sosfilt(sos[band:band+1], x[:, c], zi=zi_in)
                out[:, c]   = y
                zi[band, c] = zo[0]
            x = out

        return x.astype(np.float32), zi


# ─────────────────────────────────────────────────────────────────────────────
# WASAPI Exclusive 장치 (Windows 전용)
# miniaudio.PlaybackDevice를 서브클래싱하지 않고,
# ffi/lib를 직접 사용해 ma_device_config에 exclusive shareMode를 주입
# ─────────────────────────────────────────────────────────────────────────────
class _WasapiExclusiveDevice:
    """
    Windows WASAPI Exclusive 모드 재생 장치.
    miniaudio의 내부 ffi/lib를 통해 ma_device_config를 직접 조작한다.

    핵심 설정:
      playback.shareMode = ma_share_mode_exclusive  → OS 믹서 완전 우회
      wasapi.noAutoConvertSRC = 1                   → WASAPI SRC 비활성화
      wasapi.noDefaultQualitySRC = 1                → 기본 품질 SRC 비활성화
      wasapi.usage = ma_wasapi_usage_pro_audio       → Pro Audio 스케줄링 (낮은 레이턴시)
    """

    def __init__(self, sample_rate: int, nchannels: int, device_id=None):
        if not MA_AVAILABLE:
            raise RuntimeError('miniaudio 없음')

        ffi = miniaudio.ffi
        lib = miniaudio.lib

        self.format        = miniaudio.SampleFormat.FLOAT32
        self.sample_width  = miniaudio.width_from_format(self.format)
        self.nchannels     = nchannels
        self.sample_rate   = sample_rate
        self.callback_generator = None
        self.backend       = 'WASAPI-Exclusive'

        self._ffi_handle = ffi.new_handle(self)
        self._device     = ffi.new('ma_device *')

        # ── ma_device_config 초기화 ──
        self._devconfig = lib.ma_device_config_init(lib.ma_device_type_playback)
        self._devconfig.sampleRate                  = sample_rate
        self._devconfig.playback.channels           = nchannels
        self._devconfig.playback.format             = self.format.value
        self._devconfig.playback.pDeviceID          = device_id or ffi.NULL
        self._devconfig.periodSizeInMilliseconds    = 50   # 50ms 버퍼
        self._devconfig.pUserData                   = self._ffi_handle
        self._devconfig.dataCallback                = lib._internal_data_callback
        self._devconfig.stopCallback                = lib._internal_stop_callback

        # ── WASAPI Exclusive 핵심 설정 ──
        self._devconfig.playback.shareMode          = lib.ma_share_mode_exclusive
        self._devconfig.wasapi.noAutoConvertSRC     = 1   # WASAPI SRC 비활성화
        self._devconfig.wasapi.noDefaultQualitySRC  = 1   # 기본 품질 SRC 비활성화
        self._devconfig.wasapi.usage                = lib.ma_wasapi_usage_pro_audio

        # ── WASAPI 백엔드로 컨텍스트 생성 ──
        self._context = ffi.new('ma_context *')
        backends_arr  = ffi.new('ma_backend[]', [lib.ma_backend_wasapi])
        ctx_config    = lib.ma_context_config_init()
        ret = lib.ma_context_init(
            backends_arr, 1,
            ffi.addressof(ctx_config),
            self._context,
        )
        if ret != lib.MA_SUCCESS:
            raise miniaudio.MiniaudioError('WASAPI 컨텍스트 초기화 실패', ret)

        # ── 장치 초기화 ──
        ret = lib.ma_device_init(
            self._context,
            ffi.addressof(self._devconfig),
            self._device,
        )
        if ret != lib.MA_SUCCESS:
            lib.ma_context_uninit(self._context)
            raise miniaudio.MiniaudioError(
                f'WASAPI Exclusive 장치 초기화 실패 (ret={ret:#010x}). '
                'DAC가 해당 SR/포맷을 Exclusive로 지원하지 않을 수 있습니다.', ret)

        print(f'[WASAPI] Exclusive 모드 열림 — SR={sample_rate} ch={nchannels}')

    def start(self, callback_generator):
        """재생 시작 — miniaudio.PlaybackDevice.start()와 동일 인터페이스"""
        ffi = miniaudio.ffi
        lib = miniaudio.lib
        self.callback_generator = callback_generator
        # generator 첫 요청으로 프라이밍
        try:
            next(self.callback_generator)
        except StopIteration:
            return
        ret = lib.ma_device_start(self._device)
        if ret != lib.MA_SUCCESS:
            raise miniaudio.MiniaudioError('WASAPI 재생 시작 실패', ret)

    def close(self):
        ffi = miniaudio.ffi
        lib = miniaudio.lib
        try:
            lib.ma_device_uninit(self._device)
            lib.ma_context_uninit(self._context)
        except Exception:
            pass
        print('[WASAPI] Exclusive 장치 닫힘')

    # miniaudio 내부 콜백이 self._ffi_handle을 통해 이 메서드를 호출
    def _data_callback(self, device, output, input, framecount):
        if self.callback_generator:
            try:
                samples = self.callback_generator.send(framecount)
            except StopIteration:
                return
            if samples is None:
                return
            import array as _arr
            if isinstance(samples, np.ndarray):
                samples = samples.flatten().astype(np.float32)
                buf = samples.tobytes()
            else:
                buf = bytes(samples)
            miniaudio.ffi.memmove(output, buf, min(len(buf), framecount * self.nchannels * self.sample_width))

    def _stop_callback(self, device):
        pass
