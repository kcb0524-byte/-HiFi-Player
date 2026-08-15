# -*- coding: utf-8 -*-
"""
음원 진위 감별 모듈 — '니콘 친게 음원 감별사'의 판정 엔진을 플레이어용으로 이식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
재생 중 흘러가는 PCM 청크를 모아 스펙트럼을 분석하고,
선언된 포맷(하이레조 PCM / DSD·SACD)이 실제 신호 특성과 일치하는지 판정한다.

판정 원리:
  · PCM: 컷오프 주파수가 나이퀴스트 대비 얼마나 뻗어 있는가.
    96kHz라고 선언했는데 22kHz에서 끊기면 → CD를 업샘플링한 가짜.
  · DSD/SACD: 진짜 DSD는 급차단 없이 초음파까지 자연 감쇠하지만,
    PCM을 DSD로 변환한 가짜는 원본 나이퀴스트(22.05/24/48kHz...)에
    20dB 이상의 '벽(brickwall)'이 남는다. 이 벽을 탐지한다.

결과 level: 'ok'(진본) / 'warn'(의심) / 'bad'(가짜 의심) / 'info'(판정 불가·생략)
"""

import numpy as np

FFT_SIZE = 32768          # 분석 창 크기
NEED_SAMPLES = FFT_SIZE * 4   # 판정에 모을 샘플 수 (약 3초 @44.1k)

LEVEL_COLOR = {           # 배지 색 (의미 고정 — 테마와 무관)
    'ok':   '#00e676',
    'warn': '#ffab40',
    'bad':  '#ff4444',
    'info': '#8888aa',
}


def _band_db(freqs, lin, f1, f2):
    m = (freqs >= f1) & (freqs < f2)
    if not m.any():
        return -300.0
    return float(10.0 * np.log10(max(float(lin[m].mean()), 1e-30)))


def _dsd_cutoff(freqs, lin):
    """DSD: 음악 대역 기준(15~20kHz) 대비 -30dB 지점을 음악 대역 상한으로 본다"""
    ref = _band_db(freqs, lin, 15000, 20000)
    if ref <= -299:
        ref = _band_db(freqs, lin, 5000, 15000)
    thr = ref - 30.0
    f, step = 20000.0, 500.0
    last = 20000.0
    while f < 120000.0:
        b = _band_db(freqs, lin, f, f + step)
        if b < thr:
            break
        last = f + step
        f += step
    return float(last)


def _find_brickwall(freqs, lin):
    """PCM 업변환 시 나타나는 급격한 차단(브릭월) 탐지 → (주파수, 낙폭dB)"""
    best_f, best_drop = 0.0, 0.0
    f, step = 18000.0, 1000.0
    top = min(70000.0, float(freqs[-1]) - 2000.0)
    while f < top:
        below = _band_db(freqs, lin, f - 2000, f)
        above = _band_db(freqs, lin, f, f + 2000)
        drop = below - above
        if drop > best_drop:
            best_drop, best_f = drop, f
        f += step
    return best_f, best_drop


def _judge_dsd(freqs, lin, cutoff, label):
    wall_f, drop = _find_brickwall(freqs, lin)

    if drop >= 20.0:
        for rate, nyq in [(44100, 22050), (48000, 24000),
                          (88200, 44100), (96000, 48000),
                          (176400, 88200), (192000, 96000)]:
            if abs(wall_f - nyq) <= 1500:
                hires = rate >= 88200
                return (('의심 · PCM 전사' if hires else '가짜 · 업스케일'),
                        ('warn' if hires else 'bad'),
                        f'{label} 표기이나 {nyq/1000:.2f}kHz에서 {drop:.0f}dB 급차단 — '
                        f'{rate/1000:g}kHz PCM 소스에서 변환된 것으로 보임')
        return ('의심', 'warn',
                f'{label} · {wall_f/1000:.0f}kHz에서 {drop:.0f}dB 급차단 — PCM 소스 가능성')

    if cutoff >= 30000:
        return ('진본', 'ok',
                f'{label} · 음악 대역 상한 {cutoff/1000:.0f}kHz, 급차단 없음 — 네이티브 DSD 특성')
    return ('의심', 'warn',
            f'{label} · 음악 대역 상한 {cutoff/1000:.0f}kHz — 고주파 성분 부족')


def _judge_pcm(dsr, cutoff, nyq, ratio):
    hi = dsr and dsr > 48000
    if hi and cutoff <= 22500:
        return ('가짜 · 업스케일 의심', 'bad',
                f'선언 {dsr//1000}kHz이나 실제 컷오프 {cutoff/1000:.1f}kHz — 업샘플링 의심')
    if ratio >= 0.85:
        return ('진본', 'ok',
                f'컷오프 {cutoff/1000:.1f}kHz (나이퀴스트 대비 {ratio*100:.0f}%) — 선언 품질과 일치')
    if ratio >= 0.65:
        return ('양호', 'ok',
                f'컷오프 {cutoff/1000:.1f}kHz (나이퀴스트 대비 {ratio*100:.0f}%) — 자연 감쇠 범위')
    if hi:
        return ('의심 · 업스케일 가능성', 'warn',
                f'컷오프 {cutoff/1000:.1f}kHz (나이퀴스트 대비 {ratio*100:.0f}%) — 실제 대역폭 낮음')
    return ('정보', 'info',
            f'컷오프 {cutoff/1000:.1f}kHz — 표준 해상도 음원 (판정 대상 아님)')


def analyze_stream(sr: int, mono: np.ndarray, *,
                   declared_sr: int = 0, is_dsd: bool = False,
                   dsd_label: str = '') -> dict:
    """
    재생 스트림에서 모은 모노 샘플을 판정.
      sr          : 샘플레이트 (청크 기준)
      mono        : float 모노 샘플 (NEED_SAMPLES 권장)
      declared_sr : 파일이 선언한 샘플레이트 (PCM 판정 기준)
      is_dsd      : DSD/SACD 소스 여부 (DSD 전용 판정 사용)
      dsd_label   : 'DSD64' 등 표기용
    반환: dict(verdict, level, color, detail, cutoff_khz)
    """
    n = len(mono)
    if n < FFT_SIZE:
        return dict(verdict='분석 불가', level='info',
                    color=LEVEL_COLOR['info'],
                    detail='분석에 필요한 데이터 부족', cutoff_khz=0.0)

    if n > FFT_SIZE * 4:
        mid = n // 2
        chunk = mono[mid - FFT_SIZE * 2: mid + FFT_SIZE * 2]
    else:
        chunk = mono

    win = np.hanning(len(chunk))
    spec = np.abs(np.fft.rfft(chunk * win))
    freqs = np.fft.rfftfreq(len(chunk), d=1.0 / sr)

    eps = 1e-12
    pdb = 20.0 * np.log10(np.maximum(spec, eps))
    mdb = float(pdb.max())
    lin = spec ** 2
    nyq = sr / 2.0

    if is_dsd:
        cutoff = _dsd_cutoff(freqs, lin)
        verdict, level, detail = _judge_dsd(freqs, lin, cutoff,
                                            dsd_label or 'DSD')
    else:
        valid = pdb >= mdb - 70.0
        idx = np.where(valid)[0]
        cutoff = float(freqs[idx[-1]]) if len(idx) else 0.0
        ratio = cutoff / nyq if nyq > 0 else 0.0
        verdict, level, detail = _judge_pcm(declared_sr or sr, cutoff, nyq, ratio)

    return dict(verdict=verdict, level=level,
                color=LEVEL_COLOR.get(level, LEVEL_COLOR['info']),
                detail=detail, cutoff_khz=cutoff / 1000.0)
