"""
HiFi Player — UI 위젯 모음
TrackLoader, MarqueeLabel, CDWidget, EQGraph, PresetPanel, EQPanel,
ToggleSwitch, TransportButton, IconButton, VUMeter,
TrackItem, PlaylistDelegate, PlaylistWidget
"""

"""
HiFi Player - 고음질 음원 플레이어
DSF/DFF(DSD), FLAC, WAV, AIFF, MP3 등 광범위한 포맷 지원
외장 DAC 포함 모든 출력 장치 선택 가능
"""

import sys
import os
import json
import random
import threading
from pathlib import Path
from typing import Optional, List

import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QListWidget, QListWidgetItem,
    QFileDialog, QComboBox, QFrame, QSplitter, QProgressBar,
    QToolButton, QSizePolicy, QMenu, QAction, QAbstractItemView,
    QMessageBox, QStyle, QGridLayout, QScrollArea, QCheckBox,
    QStackedWidget, QStyledItemDelegate,
)
from PyQt5.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QUrl, QSize, QMimeData,
    QPoint, QRect, QEvent,
)
from PyQt5.QtGui import (
    QIcon, QFont, QFontMetrics, QPalette, QColor, QDragEnterEvent, QDropEvent,
    QPixmap, QPainter, QLinearGradient, QBrush, QPen, QPainterPath,
    QRadialGradient, QConicalGradient,
)

from audio_engine import AudioEngine, AudioDevice
from dsd_decoder import DSDDecoder


from constants import DARK, EQ_PRESETS, EQ_BAND_LABELS, STYLESHEET

class TrackLoader(QThread):
    loaded = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(float)   # 0.0~1.0 — SACD ISO 로딩 진행률

    def __init__(self, engine: AudioEngine, filepath: str, sacd_track_info=None):
        super().__init__()
        self.engine = engine
        self.filepath = filepath
        self.sacd_track_info = sacd_track_info

    def run(self):
        try:
            # SACD ISO: 엔진에 트랙 정보와 progress 콜백 미리 전달
            if self.sacd_track_info is not None:
                self.engine._sacd_track_info = self.sacd_track_info
                # progress 콜백: 스레드에서 시그널로 emit (Qt 크로스스레드 안전)
                def _prog(pct: float):
                    try:
                        self.progress.emit(float(pct))
                    except Exception:
                        pass
                self.engine._sacd_progress_cb = _prog
            info = self.engine.load(self.filepath)
            info['filepath'] = self.filepath
            self.loaded.emit(info)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────
# 마퀴(좌우 스크롤) 레이블 — 텍스트가 위젯 폭보다 길면 자동 스크롤
# ─────────────────────────────────────────────────────────────
class MarqueeLabel(QWidget):
    """텍스트가 너비를 초과하면 우→좌로 흐르는 스크롤 레이블."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text   = ""
        self._offset = 0
        self._timer  = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._paused = True          # 텍스트가 짧으면 정지
        self._font   = QFont()
        self._color  = QColor("#f0f0f4")
        self._speed  = 1             # 픽셀/틱
        self._gap    = 60            # 문자열 반복 사이 여백(px)
        self._text_w = 0

    def setFont(self, font: QFont):
        self._font = font
        self._recalc()
        self.update()

    def setStyleSheet(self, css: str):
        # color 파싱
        import re
        m = re.search(r'color\s*:\s*([^;]+)', css)
        if m:
            self._color = QColor(m.group(1).strip())
        super().setStyleSheet("background:transparent;")

    def setText(self, text: str):
        self._text   = text
        self._offset = 0
        self._recalc()
        self.update()

    def text(self) -> str:
        return self._text

    def _recalc(self):
        fm = self.fontMetrics() if self._font.family() else QFontMetrics(self._font)
        fm = QFontMetrics(self._font)
        self._text_w = fm.horizontalAdvance(self._text)
        avail = self.width() or 300
        if self._text_w > avail:
            if self._paused:
                self._paused = False
                self._timer.start(16)   # ~60 fps
        else:
            self._paused = True
            self._timer.stop()
            self._offset = 0

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalc()

    def _tick(self):
        cycle = self._text_w + self._gap
        self._offset = (self._offset + self._speed) % cycle
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(self._font)
        p.setPen(self._color)
        avail = self.width()
        if self._paused:
            # 짧으면 그냥 왼쪽 정렬
            p.drawText(0, 0, avail, self.height(),
                       Qt.AlignLeft | Qt.AlignVCenter, self._text)
        else:
            x = -self._offset
            cycle = self._text_w + self._gap
            # 2번 그려서 끊김 없이 이어지게
            for _ in range(3):
                if x < avail:
                    p.drawText(int(x), 0, self._text_w + 10, self.height(),
                               Qt.AlignLeft | Qt.AlignVCenter, self._text)
                x += cycle
        p.end()


# ─────────────────────────────────────────────────────────────
# CD 회전 애니메이션 위젯
# ─────────────────────────────────────────────────────────────
class CDWidget(QWidget):
    """앨범아트 없을 때 표시하는 LP 레코드 위젯 — 회전 애니메이션 포함"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 80)
        self._angle = 0.0
        self._spinning = False
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_spinning(self, on: bool):
        self._spinning = on
        if on:
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self):
        self._angle = (self._angle + 0.6) % 360.0
        self.update()

    def paintEvent(self, event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h   = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        r      = min(cx, cy) - 1.5

        p.save()
        p.translate(cx, cy)
        p.rotate(self._angle)

        # ── 1. LP 본체: 거의 검정 비닐 ──────────────────────────
        vinyl = QRadialGradient(0, 0, r)
        vinyl.setColorAt(0.00, QColor(38, 35, 42))
        vinyl.setColorAt(0.30, QColor(28, 26, 32))
        vinyl.setColorAt(0.60, QColor(22, 20, 26))
        vinyl.setColorAt(1.00, QColor(15, 14, 18))
        p.setBrush(vinyl)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(0, 0), int(r), int(r))

        # ── 2. 그루브(홈) 동심원 ─────────────────────────────────
        p.setBrush(Qt.NoBrush)
        groove_start = 0.30
        groove_end   = 0.96
        n_grooves    = 28
        for i in range(n_grooves):
            t   = groove_start + (groove_end - groove_start) * i / n_grooves
            rr  = r * t
            # 빛 반사 효과: 각도에 따라 밝기 변화
            bright = 18 + int(14 * abs(math.sin(math.radians(i * 13 + self._angle * 0.3))))
            pen = QPen(QColor(bright + 10, bright + 8, bright + 14, 180))
            pen.setWidthF(0.7)
            p.setPen(pen)
            p.drawEllipse(QPoint(0, 0), int(rr), int(rr))

        # ── 3. 광택 하이라이트 (회전과 함께) ────────────────────
        shine = QConicalGradient(0, 0, self._angle * 0.7)
        shine.setColorAt(0.00, QColor(255, 255, 255, 0))
        shine.setColorAt(0.08, QColor(255, 255, 255, 22))
        shine.setColorAt(0.15, QColor(255, 255, 255, 8))
        shine.setColorAt(0.55, QColor(255, 255, 255, 0))
        shine.setColorAt(0.58, QColor(180, 190, 255, 14))
        shine.setColorAt(0.65, QColor(255, 255, 255, 0))
        shine.setColorAt(1.00, QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(0, 0), int(r), int(r))

        # ── 4. 센터 레이블 (골드 톤 원형) ───────────────────────
        lr = int(r * 0.28)
        label_grad = QRadialGradient(-lr * 0.25, -lr * 0.3, lr * 1.3)
        label_grad.setColorAt(0.00, QColor(210, 175,  80))
        label_grad.setColorAt(0.40, QColor(185, 145,  55))
        label_grad.setColorAt(0.75, QColor(160, 120,  35))
        label_grad.setColorAt(1.00, QColor(130,  95,  20))
        p.setBrush(label_grad)
        p.setPen(QPen(QColor(100, 75, 15), 1))
        p.drawEllipse(QPoint(0, 0), lr, lr)

        # ── 5. 레이블 텍스트 — QPainterPath로 벡터 렌더링 ──────────
        # drawText() 대신 addText()→fillPath() 사용:
        # GDI 폰트 렌더러를 우회해 Windows 회전 좌표계에서도 글리치 없음
        hole_r = int(r * 0.055)
        fnt_top = QFont('Arial', max(5, int(lr * 0.30)), QFont.Bold)
        fnt_sub = QFont('Arial', max(4, int(lr * 0.24)))
        fm_top  = QFontMetrics(fnt_top)
        fm_sub  = QFontMetrics(fnt_sub)

        # "ZUNAS" — 구멍 위쪽
        tw  = fm_top.horizontalAdvance("ZUNAS")
        y_top = -hole_r - 4 - fm_top.descent()
        path_top = QPainterPath()
        path_top.addText(-tw / 2, y_top, fnt_top, "ZUNAS")
        p.setPen(Qt.NoPen)
        p.fillPath(path_top, QBrush(QColor(45, 28, 5)))

        # "Music" — 구멍 아래쪽
        tw2 = fm_sub.horizontalAdvance("Music")
        y_bot = hole_r + 4 + fm_sub.ascent()
        path_bot = QPainterPath()
        path_bot.addText(-tw2 / 2, y_bot, fnt_sub, "Music")
        p.fillPath(path_bot, QBrush(QColor(70, 48, 12)))

        # ── 6. 중앙 스핀들 구멍 ─────────────────────────────────
        p.setBrush(QColor(8, 7, 10))
        p.setPen(QPen(QColor(60, 55, 70), 1))
        p.drawEllipse(QPoint(0, 0), hole_r, hole_r)

        p.restore()  # translate + rotate 해제

        # ── 7. 외곽 테두리 ───────────────────────────────────────
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(50, 45, 58), 1))
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        # ── 8. 고정 하이라이트 (좌상단 빛) ──────────────────────
        hi = QRadialGradient(cx - r * 0.35, cy - r * 0.38, r * 0.5)
        hi.setColorAt(0.0, QColor(255, 255, 255, 45))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(hi)
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))


# ─────────────────────────────────────────────────────────────
# 그래픽 파라메트릭 EQ — EQGraph
# ─────────────────────────────────────────────────────────────
class EQGraph(QWidget):
    """Logic Pro 스타일 그래픽 EQ — 드래그로 gain/freq, 휠로 Q 조절"""
    params_changed = pyqtSignal(list)

    N_BANDS = 12
    BANDS = [
        ('lowshelf',    32,  0.7),
        ('peak',        64,  1.0),
        ('peak',       125,  1.0),
        ('peak',       250,  1.0),
        ('peak',       500,  1.0),
        ('peak',      1000,  1.0),
        ('peak',      2000,  1.0),
        ('peak',      4000,  1.0),
        ('peak',      6000,  1.0),
        ('peak',      8000,  1.0),
        ('peak',     16000,  1.0),
        ('highshelf', 20000, 0.7),
    ]
    BAND_COLORS = [
        QColor(255, 100,  40),   # 32Hz  — 주황
        QColor(255, 170,  40),   # 64Hz  — 금
        QColor(220, 220,  50),   # 125Hz — 노랑
        QColor(100, 220,  80),   # 250Hz — 연두
        QColor( 40, 200, 160),   # 500Hz — 청록
        QColor( 50, 160, 255),   # 1kHz  — 하늘
        QColor( 60, 100, 255),   # 2kHz  — 파랑
        QColor(100,  60, 255),   # 4kHz  — 보라
        QColor(160,  60, 240),   # 6kHz  — 연보라
        QColor(210,  60, 200),   # 8kHz  — 마젠타
        QColor(240,  80, 140),   # 16kHz — 핑크
        QColor(255, 120, 100),   # 20kHz — 살구
    ]
    ML, MT, MR, MB = 34, 12, 8, 24   # margins

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gains      = [0.0] * self.N_BANDS
        self._qs         = [b[2] for b in self.BANDS]
        self._freqs      = [float(b[1]) for b in self.BANDS]
        self._gain_range = 12.0   # ±6 또는 ±12 선택 가능
        self._drag_idx   = -1
        self._hover_idx  = -1
        self._drag_start = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(160)
        self.setMinimumWidth(300)

    # ── 좌표 변환 ──────────────────────────────────────────
    def _fx(self, freq):
        import math
        w = self.width() - self.ML - self.MR
        t = math.log10(max(freq, 20) / 20) / math.log10(1000)
        return self.ML + t * w

    def _xf(self, x):
        import math
        w = self.width() - self.ML - self.MR
        t = max(0.0, min(1.0, (x - self.ML) / w))
        return 20.0 * (10 ** (t * math.log10(1000)))

    def _gy(self, gain):
        h  = self.height() - self.MT - self.MB
        gr = self._gain_range
        return self.MT + h * (1.0 - (gain + gr) / (gr * 2))

    def _yg(self, y):
        h  = self.height() - self.MT - self.MB
        gr = self._gain_range
        return max(-gr, min(gr, (1.0 - (y - self.MT) / h) * (gr * 2) - gr))

    # ── 필터 응답 계산 ──────────────────────────────────────
    @staticmethod
    def _biquad_response(ftype, freq, gain_db, q, sr, freqs_arr):
        import math, cmath
        A  = 10 ** (gain_db / 40.0)
        w0 = 2 * math.pi * freq / sr
        cw = math.cos(w0); sw = math.sin(w0)
        alpha = sw / (2 * q)
        if ftype == 'peak':
            b = [1+alpha*A, -2*cw, 1-alpha*A]
            a = [1+alpha/A, -2*cw, 1-alpha/A]
        elif ftype == 'lowshelf':
            sq = 2 * math.sqrt(A) * alpha
            b = [A*((A+1)-(A-1)*cw+sq),  2*A*((A-1)-(A+1)*cw), A*((A+1)-(A-1)*cw-sq)]
            a = [(A+1)+(A-1)*cw+sq,      -2*((A-1)+(A+1)*cw),  (A+1)+(A-1)*cw-sq]
        else:
            sq = 2 * math.sqrt(A) * alpha
            b = [A*((A+1)+(A-1)*cw+sq), -2*A*((A-1)+(A+1)*cw), A*((A+1)+(A-1)*cw-sq)]
            a = [(A+1)-(A-1)*cw+sq,       2*((A-1)-(A+1)*cw),  (A+1)-(A-1)*cw-sq]
        a0 = a[0]
        b = [x/a0 for x in b]; a = [x/a0 for x in a]
        out = []
        for f in freqs_arr:
            w  = 2 * math.pi * f / sr
            z  = cmath.exp(1j * w)
            z2 = z * z
            H  = (b[0] + b[1]/z + b[2]/z2) / (1 + a[1]/z + a[2]/z2)
            out.append(20 * math.log10(max(abs(H), 1e-10)))
        return out

    def _total_response(self, freqs_arr, sr=44100):
        total = [0.0] * len(freqs_arr)
        for i, (ftype, _, _) in enumerate(self.BANDS):
            r = self._biquad_response(ftype, self._freqs[i], self._gains[i],
                                      self._qs[i], sr, freqs_arr)
            for j in range(len(freqs_arr)):
                total[j] += r[j]
        return total

    # ── 페인트 ──────────────────────────────────────────────
    def paintEvent(self, event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        gw = w - self.ML - self.MR
        gh = h - self.MT - self.MB

        # 배경
        p.fillRect(0, 0, w, h, QColor(10, 10, 18))
        p.fillRect(self.ML, self.MT, gw, gh, QColor(14, 14, 24))

        # dB 그리드 (gain_range에 따라 라벨 변경)
        gr = self._gain_range
        step = 3 if gr >= 12 else 2
        grid_dbs = list(range(int(-gr), int(gr) + 1, step))
        p.setFont(QFont('Arial', 7))
        for db in grid_dbs:
            y = int(self._gy(db))
            is_zero = (db == 0)
            p.setPen(QPen(QColor(70, 70, 110) if is_zero else QColor(40, 40, 66),
                          1.2 if is_zero else 0.8))
            p.drawLine(self.ML, y, w - self.MR, y)
            p.setPen(QColor(80, 80, 120))
            sign = '+' if db > 0 else ''
            p.drawText(2, y + 4, f'{sign}{db}')

        # 주파수 그리드
        fmarks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
        flabels = ['20', '50', '100', '200', '500', '1k', '2k', '5k', '10k', '20k']
        for freq, lbl in zip(fmarks, flabels):
            x = int(self._fx(freq))
            p.setPen(QPen(QColor(35, 35, 58), 0.8))
            p.drawLine(x, self.MT, x, h - self.MB)
            p.setPen(QColor(80, 80, 120))
            p.setFont(QFont('Arial', 7))
            p.drawText(x - 10, h - self.MB + 12, lbl)

        # 개별 밴드 곡선 + 채움
        N = 180
        freqs = [20 * (10 ** (i / (N-1) * math.log10(1000))) for i in range(N)]
        for i, (ftype, _, _) in enumerate(self.BANDS):
            if abs(self._gains[i]) < 0.01:
                continue
            col = self.BAND_COLORS[i]
            resp = self._biquad_response(ftype, self._freqs[i], self._gains[i],
                                         self._qs[i], 44100, freqs)
            zero_y = self._gy(0)
            path = QPainterPath()
            path.moveTo(self._fx(freqs[0]), zero_y)
            for j in range(N):
                path.lineTo(self._fx(freqs[j]), self._gy(resp[j]))
            path.lineTo(self._fx(freqs[-1]), zero_y)
            path.closeSubpath()
            p.fillPath(path, QColor(col.red(), col.green(), col.blue(), 28))
            pen = QPen(QColor(col.red(), col.green(), col.blue(), 90), 1.0)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            for j in range(1, N):
                p.drawLine(int(self._fx(freqs[j-1])), int(self._gy(resp[j-1])),
                           int(self._fx(freqs[j])),   int(self._gy(resp[j])))

        # 합산 응답
        total = self._total_response(freqs)
        path2 = QPainterPath()
        path2.moveTo(self._fx(freqs[0]), self._gy(total[0]))
        for j in range(1, N):
            path2.lineTo(self._fx(freqs[j]), self._gy(total[j]))
        # 곡선 아래 반투명 채움
        fill_path = QPainterPath(path2)
        fill_path.lineTo(self._fx(freqs[-1]), self._gy(0))
        fill_path.lineTo(self._fx(freqs[0]),  self._gy(0))
        fill_path.closeSubpath()
        p.fillPath(fill_path, QColor(80, 120, 220, 20))
        p.setPen(QPen(QColor(180, 200, 255), 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path2)

        # 테두리
        p.setPen(QPen(QColor(40, 40, 66), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.ML, self.MT, gw, gh)

        # 밴드 포인트
        for i in range(self.N_BANDS):
            col = self.BAND_COLORS[i]
            bx  = int(self._fx(self._freqs[i]))
            by  = int(self._gy(self._gains[i]))
            r   = 6 if i == self._hover_idx else 4
            # 글로우
            glow = QRadialGradient(bx, by, r * 3)
            glow.setColorAt(0, QColor(col.red(), col.green(), col.blue(), 50))
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(glow))
            p.setPen(Qt.NoPen)
            p.drawEllipse(bx - r*3, by - r*3, r*6, r*6)
            # 포인트 본체
            p.setBrush(col)
            p.setPen(QPen(QColor(255, 255, 255, 160), 1.0))
            p.drawEllipse(bx - r, by - r, r*2, r*2)
            # gain 레이블
            gain = self._gains[i]
            sign = '+' if gain >= 0 else ''
            p.setFont(QFont('Arial', 7, QFont.Bold))
            p.setPen(col.lighter(170))
            p.drawText(bx - 16, by - r - 3, f'{sign}{gain:.1f}')

    # ── 마우스 ───────────────────────────────────────────────
    def _hit(self, x, y, radius=9):
        for i in range(self.N_BANDS):
            bx = self._fx(self._freqs[i])
            by = self._gy(self._gains[i])
            if (x - bx)**2 + (y - by)**2 <= radius**2:
                return i
        return -1

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            idx = self._hit(e.x(), e.y())
            if idx >= 0:
                self._drag_idx = idx
                self._drag_start = (e.x(), e.y(), self._gains[idx], self._freqs[idx])
                self.setCursor(Qt.SizeAllCursor)

    def mouseMoveEvent(self, e):
        if self._drag_idx >= 0 and self._drag_start:
            sx, sy, sg, sf = self._drag_start
            dy = e.y() - sy
            gain = sg - dy * 0.14
            gr   = self._gain_range
            gain = max(-gr, min(gr, round(gain * 2) / 2))
            self._gains[self._drag_idx] = gain
            if self.BANDS[self._drag_idx][0] == 'peak':
                import math
                dx = e.x() - sx
                nf = sf * (10 ** (dx * 0.005))
                self._freqs[self._drag_idx] = max(25.0, min(18000.0, nf))
            self._notify()
            self.update()
        else:
            idx = self._hit(e.x(), e.y())
            if idx != self._hover_idx:
                self._hover_idx = idx
                self.setCursor(Qt.SizeAllCursor if idx >= 0 else Qt.ArrowCursor)
                self.update()

    def mouseReleaseEvent(self, e):
        self._drag_idx = -1
        self._drag_start = None
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, e):
        idx = self._hit(e.x(), e.y())
        if idx < 0:
            return
        delta = e.angleDelta().y() / 120
        q = self._qs[idx]
        q = max(0.1, min(10.0, round((q + delta * 0.12) * 100) / 100))
        self._qs[idx] = q
        self._notify()
        self.update()

    def _notify(self):
        self.params_changed.emit(self._build_params())

    def _build_params(self):
        return [(self.BANDS[i][0], self._freqs[i], self._gains[i], self._qs[i])
                for i in range(self.N_BANDS)]

    # ── 공개 API ─────────────────────────────────────────────
    def apply_preset(self, name):
        if name not in EQ_PRESETS:
            return
        for i, (ftype, freq, gain, q) in enumerate(EQ_PRESETS[name][:self.N_BANDS]):
            self._freqs[i] = float(freq)
            self._gains[i] = float(gain)
            self._qs[i]    = float(q)
        self.update()
        self._notify()

    def reset(self):
        for i in range(self.N_BANDS):
            self._gains[i] = 0.0
            self._freqs[i] = float(self.BANDS[i][1])
            self._qs[i]    = self.BANDS[i][2]
        self.update()
        self._notify()

    def get_params(self):
        return self._build_params()

    def set_params(self, params):
        for i, (ftype, freq, gain, q) in enumerate(params[:self.N_BANDS]):
            self._freqs[i] = float(freq)
            self._gains[i] = float(gain)
            self._qs[i]    = float(q)
        self.update()

    def set_gain_range(self, gain_range: float):
        """±6 또는 ±12 범위 전환. 현재 게인을 새 범위로 클램프."""
        self._gain_range = float(gain_range)
        for i in range(self.N_BANDS):
            self._gains[i] = max(-gain_range, min(gain_range, self._gains[i]))
        self.update()
        self._notify()

    def get_gain_range(self) -> float:
        return self._gain_range


# ─────────────────────────────────────────────────────────────
# PresetPanel — 세련된 프리셋 버튼 그리드 + 사용자 4슬롯
# ─────────────────────────────────────────────────────────────
class PresetPanel(QWidget):
    preset_selected = pyqtSignal(str)
    user_saved      = pyqtSignal(int, str)
    user_deleted    = pyqtSignal(int)

    SYSTEM_PRESETS = ["Flat"] + [k for k in EQ_PRESETS
                                  if k not in ("Custom", "Flat")]

    _S_BASE = (
        "QPushButton{background:#1a1a30;color:#a0a8c8;border:1px solid #303060;"
        "border-radius:5px;font-size:13px;padding:3px 5px;}"
        "QPushButton:hover{background:#22223a;color:#d0d8ff;border-color:#5050a0;}"
        "QPushButton:checked{background:#0e2050;color:#70c0ff;"
        "border:1.5px solid #3080e0;font-weight:bold;}")
    _S_FLAT = (  # Flat은 그리드 내 _S_BASE와 동일, 레거시용으로 유지
        "QPushButton{background:#1a1a30;color:#a0a8c8;border:1px solid #303060;"
        "border-radius:5px;font-size:13px;padding:3px 5px;}"
        "QPushButton:hover{background:#22223a;color:#d0d8ff;}")
    _S_USER = (
        "QPushButton{background:#161628;color:#9090b8;border:1px dashed #383868;"
        "border-radius:5px;font-size:12px;padding:3px 5px;}"
        "QPushButton:hover{background:#1e1e3a;color:#c0c0e0;border-color:#5050a0;}"
        "QPushButton:checked{background:#0a1a40;color:#80b0f0;"
        "border:1.5px solid #3070c0;font-weight:bold;}")
    _S_SAVE = (
        "QPushButton{background:#0e1e0e;color:#70b870;border:1px solid #1e3e1e;"
        "border-radius:4px;font-size:12px;}"
        "QPushButton:hover{background:#162816;color:#90d890;}")
    _S_DEL  = (
        "QPushButton{background:#1e0e0e;color:#c06060;border:1px solid #3e1e1e;"
        "border-radius:4px;font-size:12px;}"
        "QPushButton:hover{background:#281616;color:#e08080;}")

    NUM_USER_SLOTS = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._user_presets = {i: None for i in range(self.NUM_USER_SLOTS)}
        self._active_btn   = None
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 0)
        root.setSpacing(4)

        # 시스템 프리셋 레이블
        lbl = QLabel("PRESETS")
        lbl.setStyleSheet("color:#e0e0ff;font-size:13px;font-weight:bold;letter-spacing:1px;margin-top:2px;")
        root.addWidget(lbl)

        # 4열 그리드 (Flat 포함)
        grid_w = QWidget()
        gl = QGridLayout(grid_w)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(3)
        self._sys_btns = {}
        for idx, name in enumerate(self.SYSTEM_PRESETS):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setStyleSheet(self._S_BASE)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, n=name: self._select(n))
            gl.addWidget(btn, *divmod(idx, 4))
            self._sys_btns[name] = btn
        root.addWidget(grid_w)

        # 사용자 슬롯 — 가로 한 줄, 우클릭으로 저장/삭제
        lbl2 = QLabel("MY PRESETS  (Right-click: Save/Delete)")
        lbl2.setStyleSheet("color:#e0e0ff;font-size:13px;font-weight:bold;letter-spacing:1px;margin-top:4px;")
        root.addWidget(lbl2)

        user_row = QWidget()
        ul = QHBoxLayout(user_row)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(3)

        self._user_btns = []
        for slot in range(self.NUM_USER_SLOTS):
            btn = QPushButton(f"Slot {slot+1}")
            btn.setCheckable(True)
            btn.setStyleSheet(self._S_USER)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, s=slot: self._select_user(s))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda _, s=slot: self._user_context_menu(s))
            ul.addWidget(btn, 1)
            self._user_btns.append((btn, None, None))

        root.addWidget(user_row)

    def _set_btn_active(self, btn, active: bool):
        """버튼 checked 상태를 설정하고 스타일을 강제 갱신한다."""
        btn.setChecked(active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    def _deactivate(self):
        if self._active_btn:
            self._set_btn_active(self._active_btn, False)
        self._active_btn = None

    def _select(self, name):
        self._deactivate()
        if name in self._sys_btns:
            self._set_btn_active(self._sys_btns[name], True)
            self._active_btn = self._sys_btns[name]
        self._active_name = name
        self.preset_selected.emit(name)

    def _select_user(self, slot):
        if self._user_presets[slot] is None:
            self._set_btn_active(self._user_btns[slot][0], False)
            return
        self._deactivate()
        self._set_btn_active(self._user_btns[slot][0], True)
        self._active_btn = self._user_btns[slot][0]
        self._active_name = f"__user_{slot}"
        self.preset_selected.emit(f"__user_{slot}")

    def _user_context_menu(self, slot):
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#16162a;color:#a0a0c8;border:1px solid #303060;}"
            "QMenu::item{padding:5px 16px;}"
            "QMenu::item:selected{background:#1e2e50;color:#ffffff;}"
        )
        act_save = menu.addAction("💾  Save Current EQ")
        act_del  = menu.addAction("✕  Clear Slot")
        act_del.setEnabled(self._user_presets[slot] is not None)
        chosen = menu.exec_(self._user_btns[slot][0].mapToGlobal(
            self._user_btns[slot][0].rect().bottomLeft()))
        if chosen == act_save:
            self._save_user(slot)
        elif chosen == act_del:
            self._del_user(slot)

    def _save_user(self, slot):
        from PyQt5.QtWidgets import QInputDialog
        cur = (self._user_presets[slot][0]
               if self._user_presets[slot] else f"My Preset {slot+1}")
        name, ok = QInputDialog.getText(self, "Save Preset",
                                        f"Slot {slot+1} name:", text=cur)
        if ok and name.strip():
            self._user_btns[slot][0].setText(name.strip())
            self.user_saved.emit(slot, name.strip())

    def _del_user(self, slot):
        self._user_presets[slot] = None
        self._user_btns[slot][0].setText(f"Slot {slot+1}")
        if self._active_btn == self._user_btns[slot][0]:
            self._active_btn = None
        self.user_deleted.emit(slot)

    def set_user_preset(self, slot, name, params):
        self._user_presets[slot] = (name, params)
        self._user_btns[slot][0].setText(name)

    def mark_active(self, name):
        self._deactivate()
        if name in self._sys_btns:
            self._set_btn_active(self._sys_btns[name], True)
            self._active_btn = self._sys_btns[name]
        elif name.startswith("__user_"):
            try:
                slot = int(name.split("_")[-1])
                btn = self._user_btns[slot][0]
                self._set_btn_active(btn, True)
                self._active_btn = btn
            except (IndexError, ValueError):
                pass
        self._active_name = name

    def get_active_preset(self):
        return getattr(self, '_active_name', 'Custom')


# ─────────────────────────────────────────────────────────────
# EQPanel — 그래프 + 프리셋 + ON/OFF 통합
# ─────────────────────────────────────────────────────────────
class EQPanel(QWidget):
    params_changed  = pyqtSignal(list)
    enabled_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled      = False
        self._user_presets = {i: None for i in range(PresetPanel.NUM_USER_SLOTS)}
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(5)

        # 헤더
        hdr = QHBoxLayout()
        self.btn_onoff = QPushButton("EQ OFF")
        self.btn_onoff.setCheckable(True)
        self.btn_onoff.setFixedHeight(26)
        self.btn_onoff.setMinimumWidth(72)
        self.btn_onoff.setStyleSheet(
            "QPushButton{background:#10101e;color:#404060;border:1px solid #202030;"
            "border-radius:4px;font-size:13px;font-weight:bold;letter-spacing:1px;}"
            "QPushButton:checked{background:#0a1a38;color:#50aaff;"
            "border:2px solid #2060d0;}")
        self.btn_onoff.clicked.connect(self._on_toggle)

        # ±6dB / ±12dB 범위 선택 버튼
        _rng_style = (
            "QPushButton{background:#10101e;color:#505070;border:1px solid #202030;"
            "border-radius:4px;font-size:11px;font-weight:bold;padding:2px 7px;}"
            "QPushButton:checked{background:#1a1020;color:#d080ff;"
            "border:2px solid #8040c0;}"
            "QPushButton:hover{color:#9090d0;}")
        self.btn_rng6  = QPushButton("±6dB")
        self.btn_rng12 = QPushButton("±12dB")
        for b in (self.btn_rng6, self.btn_rng12):
            b.setCheckable(True)
            b.setFixedHeight(26)
            b.setStyleSheet(_rng_style)
        self.btn_rng12.setChecked(True)   # 기본값 ±12dB
        self.btn_rng6.clicked.connect(lambda: self._set_range(6))
        self.btn_rng12.clicked.connect(lambda: self._set_range(12))

        hint = QLabel("드래그: gain/freq  •  휠: Q (대역폭)")
        hint.setStyleSheet("color:#9090c0;font-size:12px;")

        hdr.addWidget(self.btn_onoff)
        hdr.addSpacing(8)
        hdr.addWidget(self.btn_rng6)
        hdr.addWidget(self.btn_rng12)
        hdr.addWidget(hint, 1)
        root.addLayout(hdr)

        # EQ 그래프
        self.graph = EQGraph()
        self.graph.setMinimumHeight(170)
        self.graph.params_changed.connect(self._on_graph_changed)
        root.addWidget(self.graph, 2)

        # 프리셋 패널 (스크롤 없이 직접)
        self.preset_panel = PresetPanel()
        self.preset_panel.preset_selected.connect(self._on_preset_selected)
        self.preset_panel.user_saved.connect(self._on_user_saved)
        self.preset_panel.user_deleted.connect(self._on_user_deleted)
        root.addWidget(self.preset_panel, 1)

    def _on_toggle(self):
        self._enabled = self.btn_onoff.isChecked()
        self.btn_onoff.setText("EQ ON" if self._enabled else "EQ OFF")
        self.enabled_changed.emit(self._enabled)

    def _set_range(self, r: int):
        """±6 또는 ±12 범위 전환"""
        self.btn_rng6.setChecked(r == 6)
        self.btn_rng12.setChecked(r == 12)
        self.graph.set_gain_range(r)
        self.params_changed.emit(self.graph.get_params())

    def _on_reset(self):
        self.graph.reset()
        self.preset_panel.mark_active("Flat")

    def _on_graph_changed(self, params):
        self.params_changed.emit(params)

    def _on_preset_selected(self, name):
        if name.startswith("__user_"):
            slot = int(name[-1])
            data = self._user_presets.get(slot)
            if data:
                _, pp = data  # (name, params) 튜플
                self.graph.set_params(pp)
                self.params_changed.emit(self.graph.get_params())
        else:
            self.graph.apply_preset(name)
            self.params_changed.emit(self.graph.get_params())

    def _on_user_saved(self, slot, name):
        params = self.graph.get_params()
        self._user_presets[slot] = (name, params)   # (이름, params) 튜플로 통일
        self.preset_panel.set_user_preset(slot, name, params)

    def _on_user_deleted(self, slot):
        self._user_presets[slot] = None

    # ── 공개 API ──
    def get_params(self):
        return self.graph.get_params()

    def get_enabled(self):
        return self._enabled

    def get_preset(self):
        return self.preset_panel.get_active_preset()

    def set_state(self, enabled, gains, preset="Custom",
                  freqs=None, qs=None, user_presets=None):
        self._enabled = enabled
        self.btn_onoff.setChecked(enabled)
        self.btn_onoff.setText("EQ ON" if enabled else "EQ OFF")
        df = [float(b[1]) for b in EQGraph.BANDS]
        dq = [b[2] for b in EQGraph.BANDS]
        flist = freqs or df
        qlist = qs    or dq
        params = [(EQGraph.BANDS[i][0],
                   float(flist[i]),
                   float(gains[i]) if i < len(gains) else 0.0,
                   float(qlist[i]))
                  for i in range(EQGraph.N_BANDS)]
        self.graph.set_params(params)
        if user_presets:
            for slot, data in user_presets.items():
                if data:
                    name, pp = data
                    self._user_presets[int(slot)] = (name, pp)  # (name, params) 튜플로 통일
                    self.preset_panel.set_user_preset(int(slot), name, pp)
        self.preset_panel.mark_active(preset)


# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# iOS 스타일 토글 스위치
# ─────────────────────────────────────────────────────────────
class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked=True, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._anim = 1.0 if checked else 0.0  # 0.0=OFF, 1.0=ON (knob 위치)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.setInterval(12)
        self._timer.timeout.connect(self._animate)

    def isChecked(self):
        return self._checked

    def setChecked(self, val):
        self._checked = val
        self._anim = 1.0 if val else 0.0
        self.update()

    def _animate(self):
        target = 1.0 if self._checked else 0.0
        step = 0.12
        if abs(self._anim - target) < step:
            self._anim = target
            self._timer.stop()
        else:
            self._anim += step if target > self._anim else -step
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._checked = not self._checked
            self._timer.start()
            self.toggled.emit(self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2

        # 트랙 색: OFF=#2a2a40, ON=#2060d0
        t = self._anim
        off_c = QColor(42, 42, 64)
        on_c  = QColor(32, 96, 208)
        track_c = QColor(
            int(off_c.red()   + (on_c.red()   - off_c.red())   * t),
            int(off_c.green() + (on_c.green() - off_c.green()) * t),
            int(off_c.blue()  + (on_c.blue()  - off_c.blue())  * t),
        )
        p.setBrush(track_c)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, w, h, r, r)

        # 노브
        pad = 3
        knob_d = h - pad * 2
        knob_x = pad + (w - pad * 2 - knob_d) * t
        p.setBrush(QColor(230, 230, 255))
        p.drawEllipse(int(knob_x), pad, knob_d, knob_d)
        p.end()


# ─────────────────────────────────────────────────────────────
# 트랜스포트 버튼 (QPainter 직접 드로잉 — 세련된 벡터 아이콘)
# ─────────────────────────────────────────────────────────────
class TransportButton(QWidget):
    """재생/일시정지/정지/이전/다음 버튼을 QPainter로 직접 그림."""
    clicked = pyqtSignal()

    # icon: 'play'|'pause'|'stop'|'prev'|'next'|'loading'
    def __init__(self, icon: str, size: int = 40, is_primary: bool = False, parent=None):
        super().__init__(parent)
        self._icon      = icon
        self._is_primary = is_primary
        self._hovered   = False
        self._pressed   = False
        self._enabled   = True
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def set_icon(self, icon: str):
        self._icon = icon
        self.update()

    def setEnabled(self, val: bool):
        self._enabled = val
        self.update()

    # setText / isEnabled 호환 shim
    def setText(self, text: str):
        mapping = {'▶': 'play', '⏸': 'pause', '⏳': 'loading',
                   '⏮': 'prev', '⏭': 'next', '⏹': 'stop'}
        self._icon = mapping.get(text, self._icon)
        self.update()

    def isEnabled(self) -> bool:
        return self._enabled

    def event(self, e):
        if e.type() == QEvent.HoverEnter:
            self._hovered = True; self.update()
        elif e.type() == QEvent.HoverLeave:
            self._hovered = False; self.update()
        return super().event(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._enabled:
            self._pressed = True; self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pressed = False; self.update()
            if self._enabled and self.rect().contains(e.pos()):
                self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        # 투명도
        alpha = 255 if self._enabled else 80

        if self._is_primary:
            # 황금 원형 배경
            if self._pressed:
                bg = QColor(168, 136, 80, alpha)
            elif self._hovered:
                bg = QColor(220, 185, 110, alpha)
            else:
                bg = QColor(200, 169, 110, alpha)
            r = min(w, h) / 2 - 2
            p.setBrush(bg)
            p.setPen(Qt.NoPen)
            p.drawEllipse(int(cx - r), int(cy - r), int(r*2), int(r*2))
            icon_color = QColor(20, 15, 5, alpha)
        else:
            # 보조 버튼: 호버 시 반투명 원
            if self._hovered and self._enabled:
                p.setBrush(QColor(255, 255, 255, 18))
                p.setPen(Qt.NoPen)
                r = min(w, h) / 2 - 1
                p.drawEllipse(int(cx-r), int(cy-r), int(r*2), int(r*2))
            if self._pressed:
                icon_color = QColor(200, 169, 110, alpha)
            elif self._hovered and self._enabled:
                icon_color = QColor(240, 220, 170, alpha)
            else:
                icon_color = QColor(160, 160, 185, alpha)

        p.setPen(Qt.NoPen)
        p.setBrush(icon_color)

        icon = self._icon
        m = min(w, h)

        if icon == 'play':
            # 삼각형 — 살짝 오른쪽 오프셋
            s = m * 0.28
            ox = cx + s * 0.12
            pts = [
                QPoint(int(ox - s*0.6), int(cy - s)),
                QPoint(int(ox + s*0.8), int(cy)),
                QPoint(int(ox - s*0.6), int(cy + s)),
            ]
            from PyQt5.QtGui import QPolygon
            p.drawPolygon(QPolygon(pts))

        elif icon == 'pause':
            bw = m * 0.11
            bh = m * 0.38
            gap = m * 0.10
            p.drawRoundedRect(int(cx - gap - bw), int(cy - bh/2), int(bw), int(bh), 2, 2)
            p.drawRoundedRect(int(cx + gap),       int(cy - bh/2), int(bw), int(bh), 2, 2)

        elif icon == 'stop':
            s = m * 0.28
            p.drawRoundedRect(int(cx - s), int(cy - s), int(s*2), int(s*2), 3, 3)

        elif icon == 'prev':
            # |◀◀ — 세로선 + 삼각형 두 개
            lw = m * 0.08
            th = m * 0.30
            ox = cx + m * 0.06
            # 왼쪽 세로선
            p.drawRoundedRect(int(ox - th*1.4 - lw), int(cy - th*0.9),
                               int(lw), int(th*1.8), 2, 2)
            # 첫 번째 삼각형
            pts1 = [QPoint(int(ox - th*0.1), int(cy - th*0.9)),
                    QPoint(int(ox - th*1.2), int(cy)),
                    QPoint(int(ox - th*0.1), int(cy + th*0.9))]
            # 두 번째 삼각형
            pts2 = [QPoint(int(ox + th*0.9), int(cy - th*0.9)),
                    QPoint(int(ox - th*0.2), int(cy)),
                    QPoint(int(ox + th*0.9), int(cy + th*0.9))]
            from PyQt5.QtGui import QPolygon
            p.drawPolygon(QPolygon(pts1))
            p.drawPolygon(QPolygon(pts2))

        elif icon == 'next':
            # ▶▶| — 삼각형 두 개 + 세로선
            lw = m * 0.08
            th = m * 0.30
            ox = cx - m * 0.06
            pts1 = [QPoint(int(ox - th*0.9), int(cy - th*0.9)),
                    QPoint(int(ox + th*0.2), int(cy)),
                    QPoint(int(ox - th*0.9), int(cy + th*0.9))]
            pts2 = [QPoint(int(ox + th*0.1), int(cy - th*0.9)),
                    QPoint(int(ox + th*1.2), int(cy)),
                    QPoint(int(ox + th*0.1), int(cy + th*0.9))]
            from PyQt5.QtGui import QPolygon
            p.drawPolygon(QPolygon(pts1))
            p.drawPolygon(QPolygon(pts2))
            p.drawRoundedRect(int(ox + th*1.3), int(cy - th*0.9),
                               int(lw), int(th*1.8), 2, 2)

        elif icon == 'loading':
            # 점 세 개 애니메이션 대신 간단한 호
            pen2 = QPen(icon_color, 2.5, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen2)
            p.setBrush(Qt.NoBrush)
            r2 = int(m * 0.22)
            p.drawArc(int(cx-r2), int(cy-r2), r2*2, r2*2, 0, 270*16)

        p.end()


# ─────────────────────────────────────────────────────────────
# 셔플 / 반복 아이콘 버튼 (QPainter로 직접 그림)
# ─────────────────────────────────────────────────────────────
class IconButton(QWidget):
    """셔플·반복 토글 버튼 — QPainter로 직접 그림, TransportButton과 동일한 완성도."""
    clicked = pyqtSignal()

    def __init__(self, icon_type: str, parent=None):
        super().__init__(parent)
        # icon_type: 'shuffle' | 'repeat'
        self._icon    = icon_type
        self._active  = False
        self._mode    = 0        # repeat 전용: 0=off 1=one 2=all
        self._hovered = False
        self._pressed = False
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def setActive(self, val: bool):
        self._active = val
        self.update()

    def setMode(self, mode: int):
        self._mode = mode
        self.update()

    def event(self, e):
        if e.type() == QEvent.HoverEnter:
            self._hovered = True;  self.update()
        elif e.type() == QEvent.HoverLeave:
            self._hovered = False; self.update()
        return super().event(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pressed = True; self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pressed = False; self.update()
            if self.rect().contains(e.pos()):
                self.clicked.emit()

    def paintEvent(self, event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0

        # 활성 상태에 따른 색상 결정
        is_on = self._active or self._mode > 0
        if self._pressed:
            color = QColor(168, 136, 80)
        elif self._hovered and is_on:
            color = QColor(240, 210, 130)
        elif self._hovered:
            color = QColor(200, 200, 220)
        elif is_on:
            color = QColor(DARK['accent'])      # 골드
        else:
            color = QColor(DARK['text_muted'])  # 흐림

        # 호버 시 반투명 원 배경
        if self._hovered:
            p.setBrush(QColor(255, 255, 255, 18))
            p.setPen(Qt.NoPen)
            r = min(w, h) / 2 - 1
            p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        # 활성 표시 점 (하단 중앙)
        if is_on:
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            dot_r = 2.2
            p.drawEllipse(int(cx - dot_r), int(h - 5), int(dot_r * 2), int(dot_r * 2))

        pen = QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        if self._icon == 'shuffle':
            self._draw_shuffle(p, w, h, color)
        elif self._icon == 'repeat':
            self._draw_repeat(p, w, h, color)

        p.end()

    # ── 공통 유틸 ─────────────────────────────────────
    @staticmethod
    def _filled_arrow(p, tip_x, tip_y, angle_deg, size=5):
        """채워진 삼각형 화살촉. angle_deg: 화살촉이 가리키는 방향(도)."""
        import math
        rad = math.radians(angle_deg)
        # 화살촉 끝 좌표
        ax, ay = tip_x, tip_y
        # 꼬리 방향
        bx = ax - math.cos(rad) * size
        by = ay - math.sin(rad) * size
        perp = math.radians(angle_deg + 90)
        half = size * 0.42
        pts = [
            QPoint(int(ax), int(ay)),
            QPoint(int(bx + math.cos(perp) * half), int(by + math.sin(perp) * half)),
            QPoint(int(bx - math.cos(perp) * half), int(by - math.sin(perp) * half)),
        ]
        from PyQt5.QtGui import QPolygon
        old_pen = p.pen()
        p.setPen(Qt.NoPen)
        p.setBrush(old_pen.color())
        p.drawPolygon(QPolygon(pts))
        p.setBrush(Qt.NoBrush)
        p.setPen(old_pen)

    # ── 셔플 아이콘 ────────────────────────────────────
    def _draw_shuffle(self, p, w, h, color):
        """Spotify 스타일 셔플: 두 경로가 교차, 각 끝에 채워진 화살촉."""
        import math
        mx, my = w * 0.14, h * 0.20
        # 좌측 끝 두 점
        lx = mx
        ly1 = h * 0.30          # 위쪽 시작 (→ 우하)
        ly2 = h * 0.70          # 아래쪽 시작 (→ 우상)
        # 우측 끝 두 점
        rx = w - mx
        ry1 = h * 0.30          # 위쪽 끝 (← 좌하에서 옴)
        ry2 = h * 0.70          # 아래쪽 끝

        # 경로1: 좌하→우상 (아래쪽에서 위쪽으로 교차)
        path1 = QPainterPath()
        path1.moveTo(lx, ly2)
        path1.cubicTo(w * 0.38, ly2, w * 0.62, ry1, rx, ry1)
        p.drawPath(path1)
        self._filled_arrow(p, rx, ry1, 0, 5)        # 오른쪽 방향

        # 경로2: 좌상→우하 (위쪽에서 아래쪽으로 교차)
        path2 = QPainterPath()
        path2.moveTo(lx, ly1)
        path2.cubicTo(w * 0.38, ly1, w * 0.62, ry2, rx, ry2)
        p.drawPath(path2)
        self._filled_arrow(p, rx, ry2, 0, 5)        # 오른쪽 방향

    # ── 반복 아이콘 ────────────────────────────────────
    def _draw_repeat(self, p, w, h, color):
        """둥근 직사각형 루프 + 방향 화살촉. mode==1 이면 중앙에 '1'."""
        import math
        mx, my = w * 0.15, h * 0.20
        r = min(w, h) * 0.16    # 모서리 반경

        lx, rx = mx,       w - mx
        ty, by = my + 1,   h - my - 5   # 아래를 약간 올려 점을 위한 공간 확보

        # QPainterPath로 둥근 사각형 반시계 방향으로 그리기
        path = QPainterPath()
        # 위쪽 선: 좌→우 (화살촉 방향은 오른쪽)
        path.moveTo(lx + r, ty)
        path.lineTo(rx - r, ty)
        path.arcTo(rx - r*2, ty, r*2, r*2, 90, -90)         # 우상 코너
        path.lineTo(rx, by - r)
        path.arcTo(rx - r*2, by - r*2, r*2, r*2, 0, -90)    # 우하 코너
        path.lineTo(lx + r, by)
        path.arcTo(lx, by - r*2, r*2, r*2, 270, -90)        # 좌하 코너
        path.lineTo(lx, ty + r)
        path.arcTo(lx, ty, r*2, r*2, 180, -90)              # 좌상 코너
        p.drawPath(path)

        # 위쪽 오른쪽 화살촉 (오른쪽을 향함, 즉 0도)
        # 화살촉 위치: 위쪽 선의 오른쪽 끝 근방
        arrow_x = rx - r * 0.5
        self._filled_arrow(p, arrow_x, ty, 0, 4.5)

        # 아래쪽 왼쪽 화살촉 (왼쪽을 향함, 즉 180도)
        arrow_x2 = lx + r * 0.5
        self._filled_arrow(p, arrow_x2, by, 180, 4.5)

        # mode == 1: 중앙에 "1" 표시
        if self._mode == 1:
            old_pen = p.pen()
            p.setPen(QPen(color))
            font = QFont("SF Pro Display", 7, QFont.Bold)
            font.setLetterSpacing(QFont.AbsoluteSpacing, 0)
            p.setFont(font)
            rect = self.rect().adjusted(0, 1, 0, -5)
            p.drawText(rect, Qt.AlignCenter, "1")
            p.setPen(old_pen)


# 스펙트럼 시각화 위젯 (간단한 VU 미터)
# ─────────────────────────────────────────────────────────────
class VUMeter(QWidget):
    """주파수 반응형 VU 미터 — 저주파(따뜻한) → 고주파(차가운) 색상"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(140)
        self.levels = [0.0, 0.0]       # L, R 전체 레벨
        self.freq_levels = [0.0] * 16  # 주파수 대역별 레벨 (저→고)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._decay)
        self._timer.start(40)

    def set_level(self, left: float, right: float):
        self.levels = [min(1.0, left), min(1.0, right)]
        self.update()

    def set_freq_levels(self, band_levels: list):
        """8개 주파수 대역 레벨 업데이트"""
        self.freq_levels = [min(1.0, v) for v in band_levels]
        self.update()

    def _decay(self):
        self.levels = [max(0.0, l - 0.02) for l in self.levels]
        self.freq_levels = [max(0.0, v - 0.015) for v in self.freq_levels]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # ── 상단: L/R 세그먼트 바 ──
        bar_h = 14
        seg_w = 4    # 세그먼트 너비
        seg_gap = 1  # 세그먼트 간격
        lx = 22      # 바 시작 x
        bar_area = w - lx - 4
        n_segs = bar_area // (seg_w + seg_gap)

        labels = ['L', 'R']
        for i, (level, label) in enumerate(zip(self.levels, labels)):
            y = i * (bar_h + 5)
            # 라벨
            p.setPen(QColor(140, 140, 160))
            p.setFont(QFont('Arial', 8))
            p.drawText(0, y, 18, bar_h, Qt.AlignCenter, label)
            # 세그먼트 그리기
            filled = int(n_segs * level)
            for s in range(n_segs):
                sx = lx + s * (seg_w + seg_gap)
                t = s / max(n_segs - 1, 1)   # 0.0 ~ 1.0
                if s < filled:
                    # 활성: 낮은 쪽 밝은 흰색 → 높은 쪽 노랑 → 빨강
                    if t < 0.75:
                        r, g, b = 220, 220, 220
                    elif t < 0.9:
                        r, g, b = 255, 200, 0
                    else:
                        r, g, b = 255, 60, 0
                    p.fillRect(sx, y + 1, seg_w, bar_h - 2, QColor(r, g, b))
                else:
                    # 비활성: 매우 어두운 색
                    p.fillRect(sx, y + 1, seg_w, bar_h - 2, QColor(30, 30, 40))

        # ── 하단: 주파수 대역별 막대 (16밴드) ──
        n_bands = len(self.freq_levels)
        band_y  = bar_h * 2 + 18
        band_area_w = w - 24
        slot_w = band_area_w // n_bands
        bw = max(4, slot_w - 3)   # 막대 너비, 3px 간격

        # 16색 그라데이션: 저주파 황금/주황 → 중음 녹색/청록 → 고주파 파랑/보라
        BAND_COLORS = [
            QColor(255, 180,  40),   #  0  sub-bass    황금
            QColor(255, 150,  30),   #  1              주황
            QColor(255, 120,  20),   #  2  bass        딥오렌지
            QColor(255,  90,  40),   #  3              코랄
            QColor(220, 180,  60),   #  4  low-mid     올리브골드
            QColor(160, 210,  60),   #  5              라임
            QColor( 80, 220,  80),   #  6  mid         그린
            QColor( 40, 210, 140),   #  7              에메랄드
            QColor( 40, 200, 180),   #  8  upper-mid   청록
            QColor( 40, 180, 220),   #  9              스카이
            QColor( 60, 150, 255),   # 10  presence    블루
            QColor( 80, 120, 255),   # 11              코발트
            QColor(100,  90, 255),   # 12  brilliance  인디고
            QColor(140,  70, 255),   # 13              바이올렛
            QColor(180,  60, 240),   # 14  air         퍼플
            QColor(220,  50, 200),   # 15              마젠타
        ]

        max_bh = h - band_y - 4
        for j, lv in enumerate(self.freq_levels):
            if j >= len(BAND_COLORS):
                break
            color  = BAND_COLORS[j]
            bx     = 12 + j * slot_w
            filled_h = int(max_bh * lv)

            # 어두운 배경 트랙
            p.fillRect(bx, band_y, bw, max_bh, QColor(22, 22, 32))

            if filled_h > 0:
                # 하단 → 상단 그라데이션 (밝기 변화)
                grad = QLinearGradient(0, band_y + max_bh, 0, band_y + max_bh - filled_h)
                grad.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 80))
                grad.setColorAt(0.6, QColor(color.red(), color.green(), color.blue(), 200))
                grad.setColorAt(1.0, QColor(min(255, color.red()+40),
                                            min(255, color.green()+40),
                                            min(255, color.blue()+40), 255))
                p.fillRect(bx, band_y + max_bh - filled_h, bw, filled_h, QBrush(grad))

                # 상단 하이라이트 (1~2px 밝은 선)
                p.fillRect(bx, band_y + max_bh - filled_h, bw, 2,
                           QColor(255, 255, 255, 120))




# ─────────────────────────────────────────────────────────────
# 플레이리스트 아이템
# ─────────────────────────────────────────────────────────────
class TrackItem:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.title = ''
        self.artist = ''
        self.album = ''
        self.duration = 0.0
        self.format = Path(filepath).suffix.upper().lstrip('.')
        self.is_dsd = Path(filepath).suffix.lower() in ('.dsf', '.dff')
        self._sacd_track_info: Optional[dict] = None  # SACD ISO 트랙 정보 (None = 일반 파일)
        # ISO 파일은 mutagen 파싱 불필요 (트랙 정보는 sacd_decoder에서 처리)
        if filepath.lower().endswith('.iso'):
            self.title = Path(filepath).stem
            self.format = 'SACD'
        else:
            self._load_quick_meta()

    def _load_quick_meta(self):
        """빠른 메타데이터 로드 (재생 없이)"""
        name = Path(self.filepath).stem
        self.title = name
        ext = Path(self.filepath).suffix.lower()
        try:
            if ext == '.dsf':
                # mutagen DSF: ID3 태그 + info.length (sample_count / sample_rate)
                from mutagen.dsf import DSF as _DSF
                tags = _DSF(self.filepath)
                self.duration = tags.info.length
                if tags.tags:
                    t = tags.tags.get('TIT2')
                    a = tags.tags.get('TPE1')
                    al = tags.tags.get('TALB')
                    if t:  self.title  = str(t)  or name
                    if a:  self.artist = str(a)
                    if al: self.album  = str(al)
            elif ext == '.dff':
                # mutagen DSDIFF: info.length 로 duration 읽기
                from mutagen.dsdiff import DSDIFF as _DSDIFF
                tags = _DSDIFF(self.filepath)
                self.duration = tags.info.length
            else:
                from mutagen import File as MutagenFile
                tags = MutagenFile(self.filepath, easy=True)
                if tags:
                    self.title  = str(tags.get('title',  [name])[0]) or name
                    self.artist = str(tags.get('artist', [''])[0])
                    self.album  = str(tags.get('album',  [''])[0])
                    if hasattr(tags, 'info') and hasattr(tags.info, 'length'):
                        self.duration = tags.info.length
        except Exception:
            pass
        # WAV 전용 폴백: mutagen이 duration을 못 읽으면 내장 wave 모듈 사용
        # (Windows에서 일부 WAV 파일 또는 경로 인코딩 문제로 mutagen 실패 시)
        if ext == '.wav' and self.duration <= 0:
            try:
                import wave as _wave
                with _wave.open(self.filepath, 'rb') as wf:
                    frames = wf.getnframes()
                    rate   = wf.getframerate()
                    if rate > 0:
                        self.duration = frames / rate
            except Exception:
                pass

    def display_text(self) -> str:
        if self.artist:
            return f"{self.artist} — {self.title}"
        return self.title

    def duration_str(self) -> str:
        if self.duration <= 0:
            return '--:--'
        m, s = divmod(int(self.duration), 60)
        return f"{m:02d}:{s:02d}"

    def format_badge(self) -> str:
        if self.is_dsd:
            return f'[DSD]'
        return f'[{self.format}]'


# ─────────────────────────────────────────────────────────────
# 플레이리스트 아이템 커스텀 델리게이트
# ─────────────────────────────────────────────────────────────
# 컬럼 레이아웃 공유 상수 (PlaylistHeader ↔ PlaylistDelegate 동기화)
_PL_NUM_W   = 36
_PL_BADGE_W = 46
_PL_DUR_W   = 46
_PL_PAD_H   = 8


class PlaylistHeader(QWidget):
    """플레이리스트 컬럼 헤더 — 클릭 시 정렬 시그널 emit."""
    sort_requested = pyqtSignal(str, bool)   # (key, ascending)

    COLS = [
        ('#',      '#',       _PL_NUM_W,   Qt.AlignRight),
        ('format', '포맷',    _PL_BADGE_W, Qt.AlignCenter),
        ('title',  '제목 / 아티스트', -1,  Qt.AlignLeft),   # -1 = stretch
        ('dur',    '시간',    _PL_DUR_W,   Qt.AlignRight),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self._sort_key = ''
        self._asc = True
        self._playlist_ref = None  # PlaylistWidget 참조 (실시간 sb 폭 계산용)

    def set_playlist(self, playlist_widget):
        """PlaylistWidget을 연결해 스크롤바 폭을 실시간으로 읽음"""
        self._playlist_ref = playlist_widget

    def set_scrollbar_width(self, w: int):
        # 하위 호환 — 직접 호출 시에도 update
        self.update()

    def _get_sb_w(self) -> int:
        """현재 스크롤바가 표시 중이면 그 폭, 아니면 0"""
        if self._playlist_ref is None:
            return 0
        sb = self._playlist_ref.verticalScrollBar()
        if sb and sb.isVisible():
            return sb.width()
        return 0

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.update)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def set_sort(self, key: str, asc: bool):
        self._sort_key = key
        self._asc = asc
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        key, asc = self._hit_test(e.x())
        if key:
            self.sort_requested.emit(key, asc)

    def _hit_test(self, mx: int):
        """클릭 x 좌표 → (col_key, ascending)"""
        x = _PL_PAD_H
        w = self.width() - self._get_sb_w()
        for key, label, col_w, _ in self.COLS:
            if col_w == -1:
                col_w = w - x - _PL_PAD_H - _PL_DUR_W
            if x <= mx < x + col_w:
                if key in ('#', 'format', 'dur'):
                    return '', False   # 정렬 불가 컬럼
                asc = not self._asc if self._sort_key == key else True
                return key, asc
            x += col_w
            if key == 'format':
                x += 6   # PAD
        return '', False

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # delegate의 rect.right()는 뷰포트 너비(스크롤바 제외)와 같음
        # 헤더도 동일하게 스크롤바 너비만큼 뺀 영역을 사용
        w = self.width() - self._get_sb_w()
        h = self.height()

        # 배경
        p.fillRect(0, 0, self.width(), h, QColor(DARK['panel3']))
        # 하단 경계선
        p.setPen(QPen(QColor(DARK['border2']), 1))
        p.drawLine(0, h - 1, self.width(), h - 1)

        font = QFont('SF Pro Display', 10)
        p.setFont(font)

        # 시간 컬럼: delegate의 dur_x = rect.right() - PAD_H - DUR_W
        # rect.right() = viewport width = w (스크롤바 제외)
        dur_x = w - _PL_PAD_H - _PL_DUR_W

        x = _PL_PAD_H
        for key, label, col_w, align in self.COLS:  # noqa
            is_active = (key == self._sort_key)
            color = QColor(DARK['accent']) if is_active else QColor(DARK['text_muted'])
            p.setPen(color)

            text = label
            if is_active:
                text += '  ▲' if self._asc else '  ▼'

            if key == 'dur':
                # delegate와 완전히 동일한 기준점
                rect = QRect(dur_x, 0, _PL_DUR_W, h - 1)
                p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, text)
            else:
                if col_w == -1:
                    col_w = dur_x - x - _PL_PAD_H
                rect = QRect(x, 0, col_w, h - 1)
                p.drawText(rect, align | Qt.AlignVCenter, text)
                x += col_w
                if key == 'format':
                    x += 6
        p.end()


class PlaylistDelegate(QStyledItemDelegate):
    """트랙번호 · 포맷배지 · 제목/아티스트 · 시간 을 컬럼으로 배치하는 델리게이트."""

    ROW_H       = 48      # 아이템 높이
    NUM_W       = _PL_NUM_W
    BADGE_W     = _PL_BADGE_W
    DUR_W       = _PL_DUR_W
    PAD_H       = _PL_PAD_H
    PLAYING_ROW = -1      # 현재 재생 중인 row (외부에서 설정)

    def sizeHint(self, option, index):
        if index.data(Qt.UserRole) == 'separator':
            return QSize(max(option.rect.width(), 100), 26)
        return QSize(max(option.rect.width(), 100), self.ROW_H)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # ── 폴더 구분선 ────────────────────────────────────────
        if index.data(Qt.UserRole) == 'separator':
            rect = option.rect
            folder_name = index.data(Qt.DisplayRole) or ''
            # 배경
            painter.fillRect(rect, QColor(DARK['bg']))
            # 가로선
            line_y = rect.top() + rect.height() // 2
            painter.setPen(QPen(QColor(DARK['border']), 1))
            painter.drawLine(rect.left() + 8, line_y,
                             rect.left() + 18, line_y)
            # 폴더 이름
            font = QFont('SF Pro Display', 9)
            font.setWeight(QFont.Medium)
            painter.setFont(font)
            painter.setPen(QColor(DARK['text_dim']))
            fm = painter.fontMetrics()
            text_x = rect.left() + 24
            text_w = rect.width() - 32
            text = fm.elidedText(folder_name, Qt.ElideMiddle, text_w)
            painter.drawText(text_x, rect.top(),
                             text_w, rect.height(),
                             Qt.AlignLeft | Qt.AlignVCenter, text)
            # 오른쪽 선
            text_end = text_x + fm.horizontalAdvance(text) + 8
            if text_end < rect.right() - 8:
                painter.drawLine(text_end, line_y, rect.right() - 8, line_y)
            painter.restore()
            return

        row   = index.row()
        track = index.data(Qt.UserRole + 1)   # TrackItem
        is_playing  = (row == self.PLAYING_ROW)
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hover    = bool(option.state & QStyle.State_MouseOver)
        is_missing  = track is not None and not os.path.exists(track.filepath)

        rect = option.rect
        rw   = rect.width()

        # ── 배경 ────────────────────────────────────────────
        if is_selected:
            bg = QColor('#1e1a10')
        elif is_hover:
            bg = QColor(DARK['btn_hover'])
        else:
            bg = QColor(DARK['panel2'])
        painter.fillRect(rect, bg)

        # 하단 구분선
        painter.setPen(QPen(QColor(DARK['bg']), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        if track is None:
            painter.restore()
            return

        # ── 색상 결정 ────────────────────────────────────────
        if is_missing:
            main_color = QColor(DARK['text_muted'])
            sub_color  = QColor(DARK['text_muted'])
            badge_bg   = QColor('#3a2020')
            badge_fg   = QColor('#c06060')
        elif is_playing:
            main_color = QColor(DARK['accent'])
            sub_color  = QColor(DARK['accent']).lighter(140)
            badge_bg   = QColor('#2a2210')
            badge_fg   = QColor(DARK['accent'])
        elif track.is_dsd:
            main_color = QColor(DARK['dsd'])
            sub_color  = QColor(DARK['text_muted'])
            badge_bg   = QColor('#1a2030')
            badge_fg   = QColor(DARK['dsd'])
        else:
            main_color = QColor(DARK['text'])
            sub_color  = QColor(DARK['text_muted'])
            badge_bg   = QColor(DARK['panel3'])
            badge_fg   = QColor(DARK['text_dim'])

        x    = rect.left() + self.PAD_H
        cy   = rect.top() + rect.height() / 2
        PAD  = 6

        # ── ① 트랙 번호 / 재생 중 아이콘 ─────────────────────
        num_rect = QRect(x, rect.top(), self.NUM_W - PAD, rect.height())
        if is_playing:
            # 작은 음표 모양 대신 골드 ▶
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(DARK['accent']))
            s = 5
            pts = [
                QPoint(int(num_rect.right() - s * 2), int(cy - s)),
                QPoint(int(num_rect.right()),          int(cy)),
                QPoint(int(num_rect.right() - s * 2), int(cy + s)),
            ]
            from PyQt5.QtGui import QPolygon
            painter.drawPolygon(QPolygon(pts))
        else:
            painter.setPen(sub_color)
            font_num = QFont('SF Pro Display', 10)
            painter.setFont(font_num)
            painter.drawText(num_rect, Qt.AlignRight | Qt.AlignVCenter,
                             str(row + 1))

        x += self.NUM_W

        # ── ② 포맷 배지 ──────────────────────────────────────
        badge_text = track.format_badge()
        badge_rect = QRect(x, int(cy - 10), self.BADGE_W, 20)
        # 배지 배경
        painter.setPen(Qt.NoPen)
        painter.setBrush(badge_bg)
        painter.drawRoundedRect(badge_rect, 3, 3)
        # 배지 텍스트
        painter.setPen(badge_fg)
        font_badge = QFont('SF Mono', 8, QFont.Bold)
        painter.setFont(font_badge)
        painter.drawText(badge_rect, Qt.AlignCenter, badge_text)

        x += self.BADGE_W + PAD

        # ── ③ 시간 (오른쪽 정렬, 미리 계산) ─────────────────
        dur_x    = rect.right() - self.PAD_H - self.DUR_W
        dur_rect = QRect(dur_x, rect.top(), self.DUR_W, rect.height())
        painter.setPen(sub_color)
        font_dur = QFont('SF Mono', 10)
        painter.setFont(font_dur)
        painter.drawText(dur_rect, Qt.AlignRight | Qt.AlignVCenter,
                         track.duration_str())

        # ── ④ 제목 + 아티스트 (남은 공간) ────────────────────
        text_w = dur_x - x - PAD
        text_rect = QRect(x, rect.top(), text_w, rect.height())

        if track.artist:
            # 두 줄: 제목(위) + 아티스트(아래)
            title_rect  = QRect(text_rect.left(), rect.top() + 4,
                                text_rect.width(), 22)
            artist_rect = QRect(text_rect.left(), rect.top() + 26,
                                text_rect.width(), 16)

            painter.setPen(main_color if not is_missing else sub_color)
            font_title = QFont('SF Pro Display', 12)
            if is_playing:
                font_title.setWeight(QFont.DemiBold)
            painter.setFont(font_title)
            title_text = painter.fontMetrics().elidedText(
                track.title, Qt.ElideRight, title_rect.width())
            painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title_text)

            painter.setPen(sub_color)
            font_artist = QFont('SF Pro Display', 10)
            painter.setFont(font_artist)
            artist_text = painter.fontMetrics().elidedText(
                track.artist, Qt.ElideRight, artist_rect.width())
            painter.drawText(artist_rect, Qt.AlignLeft | Qt.AlignVCenter, artist_text)
        else:
            # 단일 행: 파일명만
            painter.setPen(main_color if not is_missing else sub_color)
            font_title = QFont('SF Pro Display', 12)
            painter.setFont(font_title)
            title_text = painter.fontMetrics().elidedText(
                track.title, Qt.ElideRight, text_rect.width())
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, title_text)

        painter.restore()


# ─────────────────────────────────────────────────────────────
# 드래그앤드롭 지원 플레이리스트 위젯
# ─────────────────────────────────────────────────────────────
class PlaylistWidget(QListWidget):
    files_dropped = pyqtSignal(list)           # 개별 파일 드롭 (구분선 없음)
    folder_dropped = pyqtSignal(str, list)     # (폴더명, 파일목록) — 구분선 포함
    remove_requested = pyqtSignal(int)         # row 번호
    clear_requested = pyqtSignal()
    row_moved = pyqtSignal(int, int)           # from_row, to_row

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)  # 외부 파일 드롭 허용
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._drop_hint_widget = None  # 오버레이 참조
        # 커스텀 델리게이트 적용
        self._delegate = PlaylistDelegate(self)
        self.setItemDelegate(self._delegate)
        self.setMouseTracking(True)  # 호버 State_MouseOver 활성화
        self.setUniformItemSizes(True)

    def set_playing_row(self, row: int):
        """현재 재생 중인 행 번호를 델리게이트에 전달하고 전체 갱신."""
        self._delegate.PLAYING_ROW = row
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._drop_hint_widget is not None:
            self._drop_hint_widget.setGeometry(0, 0, self.width(), self.height())

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)
            # 드래그 중 상하단 경계에서 자동 스크롤
            pos_y = event.pos().y()
            margin = 40
            vbar = self.verticalScrollBar()
            if pos_y < margin:
                # 상단 근처: 위로 스크롤 (경계에 가까울수록 빠르게)
                speed = max(5, int((margin - pos_y) * 0.8))
                vbar.setValue(vbar.value() - speed)
            elif pos_y > self.height() - margin:
                # 하단 근처: 아래로 스크롤
                speed = max(5, int((pos_y - (self.height() - margin)) * 0.8))
                vbar.setValue(vbar.value() + speed)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            # 외부 드롭: 폴더와 개별 파일을 분리 처리
            loose_files = []   # 폴더 없이 직접 드롭된 파일들
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if os.path.isdir(path):
                    folder_files = self._collect_from_dir(path)
                    if folder_files:
                        # 폴더 단위로 별도 시그널 → player_window에서 구분선 삽입
                        self.folder_dropped.emit(os.path.basename(path), folder_files)
                elif self._is_audio(path):
                    loose_files.append(path)
            if loose_files:
                self.files_dropped.emit(loose_files)
            event.acceptProposedAction()
        else:
            # 내부 드래그 — Copy 대신 Move로 처리
            source_row = self.currentRow()
            if source_row < 0:
                event.ignore()
                return
            # 구분선(separator)은 드래그 불가
            if self.item(source_row) and \
               self.item(source_row).data(Qt.UserRole) == 'separator':
                event.ignore()
                return

            target_item = self.itemAt(event.pos())
            if target_item is not None:
                target_row = self.row(target_item)
                # 구분선 위로 드롭 시 그 아래로 이동
                if target_item.data(Qt.UserRole) == 'separator':
                    target_row += 1
            else:
                target_row = self.count()

            if source_row == target_row:
                event.ignore()
                return

            # 아이템과 데이터 보존하여 이동
            item = self.takeItem(source_row)
            insert_row = target_row if target_row < source_row else target_row - 1
            self.insertItem(insert_row, item)
            self.setCurrentRow(insert_row)
            self.row_moved.emit(source_row, insert_row)
            event.acceptProposedAction()

    def _collect_from_dir(self, dirpath: str) -> list:
        """폴더에서 지원 오디오 파일 재귀 수집 (macOS 숨김 파일 제외)"""
        files = []
        exts = AudioEngine.SUPPORTED_FORMATS
        for root, dirs, filenames in os.walk(dirpath):
            # 숨김 폴더 제외
            dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
            for fname in sorted(filenames):
                # macOS 리소스 포크(._로 시작) 및 숨김 파일 제외
                if fname.startswith('.') or fname.startswith('._'):
                    continue
                if Path(fname).suffix.lower() in exts:
                    files.append(os.path.join(root, fname))
        return files

    def _is_audio(self, path: str) -> bool:
        fname = os.path.basename(path)
        if fname.startswith('.') or fname.startswith('._'):
            return False
        return Path(path).suffix.lower() in AudioEngine.SUPPORTED_FORMATS

    def _context_menu(self, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK['panel']};
                color: {DARK['text']};
                border: 1px solid {DARK['border']};
                border-radius: 4px;
            }}
            QMenu::item:selected {{ background-color: {DARK['btn_active']}; }}
        """)
        item = self.itemAt(pos)
        if item:
            row = self.row(item)
            remove_act = QAction("이 트랙 제거", self)
            remove_act.triggered.connect(lambda: self.remove_requested.emit(row))
            menu.addAction(remove_act)
        clear_act = QAction("플레이리스트 전체 지우기", self)
        clear_act.triggered.connect(self.clear_requested.emit)
        menu.addAction(clear_act)
        menu.exec_(self.mapToGlobal(pos))


# ─────────────────────────────────────────────────────────────
# 메인 윈도우
# ─────────────────────────────────────────────────────────────
