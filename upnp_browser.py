"""
UPnP/DLNA Browser
=================
로컬 네트워크의 UPnP 미디어 서버를 검색하고
음악 파일을 브라우징/스트리밍하는 모듈

사용 라이브러리: upnpclient (pip install upnpclient)
"""

import threading
import socket
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Callable

# ─────────────────────────────────────────────────────────────
# SSDP 상수
# ─────────────────────────────────────────────────────────────
SSDP_ADDR    = '239.255.255.250'
SSDP_PORT    = 1900
SSDP_ST_MS  = 'urn:schemas-upnp-org:service:ContentDirectory:1'
SSDP_MX     = 3   # 응답 대기 최대 초

SSDP_REQUEST = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    "MAN: \"ssdp:discover\"\r\n"
    f"MX: {SSDP_MX}\r\n"
    f"ST: {SSDP_ST_MS}\r\n"
    "\r\n"
)

# ContentDirectory Browse 액션 XML 템플릿
BROWSE_SOAP = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <ObjectID>{object_id}</ObjectID>
      <BrowseFlag>{browse_flag}</BrowseFlag>
      <Filter>*</Filter>
      <StartingIndex>{start}</StartingIndex>
      <RequestedCount>{count}</RequestedCount>
      <SortCriteria></SortCriteria>
    </u:Browse>
  </s:Body>
</s:Envelope>"""

# DIDL-Lite 네임스페이스
NS = {
    'didl':  'urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/',
    'dc':    'http://purl.org/dc/elements/1.1/',
    'upnp':  'urn:schemas-upnp-org:metadata-1-0/upnp/',
    'r':     'urn:schemas-rinconnetworks-com:metadata-1-0/',
}

# 오디오 MIME 타입
AUDIO_MIMES = {
    'audio/flac', 'audio/x-flac',
    'audio/mpeg', 'audio/mp3',
    'audio/wav',  'audio/x-wav',
    'audio/aiff', 'audio/x-aiff',
    'audio/aac',  'audio/mp4',
    'audio/ogg',  'audio/vorbis',
    'audio/dsf',  'audio/dff',
    'audio/x-dsd',
}


# ─────────────────────────────────────────────────────────────
# SSDP 검색
# ─────────────────────────────────────────────────────────────
def _ssdp_discover(timeout: float = 4.0) -> List[str]:
    """SSDP M-SEARCH로 ContentDirectory 서비스 URL 목록 반환"""
    locations = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)
        sock.sendto(SSDP_REQUEST.encode(), (SSDP_ADDR, SSDP_PORT))
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                resp = data.decode('utf-8', errors='ignore')
                for line in resp.splitlines():
                    if line.upper().startswith('LOCATION:'):
                        loc = line.split(':', 1)[1].strip()
                        locations.add(loc)
            except socket.timeout:
                break
        sock.close()
    except Exception as e:
        print(f"[UPnP] SSDP error: {e}")
    return list(locations)


# ─────────────────────────────────────────────────────────────
# 디바이스 설명 파싱
# ─────────────────────────────────────────────────────────────
def _parse_device_description(location: str) -> Optional[Dict]:
    """
    UPnP 디바이스 설명 XML에서 ContentDirectory 컨트롤 URL 추출
    반환: {name, control_url, location}
    """
    try:
        req = urllib.request.Request(location, headers={'User-Agent': 'HiFiPlayer/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        ns_dev = {'d': 'urn:schemas-upnp-org:device-1-0'}

        # 기기 이름
        name_el = root.find('.//d:friendlyName', ns_dev)
        name = name_el.text if name_el is not None else 'Unknown Device'

        # ContentDirectory 서비스 컨트롤 URL
        ctrl_url = None
        base_url = location.rsplit('/', 1)[0]
        for svc in root.findall('.//d:service', ns_dev):
            stype = svc.find('d:serviceType', ns_dev)
            if stype is not None and 'ContentDirectory' in (stype.text or ''):
                cu = svc.find('d:controlURL', ns_dev)
                if cu is not None and cu.text:
                    ctrl = cu.text.strip()
                    if ctrl.startswith('http'):
                        ctrl_url = ctrl
                    else:
                        # 상대 경로 → 절대 경로
                        base = '/'.join(location.split('/')[:3])
                        ctrl_url = base + ('/' if not ctrl.startswith('/') else '') + ctrl
                break

        if ctrl_url is None:
            return None

        return {'name': name, 'control_url': ctrl_url, 'location': location}
    except Exception as e:
        print(f"[UPnP] parse_device error ({location}): {e}")
        return None


# ─────────────────────────────────────────────────────────────
# ContentDirectory Browse
# ─────────────────────────────────────────────────────────────
def _browse(control_url: str, object_id: str = '0',
            browse_flag: str = 'BrowseDirectChildren',
            start: int = 0, count: int = 200) -> List[Dict]:
    """
    ContentDirectory Browse 액션 호출
    반환: [{id, title, type('container'|'item'), url, mime, duration, artist, album}]
    """
    soap_body = BROWSE_SOAP.format(
        object_id=object_id,
        browse_flag=browse_flag,
        start=start,
        count=count,
    )
    headers = {
        'Content-Type':  'text/xml; charset="utf-8"',
        'SOAPAction':    '"urn:schemas-upnp-org:service:ContentDirectory:1#Browse"',
        'User-Agent':    'HiFiPlayer/1.0',
    }
    try:
        req = urllib.request.Request(
            control_url,
            data=soap_body.encode('utf-8'),
            headers=headers,
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"[UPnP] Browse error: {e}")
        return []

    return _parse_didl(xml_data)


def _parse_didl(xml_data: bytes) -> List[Dict]:
    """DIDL-Lite XML → 아이템 목록"""
    items = []
    try:
        root = ET.fromstring(xml_data)
        # SOAP 응답에서 Result 추출
        result_el = root.find('.//{urn:schemas-upnp-org:service:ContentDirectory:1}Result')
        if result_el is None:
            # 네임스페이스 없이 시도
            for el in root.iter():
                if el.tag.endswith('Result'):
                    result_el = el
                    break
        if result_el is None or not result_el.text:
            return []

        didl = ET.fromstring(result_el.text)

        # 컨테이너(폴더)
        for container in didl.findall('{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}container'):
            cid   = container.get('id', '')
            title_el = container.find('{http://purl.org/dc/elements/1.1/}title')
            title = title_el.text if title_el is not None else cid
            items.append({
                'id':       cid,
                'title':    title,
                'type':     'container',
                'url':      '',
                'mime':     '',
                'duration': 0,
                'artist':   '',
                'album':    '',
            })

        # 아이템(파일)
        for item in didl.findall('{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}item'):
            iid   = item.get('id', '')
            title_el  = item.find('{http://purl.org/dc/elements/1.1/}title')
            artist_el = item.find('{urn:schemas-upnp-org:metadata-1-0/upnp/}artist')
            album_el  = item.find('{urn:schemas-upnp-org:metadata-1-0/upnp/}album')
            title  = title_el.text  if title_el  is not None else iid
            artist = artist_el.text if artist_el is not None else ''
            album  = album_el.text  if album_el  is not None else ''

            # res 요소에서 URL, MIME, 재생시간 추출
            url, mime, duration = '', '', 0
            for res in item.findall('{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}res'):
                m = res.get('protocolInfo', '')
                # protocolInfo = "http-get:*:audio/flac:*"
                parts = m.split(':')
                if len(parts) >= 3:
                    mime_candidate = parts[2]
                    if mime_candidate in AUDIO_MIMES or mime_candidate.startswith('audio/'):
                        url  = res.text or ''
                        mime = mime_candidate
                        dur_str = res.get('duration', '')
                        if dur_str:
                            duration = _parse_duration(dur_str)
                        break

            if url:  # URL 있는 것만 추가
                items.append({
                    'id':       iid,
                    'title':    title,
                    'type':     'item',
                    'url':      url,
                    'mime':     mime,
                    'duration': duration,
                    'artist':   artist,
                    'album':    album,
                })
    except Exception as e:
        print(f"[UPnP] DIDL parse error: {e}")
    return items


def _parse_duration(s: str) -> float:
    """'H:MM:SS.mmm' → 초"""
    try:
        parts = s.strip().split(':')
        if len(parts) == 3:
            h, m, sec = parts
            return int(h) * 3600 + int(m) * 60 + float(sec)
        elif len(parts) == 2:
            m, sec = parts
            return int(m) * 60 + float(sec)
        return float(s)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────
class UPnPBrowser:
    """UPnP/DLNA 미디어 서버 검색 및 브라우징"""

    def __init__(self):
        self._devices: List[Dict] = []   # [{name, control_url, location}]
        self._lock = threading.Lock()

    # ── 디바이스 검색 ──────────────────────────────────────
    def discover_async(self, on_found: Callable[[List[Dict]], None],
                       timeout: float = 4.0):
        """
        비동기 디바이스 검색
        on_found(devices: List[Dict]) — 검색 완료 시 호출
        """
        def _worker():
            locations = _ssdp_discover(timeout)
            devices = []
            for loc in locations:
                info = _parse_device_description(loc)
                if info:
                    devices.append(info)
            with self._lock:
                self._devices = devices
            on_found(devices)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    def discover(self, timeout: float = 4.0) -> List[Dict]:
        """동기 디바이스 검색"""
        locations = _ssdp_discover(timeout)
        devices = []
        for loc in locations:
            info = _parse_device_description(loc)
            if info:
                devices.append(info)
        with self._lock:
            self._devices = devices
        return devices

    # ── 브라우징 ───────────────────────────────────────────
    def browse(self, device: Dict, object_id: str = '0') -> List[Dict]:
        """
        폴더/파일 목록 반환
        device: discover()가 반환한 디바이스 dict
        object_id: '0' = 루트
        반환: [{id, title, type, url, mime, duration, artist, album}]
        """
        return _browse(device['control_url'], object_id)

    def browse_music_root(self, device: Dict) -> List[Dict]:
        """
        Music 폴더 자동 탐색 (루트 → 'Music' 컨테이너)
        없으면 루트 반환
        """
        root_items = _browse(device['control_url'], '0')
        for item in root_items:
            if item['type'] == 'container' and 'music' in item['title'].lower():
                return _browse(device['control_url'], item['id'])
        return root_items

    @property
    def devices(self) -> List[Dict]:
        with self._lock:
            return list(self._devices)


# ─────────────────────────────────────────────────────────────
# PyQt5 UI 위젯
# ─────────────────────────────────────────────────────────────
try:
    from PyQt5.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
        QPushButton, QLabel, QSplitter, QWidget, QSizePolicy, QComboBox,
        QProgressBar,
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
    from PyQt5.QtGui import QIcon

    class _DiscoverThread(QThread):
        found = pyqtSignal(list)

        def __init__(self, browser: UPnPBrowser):
            super().__init__()
            self._browser = browser

        def run(self):
            devs = self._browser.discover(timeout=4.0)
            self.found.emit(devs)

    class _BrowseThread(QThread):
        done = pyqtSignal(list)

        def __init__(self, browser: UPnPBrowser, device: Dict, obj_id: str):
            super().__init__()
            self._browser = browser
            self._device  = device
            self._obj_id  = obj_id

        def run(self):
            items = self._browser.browse(self._device, self._obj_id)
            self.done.emit(items)

    # DARK 팔레트 (player_window.py와 동일 색상)
    _BG    = '#0a0a0f'
    _PAN   = '#111118'
    _PAN2  = '#16161f'
    _ACC   = '#4a9eff'
    _TXT   = '#e8e8f0'
    _TMUT  = '#6060a0'
    _TDIM  = '#9090c0'
    _BRD   = '#1e1e2e'

    _DLG_STYLE = f"""
        QDialog, QWidget {{ background: {_BG}; color: {_TXT}; }}
        QListWidget {{
            background: {_PAN}; border: 1px solid {_BRD};
            border-radius: 6px; color: {_TXT}; font-size: 13px;
            outline: none;
        }}
        QListWidget::item:selected {{ background: {_ACC}; color: #fff; border-radius: 4px; }}
        QListWidget::item:hover    {{ background: {_PAN2}; }}
        QPushButton {{
            background: {_PAN2}; color: {_TDIM}; border: 1px solid {_BRD};
            border-radius: 5px; padding: 5px 14px; font-size: 12px;
        }}
        QPushButton:hover  {{ background: {_ACC}; color: #fff; }}
        QPushButton:disabled {{ color: {_TMUT}; }}
        QLabel {{ color: {_TDIM}; font-size: 12px; }}
        QComboBox {{
            background: {_PAN}; color: {_TXT}; border: 1px solid {_BRD};
            border-radius: 5px; padding: 4px 8px; font-size: 12px;
        }}
        QProgressBar {{
            background: {_PAN}; border: none; border-radius: 3px; height: 4px;
        }}
        QProgressBar::chunk {{ background: {_ACC}; border-radius: 3px; }}
    """

    class UPnPDialog(QDialog):
        """
        UPnP/DLNA 브라우저 다이얼로그
        track_selected(url, title, artist, album, duration) 시그널 emit
        """
        track_selected = pyqtSignal(str, str, str, str, float)  # url, title, artist, album, duration

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("UPnP / DLNA 미디어 서버")
            self.resize(720, 500)
            self.setStyleSheet(_DLG_STYLE)

            self._browser    = UPnPBrowser()
            self._devices:   List[Dict] = []
            self._cur_device: Optional[Dict] = None
            self._nav_stack: List[str] = []   # object_id 스택
            self._items:     List[Dict] = []

            self._build_ui()
            self._start_discover()

        def _build_ui(self):
            main = QVBoxLayout(self)
            main.setContentsMargins(16, 16, 16, 16)
            main.setSpacing(10)

            # 상단: 기기 선택 + 새로고침
            top = QHBoxLayout()
            self._lbl_status = QLabel("네트워크 검색 중...")
            self._combo_dev  = QComboBox()
            self._combo_dev.setMinimumWidth(260)
            self._combo_dev.currentIndexChanged.connect(self._on_device_changed)
            self._btn_refresh = QPushButton("🔄 새로고침")
            self._btn_refresh.clicked.connect(self._start_discover)
            top.addWidget(QLabel("미디어 서버:"))
            top.addWidget(self._combo_dev, 1)
            top.addWidget(self._btn_refresh)
            main.addLayout(top)

            # 진행 표시
            self._progress = QProgressBar()
            self._progress.setRange(0, 0)   # indeterminate
            self._progress.setFixedHeight(4)
            main.addWidget(self._progress)

            # 내비게이션 바
            nav = QHBoxLayout()
            self._btn_back = QPushButton("◀ 뒤로")
            self._btn_back.setEnabled(False)
            self._btn_back.clicked.connect(self._go_back)
            self._btn_home = QPushButton("⌂ 루트")
            self._btn_home.clicked.connect(self._go_home)
            self._lbl_path = QLabel("/")
            nav.addWidget(self._btn_back)
            nav.addWidget(self._btn_home)
            nav.addWidget(self._lbl_path, 1)
            main.addLayout(nav)

            # 파일 목록
            self._list = QListWidget()
            self._list.itemDoubleClicked.connect(self._on_item_dblclick)
            main.addWidget(self._list, 1)

            # 상태 레이블
            main.addWidget(self._lbl_status)

            # 하단 버튼
            btn_row = QHBoxLayout()
            self._btn_add = QPushButton("▶ 재생 목록에 추가")
            self._btn_add.setEnabled(False)
            self._btn_add.clicked.connect(self._on_add_clicked)
            btn_close = QPushButton("닫기")
            btn_close.clicked.connect(self.close)
            btn_row.addWidget(self._btn_add)
            btn_row.addStretch()
            btn_row.addWidget(btn_close)
            main.addLayout(btn_row)

        # ── 검색 ──────────────────────────────────────────
        def _start_discover(self):
            self._progress.setVisible(True)
            self._combo_dev.setEnabled(False)
            self._btn_refresh.setEnabled(False)
            self._lbl_status.setText("네트워크 검색 중...")
            self._list.clear()

            self._disc_thread = _DiscoverThread(self._browser)
            self._disc_thread.found.connect(self._on_discovered)
            self._disc_thread.start()

        def _on_discovered(self, devices: List[Dict]):
            self._devices = devices
            self._progress.setVisible(False)
            self._combo_dev.setEnabled(True)
            self._btn_refresh.setEnabled(True)
            self._combo_dev.clear()
            if devices:
                for d in devices:
                    self._combo_dev.addItem(d['name'])
                self._lbl_status.setText(f"{len(devices)}개 미디어 서버 발견")
            else:
                self._lbl_status.setText("미디어 서버를 찾지 못했습니다. NAS/PC가 켜져 있는지 확인하세요.")

        def _on_device_changed(self, idx: int):
            if 0 <= idx < len(self._devices):
                self._cur_device = self._devices[idx]
                self._nav_stack  = []
                self._go_home()

        # ── 브라우징 ──────────────────────────────────────
        def _browse(self, obj_id: str):
            if self._cur_device is None:
                return
            self._progress.setVisible(True)
            self._list.clear()
            self._btn_add.setEnabled(False)
            self._lbl_status.setText("로딩 중...")

            self._browse_thread = _BrowseThread(self._browser, self._cur_device, obj_id)
            self._browse_thread.done.connect(self._on_browse_done)
            self._browse_thread.start()

        def _on_browse_done(self, items: List[Dict]):
            self._items = items
            self._progress.setVisible(False)
            self._list.clear()
            self._btn_back.setEnabled(len(self._nav_stack) > 0)

            audio_count = 0
            for item in items:
                if item['type'] == 'container':
                    label = f"📁  {item['title']}"
                elif item['mime']:
                    ext = item['mime'].split('/')[-1].upper().replace('X-', '')
                    dur = _fmt_dur(item['duration'])
                    artist = f"  —  {item['artist']}" if item['artist'] else ''
                    label = f"🎵  {item['title']}{artist}  [{ext}] {dur}"
                    audio_count += 1
                else:
                    continue  # 비오디오 아이템 숨김
                wi = QListWidgetItem(label)
                wi.setData(Qt.UserRole, item)
                self._list.addItem(wi)

            self._lbl_status.setText(
                f"{len(items)}개 항목  (오디오: {audio_count}개)"
            )

        def _go_home(self):
            self._nav_stack = []
            self._lbl_path.setText("/")
            self._browse('0')

        def _go_back(self):
            if self._nav_stack:
                self._nav_stack.pop()
            obj_id = self._nav_stack[-1] if self._nav_stack else '0'
            path_depth = len(self._nav_stack)
            self._lbl_path.setText("/" + "/".join([f"L{i+1}" for i in range(path_depth)]))
            self._browse(obj_id)

        def _on_item_dblclick(self, wi: QListWidgetItem):
            item = wi.data(Qt.UserRole)
            if item is None:
                return
            if item['type'] == 'container':
                self._nav_stack.append(item['id'])
                depth = len(self._nav_stack)
                self._lbl_path.setText("/" + item['title'])
                self._browse(item['id'])
            else:
                # 오디오 파일 → 재생
                self._emit_track(item)

        def _on_add_clicked(self):
            items = self._list.selectedItems()
            for wi in items:
                item = wi.data(Qt.UserRole)
                if item and item['type'] == 'item' and item['url']:
                    self._emit_track(item)

        def _emit_track(self, item: Dict):
            self._btn_add.setEnabled(True)
            self.track_selected.emit(
                item['url'],
                item['title'],
                item['artist'],
                item['album'],
                item['duration'],
            )

    def _fmt_dur(sec: float) -> str:
        if sec <= 0:
            return ''
        m, s = divmod(int(sec), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

except ImportError:
    # PyQt5 없을 때 (CLI 환경) UI 클래스 생략
    class UPnPDialog:  # type: ignore
        def __init__(self, *a, **kw):
            raise RuntimeError("PyQt5 not installed")
