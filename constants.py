"""
HiFi Player — 색상·스타일시트·EQ 프리셋 상수 모음
"""

APP_VERSION = "1.8.5"

# ─────────────────────────────────────────────────────────────
# 파라메트릭 EQ 프리셋
# 포맷: [(type, freq_hz, gain_db, q), ...]
# type: 'lowshelf' | 'peak' | 'highshelf'
# ─────────────────────────────────────────────────────────────
# 8밴드: Low Shelf 60Hz / 125Hz / 250Hz / 500Hz / 1kHz / 2kHz / 4kHz / High Shelf 12kHz
_F = [
    ('lowshelf',    60, 0.7),
    ('peak',       125, 1.0),
    ('peak',       250, 1.0),
    ('peak',       500, 1.0),
    ('peak',      1000, 1.0),
    ('peak',      2000, 1.0),
    ('peak',      4000, 1.0),
    ('highshelf', 12000, 0.7),
]

def _p(gains):
    return [(_F[i][0], _F[i][1], gains[i], _F[i][2]) for i in range(8)]

EQ_PRESETS = {
    "Flat":         _p([ 0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0]),
    "Pop":          _p([ 2.0,  1.5, -1.0,  0.0,  2.0,  2.5,  3.0,  2.0]),
    "Rock":         _p([ 4.0,  3.0,  2.0, -0.5, -1.0,  1.0,  2.5,  3.0]),
    "Jazz":         _p([ 3.0,  2.5,  2.0,  0.0, -1.5,  0.0,  1.5, -1.0]),
    "Classical":    _p([ 2.0,  1.5,  1.0,  0.0,  0.0,  1.0,  1.0,  2.5]),
    "Vocal":        _p([-2.0, -1.5, -1.5,  2.0,  3.5,  2.5,  2.0,  1.5]),
    "R&B":          _p([ 4.0,  3.5,  1.5, -0.5, -1.0,  1.5,  2.0,  2.5]),
    "Electronic":   _p([ 5.0,  3.0,  0.0, -1.0,  0.0,  2.0,  3.0,  4.0]),
    "Acoustic":     _p([ 2.5,  1.5,  2.0,  1.0,  1.5,  1.5,  1.0,  1.5]),
    "Bass Boost":   _p([ 6.0,  5.0,  3.0,  1.0,  0.0,  0.0,  0.0,  0.0]),
    "Treble Boost": _p([ 0.0,  0.0,  0.0,  0.0,  1.0,  2.5,  3.5,  5.0]),
    "Loudness":     _p([ 5.0,  3.5,  1.5,  0.0, -1.0,  0.5,  2.0,  4.0]),
    "Custom":       _p([ 0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0]),
}

EQ_BAND_LABELS = ["Low\n60Hz", "125Hz", "250Hz", "500Hz", "1kHz", "2kHz", "4kHz", "High\n12kHz"]


# ─────────────────────────────────────────────────────────────
# 색상 테마 시스템 — 앱 내에서 선택 가능 (HiFi Options > Theme)
# ─────────────────────────────────────────────────────────────
THEMES = {
    # 진짜 오렌지 — 배경까지 오렌지 톤의 리치 앰버 다크
    'Sunset Orange': {
        'bg': '#331a08', 'panel': '#3d2009', 'panel2': '#371d08', 'panel3': '#4a2a10',
        'border': '#66401c', 'border2': '#7d5226',
        'accent': '#ffa245', 'accent2': '#ffc06e', 'accent_blue': '#ffd166',
        'text': '#fff2e2', 'text_dim': '#e0b48a', 'text_muted': '#a37a4e',
        'playing': '#ffa245', 'dsd': '#ffd166', 'error': '#ff6b5c',
        'slider_bg': '#66401c', 'slider_fill': '#ffa245',
        'btn': '#452709', 'btn_hover': '#553112', 'btn_active': '#663d18',
        'divider': '#3a2008',
    },
    # 밝은 오렌지 라이트 — 화면 전체가 환한 오렌지 크림
    'Orange Light': {
        'bg': '#fff1e0', 'panel': '#ffe8cc', 'panel2': '#ffedd8', 'panel3': '#ffdfb8',
        'border': '#f0c894', 'border2': '#e0b070',
        'accent': '#f97316', 'accent2': '#fb923c', 'accent_blue': '#ea580c',
        'text': '#3a2410', 'text_dim': '#8a5a2e', 'text_muted': '#b98a58',
        'playing': '#ea580c', 'dsd': '#d97706', 'error': '#dc2626',
        'slider_bg': '#f0d0a8', 'slider_fill': '#f97316',
        'btn': '#ffe4c4', 'btn_hover': '#ffd9ae', 'btn_active': '#ffcf9c',
        'divider': '#f5d9b8',
    },
    # 오리지널 블랙+골드
    'Black Gold': {
        'bg': '#050508', 'panel': '#090910', 'panel2': '#07070e', 'panel3': '#0f0f18',
        'border': '#161624', 'border2': '#222232',
        'accent': '#b8913a', 'accent2': '#d4a84e', 'accent_blue': '#3a8eee',
        'text': '#e8e8f0', 'text_dim': '#787898', 'text_muted': '#3a3a58',
        'playing': '#b8913a', 'dsd': '#d09020', 'error': '#ff4a4a',
        'slider_bg': '#161624', 'slider_fill': '#b8913a',
        'btn': '#0e0e16', 'btn_hover': '#161624', 'btn_active': '#1e1e30',
        'divider': '#101020',
    },
    # 딥바이올렛 + 일렉트릭 블루
    'Violet Space': {
        'bg': '#0a0714', 'panel': '#0d0918', 'panel2': '#0b0813', 'panel3': '#141024',
        'border': '#241d3d', 'border2': '#332a52',
        'accent': '#8b5cf6', 'accent2': '#a78bfa', 'accent_blue': '#38bdf8',
        'text': '#ece9f8', 'text_dim': '#8d85b3', 'text_muted': '#4a4270',
        'playing': '#8b5cf6', 'dsd': '#38bdf8', 'error': '#ff4a6a',
        'slider_bg': '#241d3d', 'slider_fill': '#8b5cf6',
        'btn': '#120e20', 'btn_hover': '#1c1631', 'btn_active': '#261e42',
        'divider': '#151024',
    },
}

THEME_ORDER = ['Sunset Orange', 'Orange Light', 'Black Gold', 'Violet Space']
CURRENT_THEME = 'Sunset Orange'
DARK = dict(THEMES[CURRENT_THEME])


def hex_shade(h, f):
    """hex 색상을 f배 밝기로 (f<1 어둡게, f>1 밝게)"""
    h = h.lstrip('#')
    r = max(0, min(255, int(int(h[0:2], 16) * f)))
    g = max(0, min(255, int(int(h[2:4], 16) * f)))
    b = max(0, min(255, int(int(h[4:6], 16) * f)))
    return f'#{r:02x}{g:02x}{b:02x}'


# 저장된 테마 조기 로드 (UI 모듈 임포트 전에 DARK 확정)
def _load_saved_theme():
    global CURRENT_THEME
    try:
        import json as _json
        from pathlib import Path as _Path
        with open(_Path.home() / '.hifi_player_settings.json', encoding='utf-8') as _f:
            _t = _json.load(_f).get('theme')
        if _t in THEMES:
            CURRENT_THEME = _t
            DARK.clear()
            DARK.update(THEMES[_t])
    except Exception:
        pass

_load_saved_theme()

def build_stylesheet():
    _grad = (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, "
             f"stop:0 {DARK['accent2']}, stop:0.5 {DARK['accent']}, "
             f"stop:1 {hex_shade(DARK['accent'], 0.8)})")
    return f"""
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
    background-color: {DARK['btn_active']};
    color: {DARK['accent2']};
    border-left: 3px solid {DARK['accent']};
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
    background: {_grad};
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


STYLESHEET = build_stylesheet()



