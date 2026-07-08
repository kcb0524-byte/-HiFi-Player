"""
HiFi Player — 색상·스타일시트·EQ 프리셋 상수 모음
"""

# ─────────────────────────────────────────────────────────────
# 파라메트릭 EQ 프리셋
# 포맷: [(type, freq_hz, gain_db, q), ...]
# type: 'lowshelf' | 'peak' | 'highshelf'
# ─────────────────────────────────────────────────────────────
# 8밴드: LS 32Hz / 125 / 250 / 500 / 1k / 2k / 4k / HS 16kHz
_F = [
    ('lowshelf',   32, 0.7),
    ('peak',      125, 1.0),
    ('peak',      250, 1.0),
    ('peak',      500, 1.0),
    ('peak',     1000, 1.0),
    ('peak',     2000, 1.0),
    ('peak',     4000, 1.0),
    ('highshelf',16000, 0.7),
]

def _p(gains):
    return [(_F[i][0], _F[i][1], gains[i], _F[i][2]) for i in range(8)]

#                         32   125   250   500    1k    2k    4k   16k
EQ_PRESETS = {
    "Flat":         _p([ 0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0]),
    "Pop":          _p([ 1.5,  1.0, -0.5,  0.0,  2.0,  2.5,  2.0,  1.5]),
    "Rock":         _p([ 4.0,  3.0,  2.0, -0.5,  0.5,  2.0,  2.5,  2.5]),
    "Jazz":         _p([ 3.0,  2.5,  2.0, -1.0,  0.0,  1.0,  1.5, -0.5]),
    "Classical":    _p([ 2.0,  1.5,  1.0,  0.0,  0.5,  1.0,  1.0,  2.0]),
    "Vocal":        _p([-2.0, -1.5, -1.5,  3.5,  3.0,  2.5,  1.5,  1.5]),
    "R&B":          _p([ 4.0,  3.5,  1.5, -1.0,  1.0,  1.5,  2.0,  2.5]),
    "Electronic":   _p([ 5.0,  3.0,  0.5,  0.0,  1.5,  2.5,  3.0,  4.0]),
    "Acoustic":     _p([ 2.5,  1.5,  2.0,  1.5,  1.5,  1.0,  1.0,  1.5]),
    "Bass Boost":   _p([ 6.0,  5.0,  3.5,  0.0,  0.0,  0.0,  0.0,  0.0]),
    "Treble Boost": _p([ 0.0,  0.0,  0.0,  1.0,  2.0,  3.0,  4.0,  4.5]),
    "Loudness":     _p([ 5.0,  3.5,  1.5, -1.0,  0.5,  1.5,  2.0,  3.5]),
    "Custom":       _p([ 0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0]),
}

EQ_BAND_LABELS = ["Low\n32Hz", "125Hz", "250Hz", "500Hz",
                  "1kHz", "2kHz", "4kHz", "High\n16kHz"]


# ─────────────────────────────────────────────────────────────
# 색상 테마 (Roon 스타일 프리미엄 다크)
# ─────────────────────────────────────────────────────────────
DARK = {
    'bg':          '#050508',   # 순수 블랙에 가까운 극암
    'panel':       '#090910',   # 좌측 패널 — 더 짙게
    'panel2':      '#07070e',   # 우측/리스트 배경
    'panel3':      '#0f0f18',   # 카드/섹션 배경
    'border':      '#161624',   # 경계선
    'border2':     '#222232',   # 조금 더 강한 경계
    'accent':      '#b8913a',   # 짙은 골드 액센트
    'accent2':     '#d4a84e',   # 밝은 골드
    'accent_blue': '#3a8eee',   # 파란 액센트
    'text':        '#e8e8f0',   # 밝은 흰색
    'text_dim':    '#787898',   # 보조 텍스트
    'text_muted':  '#3a3a58',   # 흐린 텍스트
    'playing':     '#b8913a',   # 재생 중 = 골드
    'dsd':         '#d09020',   # DSD 오렌지
    'error':       '#ff4a4a',
    'slider_bg':   '#161624',
    'slider_fill': '#b8913a',   # 골드 슬라이더
    'btn':         '#0e0e16',
    'btn_hover':   '#161624',
    'btn_active':  '#1e1e30',
    'divider':     '#101020',
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {DARK['bg']};
    color: {DARK['text']};
    font-family: 'SF Pro Display', 'Helvetica Neue', 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QFrame#LeftPanel {{
    background-color: {DARK['panel']};
    border-right: 1px solid {DARK['border']};
}}
QFrame#RightPanel {{
    background-color: {DARK['bg']};
}}
QFrame#ArtCard {{
    background-color: {DARK['panel3']};
    border-radius: 12px;
}}
QFrame#InfoSection {{
    background-color: transparent;
}}
QFrame#ControlBar {{
    background-color: {DARK['panel']};
    border-top: 1px solid {DARK['border']};
}}
QFrame#HifiSection {{
    background-color: {DARK['panel3']};
    border: 1px solid {DARK['border']};
    border-radius: 10px;
}}
QFrame#EQSection {{
    background-color: {DARK['panel3']};
    border: 1px solid {DARK['border']};
    border-radius: 10px;
}}
QListWidget {{
    background-color: {DARK['panel2']};
    border: 1px solid {DARK['border']};
    border-radius: 8px;
    color: {DARK['text']};
    font-size: 13px;
    outline: none;
}}
QListWidget::item {{
    padding: 9px 12px;
    border-bottom: 1px solid {DARK['bg']};
}}
QListWidget::item:selected {{
    background-color: #1e1a10;
    color: {DARK['accent']};
}}
QListWidget::item:hover {{
    background-color: {DARK['btn_hover']};
}}
QPushButton {{
    background-color: {DARK['btn']};
    color: {DARK['text_dim']};
    border: 1px solid {DARK['border']};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {DARK['btn_hover']};
    color: {DARK['text']};
    border-color: {DARK['border2']};
}}
QPushButton:pressed {{
    background-color: {DARK['btn_active']};
}}
QPushButton#PlayBtn {{
    background-color: {DARK['accent']};
    color: #0a0a0f;
    border: none;
    border-radius: 26px;
    font-size: 22px;
    font-weight: bold;
    min-width: 52px;
    min-height: 52px;
    max-width: 52px;
    max-height: 52px;
}}
QPushButton#PlayBtn:hover {{
    background-color: {DARK['accent2']};
}}
QPushButton#PlayBtn:pressed {{
    background-color: #a08040;
}}
QPushButton#TransportBtn {{
    background-color: transparent;
    color: {DARK['text_dim']};
    border: none;
    border-radius: 20px;
    font-size: 18px;
    min-width: 40px;
    min-height: 40px;
    max-width: 40px;
    max-height: 40px;
}}
QPushButton#TransportBtn:hover {{
    background-color: {DARK['btn_hover']};
    color: {DARK['text']};
}}
QSlider::groove:horizontal {{
    height: 3px;
    background: {DARK['border2']};
    border-radius: 1px;
}}
QSlider::sub-page:horizontal {{
    background: {DARK['accent']};
    border-radius: 1px;
}}
QSlider::handle:horizontal {{
    background: {DARK['accent2']};
    border: none;
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{
    background: white;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}
QComboBox {{
    background-color: {DARK['btn']};
    color: {DARK['text_dim']};
    border: 1px solid {DARK['border']};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
}}
QComboBox:hover {{
    border-color: {DARK['border2']};
    color: {DARK['text']};
}}
QComboBox QAbstractItemView {{
    background-color: {DARK['panel3']};
    color: {DARK['text']};
    border: 1px solid {DARK['border2']};
    selection-background-color: {DARK['btn_active']};
    padding: 4px;
}}
QLabel {{
    color: {DARK['text']};
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 5px;
    border-radius: 2px;
}}
QScrollBar::handle:vertical {{
    background: {DARK['border2']};
    border-radius: 2px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {DARK['text_muted']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    height: 0px;
}}
QSplitter::handle {{
    background: {DARK['border']};
}}
"""


