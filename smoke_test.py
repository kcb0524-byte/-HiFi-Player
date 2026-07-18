#!/usr/bin/env python3
"""
스모크 테스트 — 핵심 동작 자동 확인 (로컬 개발용)
=================================================
릴리스/커밋 전에 실행해서 재생·드래그·SACD 등 핵심 기능이 살아있는지 확인한다.

    python3 smoke_test.py            # 전체 실행
    python3 smoke_test.py --iso /path/to/sacd.iso   # SACD ISO 경로 직접 지정

- 실제 오디오 장치로 재생하되 볼륨 0, 비독점 모드로 사용자를 방해하지 않음
- SACD ISO / 문제 MP3 샘플은 없으면 SKIP (실패 아님)
- 종료 코드: 0=전부 통과, 1=실패 있음

배경: CI 빌드에서 miniaudio가 누락돼 '재생 상태인데 무음+0:00 고정' 앱이
배포된 사고가 있었음 — 1번(필수 모듈)과 2번(실재생) 검사가 그 재발 방지다.
"""
import os
import sys
import glob
import time
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RESULTS = []


def check(name, ok, detail=''):
    mark = '✓' if ok else '✗'
    print(f"{mark} {name}" + (f" — {detail}" if detail else ''))
    RESULTS.append((name, ok))
    return ok


def skip(name, why):
    print(f"- {name} — SKIP ({why})")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', help='SACD ISO 경로 (미지정 시 자동 탐색)')
    args = ap.parse_args()

    # ── 1. 필수 모듈 (CI 패키징 누락 방지 1차 방어) ──────────────
    missing = []
    for mod in ('miniaudio', 'soundfile', 'sounddevice', 'numpy', 'scipy',
                'mutagen', 'PyQt5'):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    check("필수 모듈 임포트", not missing, ', '.join(missing) or '전부 OK')

    import numpy as np
    import soundfile as sf_mod
    from PyQt5.QtWidgets import QApplication, QListWidgetItem
    from PyQt5.QtCore import Qt, QPoint, QPointF
    from PyQt5.QtGui import QWheelEvent
    app = QApplication([])

    from audio_engine import AudioEngine
    from ui_widgets import TrackItem, PlaylistWidget, natural_sort_key
    from player_window import HiFiPlayer

    # ── 2. 실재생: 사인파 FLAC 생성 → 재생 위치 증가 확인 ────────
    tone = np.sin(2 * np.pi * 440 * np.arange(44100 * 4) / 44100) * 0.3
    tmp_flac = os.path.join(tempfile.gettempdir(), 'ncmp_smoke_tone.flac')
    sf_mod.write(tmp_flac, tone.astype(np.float32), 44100)
    eng = AudioEngine()
    eng._exclusive_mode = False
    eng.set_volume(0.0)
    try:
        eng.load(tmp_flac)
        eng.play()
        time.sleep(3)
        pos = eng.current_position
        check("FLAC 실재생 (진행 시간 증가)", pos > 1.5 and eng.is_playing,
              f"3초 대기 후 pos={pos:.1f}s")
        eng.stop()
    except Exception as e:
        check("FLAC 실재생 (진행 시간 증가)", False, str(e))

    # ── 3. 폴더 드래그 수집: 자연 정렬 ───────────────────────────
    d = tempfile.mkdtemp(prefix='ncmp_smoke_')
    for n in ("11 - 마지막.mp3", "1 - 첫곡.mp3", "2 - 둘째.flac", "10 - 열째.mp3"):
        open(os.path.join(d, n), 'w').close()
    pw = PlaylistWidget()
    got = [os.path.basename(p) for p in pw._collect_from_dir(d)]
    check("폴더 수집 자연 정렬", got == ["1 - 첫곡.mp3", "2 - 둘째.flac",
                                          "10 - 열째.mp3", "11 - 마지막.mp3"], str(got))

    # ── 4. UI 로직 (offscreen + fake 엔진) ───────────────────────
    w = HiFiPlayer()
    w._clear_playlist()
    for i in range(4):
        it = QListWidgetItem()
        it.setData(Qt.UserRole + 1, TrackItem(f"/fake/{i}.mp3"))
        w.playlist.addItem(it)

    calls = []
    w._load_and_play = lambda idx, _s=None: calls.append(('play', idx))

    class FakeEngine:
        duration = 100.0
        current_position = 50.0
        is_playing = False
        is_paused = False
        def seek(self, p): calls.append(('seek', round(p, 1)))
        def pause(self): calls.append(('pause',))
        def resume(self): calls.append(('resume',))
        def stop(self): calls.append(('stop',))

    real_engine = w.engine

    # 4a. 재생 버튼 = 선택 곡
    w.engine = FakeEngine()
    calls.clear(); w.current_index = 0; w.playlist.setCurrentRow(2)
    w._toggle_play()
    check("재생 버튼 → 선택 곡 재생", calls == [('play', 2)], str(calls))

    # 4b. 이전 곡 3초 규칙
    calls.clear(); w.engine.is_playing = True
    w.current_index = 2; w.engine.current_position = 10.0
    w._prev_track()
    ok1 = calls == [('seek', 0.0)]
    calls.clear(); w.engine.current_position = 1.5
    w._prev_track()
    check("이전 곡 3초 규칙", ok1 and calls == [('play', 1)], str(calls))

    # 4c. 시크바 휠 시크
    calls.clear(); w.engine.current_position = 50.0
    ev = QWheelEvent(QPointF(5, 5), QPointF(50, 50), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    handled = w.eventFilter(w.seek_slider, ev)
    check("시크바 휠 시크(+5초)", handled and ('seek', 55.0) in calls, str(calls))

    # 4d. Bit Perfect 잠금/복원
    w.engine = real_engine
    w._on_bit_perfect_toggled(True)
    locked = (not w.slider_rg_target.isEnabled() and not w.vol_slider.isEnabled()
              and not w.eq_panel.isEnabled())
    w._on_bit_perfect_toggled(False)
    restored = (w.slider_rg_target.isEnabled() and w.vol_slider.isEnabled()
                and w.eq_panel.isEnabled())
    check("Bit Perfect 컨트롤 잠금/복원", locked and restored)

    # 4e. 다중 삭제 + 재생 정보 초기화
    w.engine = FakeEngine()
    w.current_index = 3
    w.lbl_title.setText("남아있으면 안 되는 제목")
    w._remove_tracks([0, 3])
    check("다중 삭제 + Now Playing 초기화",
          w.playlist.count() == 2 and w.current_index == -1
          and w.lbl_title.text() == "—")
    w.engine = real_engine

    # ── 5. SACD ISO (있을 때만) ─────────────────────────────────
    iso = args.iso
    if not iso:
        cands = glob.glob(os.path.expanduser('~/Desktop/**/*.iso'), recursive=True)
        iso = cands[0] if cands else None
    if iso and os.path.isfile(iso):
        import threading
        from sacd_decoder import SACDDecoder
        dec = SACDDecoder()
        tracks = dec.get_track_list(iso)
        if tracks:
            got_n = {'n': 0}
            stop = threading.Event()
            dec.decode_streaming(tracks[0],
                                 lambda p, s, i, g=got_n: g.__setitem__('n', g['n'] + len(p)),
                                 stop_event=stop)
            t0 = time.time()
            while got_n['n'] < 176400 * 3 and time.time() - t0 < 40:
                time.sleep(0.3)
            stop.set()
            check("SACD ISO 트랙 파싱+3초 디코드",
                  got_n['n'] >= 176400 * 3,
                  f"{len(tracks)}트랙, {os.path.basename(iso)}")
        else:
            check("SACD ISO 트랙 파싱+3초 디코드", False, "트랙 없음")
    else:
        skip("SACD ISO", "ISO 파일 없음 — --iso 로 지정 가능")

    # ── 6. 문제 MP3 구조대 (샘플 있을 때만) ─────────────────────
    # macOS는 파일명이 NFD라 NFC 리터럴 glob이 안 맞음 → 정규화 비교로 탐색
    import unicodedata
    bad = []
    base = os.path.dirname(os.path.abspath(__file__))
    for root, _dirs, files in os.walk(base):
        if unicodedata.normalize('NFC', os.path.basename(root)) == '되는거 안되는거':
            bad = [os.path.join(root, f) for f in files
                   if unicodedata.normalize('NFC', f).startswith('안되는거')
                   and f.endswith('.mp3')]
            break
    if bad:
        try:
            eng2 = AudioEngine()
            info = eng2._load_pcm(bad[0])
            check("문제 MP3 구조대 디코드", eng2._total_samples > 44100,
                  os.path.basename(bad[0])[:30])
        except Exception as e:
            check("문제 MP3 구조대 디코드", False, str(e)[:80])
    else:
        skip("문제 MP3 구조대", "샘플 폴더 없음")

    # ── 결과 ─────────────────────────────────────────────────────
    fails = [n for n, ok in RESULTS if not ok]
    print()
    if fails:
        print(f"❌ 실패 {len(fails)}건: {', '.join(fails)}")
        return 1
    print(f"✅ 스모크 테스트 전체 통과 ({len(RESULTS)}건)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
