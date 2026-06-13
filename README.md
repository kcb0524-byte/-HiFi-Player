# HiFi Player

DSF/DFF(DSD), FLAC, WAV, AIFF, MP3 등 고음질 음원을 비트퍼펙트로 재생하는 Python 기반 플레이어.

## 주요 기능

| 기능 | 설명 |
|------|------|
| **DSD 지원** | DSF (Sony), DFF (DSDIFF) — DSD64/128/256/512 |
| **PCM 고해상도** | FLAC 24bit/192kHz, WAV, AIFF, APE, WavPack 등 |
| **비트퍼펙트 출력** | sounddevice로 OS 믹서 우회, 원본 샘플레이트 유지 |
| **외장 DAC 선택** | 시스템에 연결된 모든 출력 장치 선택 가능 |
| **파일 추가 방법** | 클릭(파일/폴더 선택) + 드래그앤드롭 (파일/폴더 모두 지원) |
| **메타데이터 표시** | 아티스트, 앨범, 샘플레이트, 비트 깊이, DSD 레이트 표시 |
| **볼륨 제어** | 소프트웨어 볼륨 (비트퍼펙트 원하면 100% 유지) |

## 지원 포맷

- **DSD**: `.dsf`, `.dff`
- **무손실**: `.flac`, `.wav`, `.aiff`, `.aif`, `.wv`, `.ape`, `.tta`
- **손실**: `.mp3`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wma`

## 설치 및 실행

### macOS
```bash
# 1. 설치
bash install_mac.sh

# 2. 실행
python3 main.py
```

### Windows
```bat
REM 1. install_windows.bat 더블클릭
REM 2. run.bat 더블클릭
```

### 수동 설치
```bash
pip install PyQt5 sounddevice soundfile mutagen numpy
python3 main.py
```

> macOS에서 sounddevice가 오류 날 경우: `brew install portaudio`

## DSD 재생 방식

DSD(Direct Stream Digital) 파일은 1비트 PDM 신호로, 일반 DAC에 직접 출력하려면 **DoP(DSD over PCM)** 또는 **PCM 변환**이 필요합니다.

이 플레이어는 **FIR 저역통과 필터 기반 PCM 변환**을 사용합니다:
- DSD 비트스트림 → 64x 데시메이션 → 44.1kHz / 88.2kHz PCM
- 20kHz 이상 초음파 노이즈 제거 (시그마-델타 노이즈 셰이핑)
- 16비트 이상 DAC에서 DSD의 다이나믹 레인지 유지

> **완전한 비트퍼펙트 DSD 재생**을 원하신다면 ASIO 드라이버를 지원하는 외장 DAC와 함께 DoP 모드를 지원하는 플레이어(HQPlayer, Audirvana 등)를 사용하시기 바랍니다.

## 외장 DAC 사용

1. DAC를 USB로 연결
2. 플레이어 우측 "출력 장치" 콤보박스에서 DAC 선택
3. "장치 새로고침" 버튼으로 새로 연결한 장치 인식

## 단축키

| 키 | 기능 |
|----|------|
| Space | 재생/일시정지 |
| ← → | 이전/다음 트랙 |
| ↑ ↓ | 볼륨 조절 |

## 파일 구조

```
hifi_player/
├── main.py          # PyQt5 UI 메인
├── audio_engine.py  # 오디오 재생 엔진
├── dsd_decoder.py   # DSF/DFF 디코더
├── requirements.txt
├── install_mac.sh
├── install_windows.bat
├── run.sh / run.bat
└── README.md
```
