# NCMP Spatial — 공간 음향 추가 버전

## 결론

기존 NCMP(Nikon Chinge HiFi Player)에 **공간 음향(Spatial Audio) 토글**이 추가된 버전입니다.
원본 소스(바탕화면 NCMP-Final)는 일절 수정하지 않았으며, 이 폴더(NCMP-Spatial)가 독립 작업본입니다.
앱 이름과 번들 ID가 달라 기존 앱과 나란히 설치·실행할 수 있습니다.

| 항목 | 기존 | Spatial 버전 |
|------|------|-------------|
| 앱 이름 | Nikon Chinge HiFi Player | **Nikon Chinge HiFi Player Spatial** |
| 번들 ID | com.twsemicon.hifi-player | com.twsemicon.hifi-player-spatial |
| 버전 | 1.0.0 | 1.1.0 |
| DMG | Nikon Chinge HiFi Player-1.0.0.dmg | Nikon Chinge HiFi Player Spatial-1.1.0.dmg |

## 빌드 방법 (맥에서)

`빌드하기(Spatial).command` 더블클릭 → Terminal이 열리며 자동 빌드 →
`dist/Nikon Chinge HiFi Player Spatial-1.1.0.dmg` 생성.

(또는 Terminal에서 `bash build_mac_spatial.sh`)

## 사용 방법

우측 HiFi Options 패널 → **Spatial Audio** 스위치.

- **OFF (기본)**: 기존과 완전히 동일한 신호 경로. 공간 음향 코드가 신호에 일절 개입하지 않음.
- **ON**: 크로스피드 바이노럴 렌더링. 헤드폰/이어폰 청취 시 소리가 머리 안이 아닌
  전방 스테이지(가상 스피커 ±30°)에서 나는 것처럼 들림. 재생 중 즉시 전환 가능.

모든 재생 가능 음원(FLAC/WAV/AIFF/MP3/DSD/SACD ISO/UPnP)에 동일하게 적용됩니다.
DSD도 PCM 변환 후 처리되므로 적용 대상입니다.

단, **Bit Perfect 모드와 DoP 모드에서는 적용되지 않습니다** — 두 모드는
"신호 무가공"이 존재 이유이므로 공간 음향과 양립할 수 없습니다.
(Bit Perfect ON 시 Spatial 토글이 자동 비활성화됩니다.)

## 음질에 대해

- OFF 시: 원본 경로 그대로 (열화 0)
- ON 시: 전 구간 float64 처리, 최종 출력 직전에만 float32 변환 (기존과 동일)
- 모노(중앙 정위) 성분의 전달함수가 이론적으로 정확히 1.0 —
  보컬/센터 이미지의 톤 변화 없음 (단위 테스트로 50Hz~18kHz 전 대역 검증)
- 클리핑 유발 없음 (이론 피크 게인 ≤ 1.0)
- 청크 경계 필터 상태 연속 — 클릭/틱 노이즈 없음
- 처리 부하: 10ms 청크당 약 55µs (실시간 대비 180배 여유)

## 변경된 파일

| 파일 | 변경 내용 |
|------|----------|
| `spatial_audio.py` | **신규** — SpatialProcessor (크로스피드 DSP) |
| `audio_engine.py` | spatial 플래그·setter 추가, 재생 제너레이터에 처리 단계 삽입 (EQ 뒤, 볼륨 앞) |
| `player_window.py` | Spatial Audio 토글 UI, 설정 저장/복원, Bit Perfect 연동 |
| `build_mac_spatial.sh` | **신규** — 새 앱 이름/번들ID/버전으로 빌드 |
| `빌드하기(Spatial).command` | **신규** — 더블클릭 빌드 |

## 기술 요약 (크로스피드 설계)

bs2b 계열의 위상 정합형 크로스피드:

```
lpL = LP₇₀₀Hz(L),  lpR = LP₇₀₀Hz(R)      ← 1차 Butterworth (head shadow)
out_L = (L − k·lpL) + k·lpR               ← k = r/(1+r), r = 10^(−4.5/20)
out_R = (R − k·lpR) + k·lpL
```

직접음 보상과 크로스피드가 동일한 필터를 공유하므로 모노 성분이 전 대역에서
불변이고, 명시적 지연 대신 필터 군지연(저역 약 220µs)이 자연스러운
양귀 시간차(ITD)를 만들어 상쇄 간섭(콤 필터링)이 원천적으로 없습니다.
