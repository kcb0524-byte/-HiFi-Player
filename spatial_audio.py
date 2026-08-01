"""
Spatial Audio — 크로스피드 + 초기 반사음 기반 공간 음향 프로세서 v2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
헤드폰 청취 시 가상 스피커(±30°) + 청음실 공간감을 시뮬레이션한다.

3단계 모드:
  natural : 위상 정합형 크로스피드만 (bs2b 계열) — 가장 투명, 효과 은은
  strong  : 크로스피드 강화 + 초기 반사음 — 머리 밖 공간감 뚜렷 (기본값)
  wide    : 스테레오 확장 + 반사음 증가 — 넓은 무대감, 효과 최대

구성 요소:
  1) 크로스피드 — 반대 채널을 저역통과+감쇠하여 섞음 (스피커 청취 재현)
     직접음 보상과 동일 필터를 공유해 모노 성분 전달함수가 정확히 1.0
  2) 초기 반사음 — 8~40ms 지연·감쇠·고역흡수된 반사 성분 (벽/바닥 반사 재현)
     좌우 비대칭 지연으로 자연스러운 공간 비상관성 생성 → "머리 밖" 정위의 핵심
  3) 스테레오 확장(wide 전용) — M/S 처리로 사이드 성분 +22%

품질 원칙:
  · 전 구간 float64 처리
  · 청크 경계에서 필터 상태(zi)·지연 버퍼 연속 → 클릭/틱 없음
  · 반사음 합산 후 정규화로 클리핑 방지
  · 스테레오(2ch) 전용 — 그 외 채널 수는 상위에서 bypass
"""

import os
import sys
import numpy as np

try:
    from scipy.signal import butter, sosfilt, fftconvolve, resample_poly
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False


def _hrir_path():
    """PyInstaller 번들/개발 환경 모두에서 HRIR 데이터 경로 해석"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'spatial_hrir.npz')


# 3D 렌더러 음량 캘리브레이션 캐시 (샘플레이트 → norm)
_NORM_CACHE = {}


class _Hrtf3D:
    """
    360° HRTF 바이노럴 렌더러 (MIT KEMAR 실측 데이터 기반)

    스테레오 입력을 4개의 가상 스피커로 업믹스한 뒤, 각 방향의
    실측 HRIR(머리전달 임펄스 응답, 512탭)로 컨볼루션해 두 귀 신호를 합성한다.

      · 전방 좌/우 (±30°) : 원본 L/R 직접 배치 — 무대·보컬 유지
      · 후방 좌/우 (±110°): 좌우 차(앰비언스) 성분을 지연·저역통과 후 배치
                            → 홀 공간감·서라운드 방향감 생성

    품질/안정성:
      · float64 처리, overlap-add 방식 스트리밍 컨볼루션 (청크 경계 연속)
      · HRIR은 트랙 샘플레이트로 정밀 리샘플 (44.1k 기준 실측)
      · 초기화 시 기준 신호로 자동 음량 캘리브레이션 (ON/OFF 등청감)
    """

    SUR_DELAY_MS = (12.0, 15.0)   # 후방 좌/우 지연 (서로 다르게 → 비상관)
    SUR_LP_HZ = 6000.0            # 후방 앰비언스 고역 제한
    SUR_GAIN = 0.9                # 후방 레벨
    TOP_DELAY_MS = (9.0, 11.0)    # 상방 좌/우 지연
    TOP_HP_HZ = 1000.0            # 상방 채널 저역 컷 (높이 지각은 고역 위주)
    TOP_GAIN = 0.7                # 상방 레벨
    XOVER_HZ = 200.0              # 베이스 바이패스 크로스오버 — 이하 대역은 원음 직결
                                  # (저음은 방향 정보가 거의 없어 HRTF 불필요,
                                  #  웅웅거림·저역 왜곡 원천 차단)

    def __init__(self, sample_rate: int):
        self.sample_rate = int(sample_rate)

        z = np.load(_hrir_path())
        base_sr = float(z['samplerate'])
        # KEMAR 좌표 관례: az+ = 왼쪽 (데이터 검증 완료)
        # HRIR은 확산음장 보정(귓바퀴 공진 제거) 완료본 — 음색 평탄, 방향 단서 유지
        raw = {'C': z['az0'],
               'FL': z['az30'], 'FR': z['az-30'],
               'RL': z['az110'], 'RR': z['az-110'],
               'TL': z['top_l'], 'TR': z['top_r']}  # 상방 +50° (az ±48°)

        # 트랙 샘플레이트로 HRIR 리샘플
        self._h = {}
        for k, h in raw.items():
            h = np.asarray(h, dtype=np.float64)
            if self.sample_rate != base_sr:
                from math import gcd
                g = gcd(self.sample_rate, int(base_sr))
                h = resample_poly(h, self.sample_rate // g, int(base_sr) // g, axis=0)
            self._h[k] = np.ascontiguousarray(h)
        self._ntaps = len(self._h['FL'])

        # 후방 지연/필터 파라미터
        self._d_rl = max(1, int(self.sample_rate * self.SUR_DELAY_MS[0] * 1e-3))
        self._d_rr = max(1, int(self.sample_rate * self.SUR_DELAY_MS[1] * 1e-3))
        nyq = self.sample_rate * 0.5
        self._sos_sur = butter(1, min(self.SUR_LP_HZ, nyq * 0.9) / nyq,
                               btype='low', output='sos')

        # 상방 채널: 지연 + 고역통과 (높이 지각은 고역 스펙트럼 단서 위주)
        self._d_tl = max(1, int(self.sample_rate * self.TOP_DELAY_MS[0] * 1e-3))
        self._d_tr = max(1, int(self.sample_rate * self.TOP_DELAY_MS[1] * 1e-3))
        self._sos_top = butter(1, min(self.TOP_HP_HZ, nyq * 0.8) / nyq,
                               btype='high', output='sos')

        # 베이스 바이패스 크로스오버 (2차 LP; high = 원음 - low 로 완전 상보 분리)
        self._sos_xo = butter(2, self.XOVER_HZ / nyq, btype='low', output='sos')
        # 저역 직결 경로는 HRTF 경로의 그룹 지연만큼 지연시켜 위상 정렬
        self._d_bass = int(np.argmax(np.abs(self._h['FL'][:, 0])))

        self.reset()
        # 음량 캘리브레이션 — 샘플레이트별 캐시 (오디오 콜백 내 재생성 시
        # 무거운 재계산으로 인한 순간 끊김 방지)
        cached = _NORM_CACHE.get(self.sample_rate)
        if cached is not None:
            self._norm = cached
        else:
            self._norm = 1.0
            self._norm = self._calibrate()
            _NORM_CACHE[self.sample_rate] = self._norm
        self.reset()

    def _calibrate(self) -> float:
        """등청감 캘리브레이션 — 귀가 민감한 500Hz~8kHz 대역의 에너지를 기준으로
        렌더링 전후 체감 음량을 맞춘다 (전체 RMS 기준은 2-6kHz 방향 단서 부스트
        때문에 체감상 크게 들리는 문제가 있었음). 추가로 -1dB 여유 트림."""
        rng = np.random.default_rng(1)
        n = 16384
        # 핑크 노이즈 (실제 음악과 유사한 스펙트럼)
        def pink(sz):
            W = np.fft.rfft(rng.standard_normal(sz))
            f = np.fft.rfftfreq(sz)
            W[1:] /= np.sqrt(f[1:]); W[0] = 0
            x = np.fft.irfft(W); return x / np.std(x)
        M = pink(n); S = pink(n) * np.sqrt(0.3 / 0.7)
        ref = np.stack([M + S, M - S], axis=1) * 0.1
        out = self.process(ref.copy())
        # 체감 대역(500Hz~8kHz) 필터
        nyq = self.sample_rate * 0.5
        band = butter(2, [min(500.0, nyq * 0.4) / nyq, min(8000.0, nyq * 0.8) / nyq],
                      btype='band', output='sos')
        rb = sosfilt(band, ref[4096:, 0])
        ob = sosfilt(band, out[4096:, 0])
        in_rms = np.sqrt(np.mean(rb ** 2))
        out_rms = np.sqrt(np.mean(ob ** 2))
        trim = 10.0 ** (+0.5 / 20.0)  # +0.5dB — 켰을 때 살짝 크게 (사용자 선호)
        return float(in_rms / max(out_rms, 1e-12) * trim)

    def reset(self):
        nt = self._ntaps - 1
        # overlap-add 꼬리: 소스별 × 귀 2
        self._tails = {k: [np.zeros(nt), np.zeros(nt)] for k in self._h}
        # 후방 지연 버퍼
        self._dbuf_rl = np.zeros(self._d_rl, dtype=np.float64)
        self._dbuf_rr = np.zeros(self._d_rr, dtype=np.float64)
        n2 = self._sos_sur.shape[0]
        self._zi_sl = np.zeros((n2, 2), dtype=np.float64)
        self._zi_sr = np.zeros((n2, 2), dtype=np.float64)
        # 크로스오버 상태 + 저역 정렬 지연 버퍼
        n3 = self._sos_xo.shape[0]
        self._zi_xl = np.zeros((n3, 2), dtype=np.float64)
        self._zi_xr = np.zeros((n3, 2), dtype=np.float64)
        db = max(1, self._d_bass)
        self._dbuf_bl = np.zeros(db, dtype=np.float64)
        self._dbuf_br = np.zeros(db, dtype=np.float64)
        # 상방 채널 상태
        n4 = self._sos_top.shape[0]
        self._zi_tl = np.zeros((n4, 2), dtype=np.float64)
        self._zi_tr = np.zeros((n4, 2), dtype=np.float64)
        self._dbuf_tl = np.zeros(self._d_tl, dtype=np.float64)
        self._dbuf_tr = np.zeros(self._d_tr, dtype=np.float64)
        # 5.1 전용 상태 (메인 5채널 크로스오버 + 공용 베이스 지연)
        self._zi_xo51 = [np.zeros((n3, 2), dtype=np.float64) for _ in range(5)]
        self._dbuf_51 = np.zeros(db, dtype=np.float64)

    @staticmethod
    def _delay(x, buf):
        d = len(buf)
        joined = np.concatenate([buf, x])
        out = joined[:len(x)]
        buf[:] = joined[len(x):len(x) + d]
        return out

    def _conv_oa(self, x, key):
        """소스 x를 HRIR 쌍으로 컨볼루션 (overlap-add, 상태 유지) → (outL, outR)"""
        h = self._h[key]
        n = len(x)
        outs = []
        for ear in (0, 1):
            y = fftconvolve(x, h[:, ear])
            tail = self._tails[key][ear]
            nt = len(tail)
            y[:nt] += tail
            if len(y) > n:
                new_tail = y[n:]
                tail[:] = 0.0
                tail[:len(new_tail)] = new_tail
            outs.append(y[:n])
        return outs

    def process(self, chunk: np.ndarray) -> np.ndarray:
        n = len(chunk)
        L = np.ascontiguousarray(chunk[:, 0], dtype=np.float64)
        R = np.ascontiguousarray(chunk[:, 1], dtype=np.float64)

        # ── 베이스 바이패스: 200Hz 이하는 원음 직결 (완전 상보 분리) ──
        lo_l, self._zi_xl = sosfilt(self._sos_xo, L, zi=self._zi_xl)
        lo_r, self._zi_xr = sosfilt(self._sos_xo, R, zi=self._zi_xr)
        hi_l = L - lo_l
        hi_r = R - lo_r
        # 저역은 HRTF 경로 그룹 지연만큼 지연시켜 시간 정렬
        bass_l = self._delay(lo_l, self._dbuf_bl)
        bass_r = self._delay(lo_r, self._dbuf_br)

        # 전방: 중고역 L/R을 ±30° 가상 스피커에 직접 배치
        # (실제 스피커 청취와 동일한 구조 — 좌우 방향감(ILD/ITD) 최대 보존)
        Sd = (hi_l - hi_r) * 0.5      # 사이드(앰비언스) 성분

        # 후방 앰비언스: 사이드 성분 → 저역통과 → 지연 (좌우 다른 지연으로 비상관)
        S_l, self._zi_sl = sosfilt(self._sos_sur, Sd, zi=self._zi_sl)
        S_r, self._zi_sr = sosfilt(self._sos_sur, -Sd, zi=self._zi_sr)
        RL = self.SUR_GAIN * self._delay(S_l, self._dbuf_rl)
        RR = self.SUR_GAIN * self._delay(S_r, self._dbuf_rr)

        # 상방 앰비언스: 사이드 성분 → 고역통과 → 지연 → +50° 상방 스피커
        # (돔처럼 위에서 감싸는 느낌 — 높이 지각은 고역 스펙트럼 단서가 핵심)
        T_l, self._zi_tl = sosfilt(self._sos_top, Sd, zi=self._zi_tl)
        T_r, self._zi_tr = sosfilt(self._sos_top, -Sd, zi=self._zi_tr)
        TL = self.TOP_GAIN * self._delay(T_l, self._dbuf_tl)
        TR = self.TOP_GAIN * self._delay(T_r, self._dbuf_tr)

        fl_l, fl_r = self._conv_oa(hi_l, 'FL')
        fr_l, fr_r = self._conv_oa(hi_r, 'FR')
        rl_l, rl_r = self._conv_oa(RL, 'RL')
        rr_l, rr_r = self._conv_oa(RR, 'RR')
        tl_l, tl_r = self._conv_oa(TL, 'TL')
        tr_l, tr_r = self._conv_oa(TR, 'TR')

        out = np.empty((n, 2), dtype=np.float64)
        out[:, 0] = (fl_l + fr_l + rl_l + rr_l + tl_l + tr_l) * self._norm + bass_l
        out[:, 1] = (fl_r + fr_r + rl_r + rr_r + tl_r + tr_r) * self._norm + bass_r
        return out

    def process_51(self, chunk: np.ndarray) -> np.ndarray:
        """
        진짜 5.1 멀티채널 → 바이노럴 렌더링.
        chunk: (n, 6) float64 — FLAC 표준 채널 순서 [FL, FR, FC, LFE, BL, BR]

        각 채널을 '실측 HRIR의 해당 방향'으로 직접 렌더링한다:
          FL→+30°, FR→−30°, FC→0°(센터), BL→+110°, BR→−110°
        스테레오 모드처럼 앰비언스를 추정하지 않는다 — 리어 채널은
        실제로 뒤에서 나라고 믹싱된 소리이므로 그대로 뒤에 배치된다.
        저역(200Hz 이하)+LFE는 무지향이므로 원음 직결(양귀 동일)로 합산.
        """
        n = len(chunk)
        srcs = [('FL', chunk[:, 0]), ('FR', chunk[:, 1]), ('C', chunk[:, 2]),
                ('RL', chunk[:, 4]), ('RR', chunk[:, 5])]
        lfe = np.ascontiguousarray(chunk[:, 3], dtype=np.float64)

        bass_acc = lfe * 0.7071          # LFE는 -3dB로 합산 (표준 관례)
        out_l = np.zeros(n, dtype=np.float64)
        out_r = np.zeros(n, dtype=np.float64)

        for i, (key, x) in enumerate(srcs):
            x = np.ascontiguousarray(x, dtype=np.float64)
            lo, self._zi_xo51[i] = sosfilt(self._sos_xo, x, zi=self._zi_xo51[i])
            hi = x - lo
            bass_acc += lo
            yl, yr = self._conv_oa(hi, key)
            out_l += yl
            out_r += yr

        # 저역 합 — HRTF 경로 그룹 지연에 맞춰 정렬, 양귀 동일 (무지향)
        bass = self._delay(bass_acc * 0.7071, self._dbuf_51)

        out = np.empty((n, 2), dtype=np.float64)
        out[:, 0] = out_l * self._norm + bass
        out[:, 1] = out_r * self._norm + bass
        return out


# 모드별 파라미터 (v3 — 확장 지향 재튜닝)
# 크로스피드는 스테레오 폭을 '좁히는' 기술이므로 비중을 낮추고,
# 공간감의 주역을 반사음 + 스테레오 확장으로 이동. ON/OFF 등청감 음량 유지.
_MODE_PARAMS = {
    #            크로스피드fc  크로스피드dB   반사음스케일  사이드확장
    'natural': dict(fc=700.0, feed_db=-4.5,  refl=0.0,  side=1.0),   # 순수 크로스피드 (자연스러움 지향)
    'strong':  dict(fc=700.0, feed_db=-8.0,  refl=1.0,  side=1.15),  # 반사음 + 약한 확장 (기본)
    'wide':    dict(fc=700.0, feed_db=-10.0, refl=1.4,  side=1.35),  # 반사음 강화 + 넓은 확장
}

# 초기 반사음 탭: (지연 ms, 게인) — 소수(prime-ish) 간격으로 콤 필터링 최소화
_TAPS_SAME  = [(11.7, 0.13), (19.3, 0.09), (31.7, 0.055)]           # 같은 쪽 귀
_TAPS_CROSS = [(8.1, 0.15), (15.9, 0.105), (26.3, 0.065), (38.9, 0.042)]  # 반대쪽 귀
_R_DELAY_RATIO = 1.073   # 우채널 반사 지연을 살짝 다르게 → 좌우 비상관(자연스러움)
_REFL_LP_HZ = 4500.0     # 반사음 고역 흡수 (벽면 흡음 재현)


class SpatialProcessor:
    """스테이트풀 공간 음향 프로세서 — 청크 단위 스트리밍 처리."""

    MODES = ('natural', 'strong', 'wide', '3d')

    def __init__(self, sample_rate: int, mode: str = 'strong'):
        if not _SCIPY_OK:
            raise RuntimeError("scipy가 필요합니다 (pip install scipy)")
        if mode not in self.MODES:
            mode = 'strong'

        self.sample_rate = int(sample_rate)
        self.mode = mode

        # ── 3D Surround (HRTF) 모드: 별도 렌더러에 위임 ──
        self._hrtf = None
        if mode == '3d':
            self._hrtf = _Hrtf3D(self.sample_rate)
            return

        p = _MODE_PARAMS[mode]

        # ── 크로스피드 게인: k = r/(1+r) → 모노 성분 전달함수 1.0 보장 ──
        r = 10.0 ** (p['feed_db'] / 20.0)
        self._k = r / (1.0 + r)
        self._side = p['side']
        self._refl = p['refl']

        nyq = self.sample_rate * 0.5
        self._sos_xf = butter(1, min(p['fc'], nyq * 0.45) / nyq,
                              btype='low', output='sos')
        self._sos_refl = butter(1, min(_REFL_LP_HZ, nyq * 0.9) / nyq,
                                btype='low', output='sos')

        # ── 반사음 탭 (샘플 단위, 좌/우 비대칭) ──
        def _mk(taps, ratio):
            return [(max(1, int(round(self.sample_rate * ms * 1e-3 * ratio))), g)
                    for ms, g in taps]
        self._taps_same_l  = _mk(_TAPS_SAME, 1.0)
        self._taps_same_r  = _mk(_TAPS_SAME, _R_DELAY_RATIO)
        self._taps_cross_l = _mk(_TAPS_CROSS, 1.0)
        self._taps_cross_r = _mk(_TAPS_CROSS, _R_DELAY_RATIO)

        max_d = max(d for d, _ in
                    self._taps_same_l + self._taps_same_r
                    + self._taps_cross_l + self._taps_cross_r)
        self._hist_len = max_d

        # ── 음량 정책 (v3.1) ──
        # 직접음(현장감을 좌우하는 2~5kHz 대역 포함)은 거의 건드리지 않는다.
        # 반사음은 '공간이 더해진 것'이므로 굳이 상쇄하지 않음 — ON이 미세하게
        # 더 크거나 같게 들리는 것이 자연스럽고, "켜면 작아진다" 인상을 없앤다.
        # 사이드 확장분만 최소한으로 보정 (클리핑 여유 확보).
        self._norm = 1.0 / (1.0 + 0.10 * (self._side - 1.0))

        self.reset()

    def reset(self):
        """필터 상태·지연 버퍼 초기화"""
        if self._hrtf is not None:
            self._hrtf.reset()
            return
        n1 = self._sos_xf.shape[0]
        n2 = self._sos_refl.shape[0]
        self._zi_l = np.zeros((n1, 2), dtype=np.float64)
        self._zi_r = np.zeros((n1, 2), dtype=np.float64)
        self._zi_refl_l = np.zeros((n2, 2), dtype=np.float64)
        self._zi_refl_r = np.zeros((n2, 2), dtype=np.float64)
        self._hist_l = np.zeros(self._hist_len, dtype=np.float64)
        self._hist_r = np.zeros(self._hist_len, dtype=np.float64)

    def process(self, chunk: np.ndarray) -> np.ndarray:
        """
        chunk: (n, 2) float64 스테레오 PCM → 공간 음향 처리된 (n, 2) float64
        상태는 호출 간 유지되어 청크 경계 아티팩트가 없다.
        """
        if chunk.ndim != 2 or chunk.shape[1] != 2 or len(chunk) == 0:
            return chunk

        # ── 3D Surround (HRTF) 모드 위임 ──
        if self._hrtf is not None:
            return self._hrtf.process(chunk)

        return self._process_stereo_body(chunk)

    def process_51(self, chunk: np.ndarray) -> np.ndarray:
        """5.1(6ch) 입력 렌더링 — 3D 모드에서만 호출됨"""
        if self._hrtf is not None and chunk.ndim == 2 and chunk.shape[1] >= 6:
            return self._hrtf.process_51(chunk)
        return chunk

    def _process_stereo_body(self, chunk: np.ndarray) -> np.ndarray:

        n = len(chunk)
        L = np.ascontiguousarray(chunk[:, 0], dtype=np.float64)
        R = np.ascontiguousarray(chunk[:, 1], dtype=np.float64)

        # ── 1) 스테레오 확장 (wide 전용, M/S) ──
        if self._side != 1.0:
            M = (L + R) * 0.5
            S = (L - R) * 0.5 * self._side
            L, R = M + S, M - S

        # ── 2) 크로스피드 (위상 정합형 — 모노 성분 불변) ──
        lp_l, self._zi_l = sosfilt(self._sos_xf, L, zi=self._zi_l)
        lp_r, self._zi_r = sosfilt(self._sos_xf, R, zi=self._zi_r)
        k = self._k
        dry_l = (L - k * lp_l) + k * lp_r
        dry_r = (R - k * lp_r) + k * lp_l

        # ── 3) 초기 반사음 (natural 모드는 스킵) ──
        if self._refl > 0.0:
            joined_l = np.concatenate([self._hist_l, L])
            joined_r = np.concatenate([self._hist_r, R])
            h = self._hist_len

            wet_l = np.zeros(n, dtype=np.float64)
            wet_r = np.zeros(n, dtype=np.float64)
            for d, g in self._taps_same_l:
                wet_l += g * joined_l[h - d: h - d + n]
            for d, g in self._taps_cross_l:
                wet_l += g * joined_r[h - d: h - d + n]
            for d, g in self._taps_same_r:
                wet_r += g * joined_r[h - d: h - d + n]
            for d, g in self._taps_cross_r:
                wet_r += g * joined_l[h - d: h - d + n]

            # 벽면 흡음 (고역 감쇠) — 상태 유지
            wet_l, self._zi_refl_l = sosfilt(self._sos_refl, wet_l, zi=self._zi_refl_l)
            wet_r, self._zi_refl_r = sosfilt(self._sos_refl, wet_r, zi=self._zi_refl_r)

            out_l = (dry_l + self._refl * wet_l) * self._norm
            out_r = (dry_r + self._refl * wet_r) * self._norm

            # 히스토리 갱신 (다음 청크의 반사음 계산용)
            self._hist_l = joined_l[-h:].copy()
            self._hist_r = joined_r[-h:].copy()
        else:
            out_l, out_r = dry_l, dry_r

        out = np.empty_like(chunk, dtype=np.float64)
        out[:, 0] = out_l
        out[:, 1] = out_r
        return out
