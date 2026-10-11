# WaveSentry

Windows용 RF 관측·드론 신호 탐지 앱입니다. HackRF One 수신, IQ 전처리, 로컬 모델 추론과 PySide6 GUI를 연결합니다. 고정 대역 분석, 2.4/5 GHz 안테나 탐색, 녹화 이미지 분석, 지도 기반 시나리오 데모를 지원합니다.

이 저장소에는 앱 소스, UI 자산, 테스트와 설치 도구를 제공합니다. **모델 가중치, 실측 IQ, 재생 샘플, 장치별 설정은 포함하지 않습니다.** 모델과 장치 없이 GUI와 시나리오 데모를 실행할 수 있습니다.

## 빠른 시작

Windows 11 x64와 Python 3.12 x64가 필요합니다. 쓰기 가능한 폴더에 복제한 뒤 PowerShell에서 실행합니다.

```powershell
git clone https://github.com/GabrielKimm/D4D_WaveSentry.git
cd D4D_WaveSentry
.\Setup.ps1
.\'Start Demo.cmd'
```

Python 경로를 직접 지정하려면 `Setup.ps1 -Python <python.exe 경로>`를 사용합니다. 위성지도는 `Setup.ps1 -Satellite`로 Cesium 자원을 설치한 뒤 사용할 수 있습니다. 설치하지 않거나 영상 연결에 실패하면 개략 지도로 전환합니다.

| 실행 파일 | 용도 | 별도 준비 |
|---|---|---|
| `Start WaveSentry.cmd` | 고정 대역 LIVE / 녹화 이미지 분석 | 모델, 추론 패키지, LIVE용 HackRF |
| `Start Antenna Survey.cmd` | 2.4/5 GHz 안테나 탐색 | 모델, 추론 패키지, HackRF |
| `Start Demo.cmd` | 지도·궤적·경보 시나리오 | 없음; 위성영상은 인터넷 필요 |

데모의 기체 위치·궤적·RF 점수·피아 정보는 합성 입력입니다. 실제 수신이나 모델 추론을 실행하지 않습니다. 위성영상은 배경 자료이며 실시간 촬영 영상이 아닙니다.

## 주요 기능

- LIVE: 2449.5 MHz 중심, 20 MS/s IQ 수신과 10 MHz 대상 채널 판정.
- SURVEY: 2400–2500 / 5150–5890 MHz 탐색, 후보 재방문, 시간 감쇠를 적용한 근거 누산.
- REPLAY: 별도로 제공한 640×640 PNG를 로컬 모델로 분석.
- DEMO: 세 가지 지역 시나리오, 연속 궤적, 방향만 수신·연결 소실 상태, 위성·개략 지도.
- NU-87: 확정 탐지와 연결된 USB 경보 LED, 응답 검증, 자동 재연결.
- 관측 기록 검색, IQ·모델 입력·판정 스냅샷 저장, 패널 배치 저장.

모델 점수와 누산 점수는 드론 존재 확률이 아닙니다. RF 영역 수는 드론 대수가 아니며, 관측 공백·입력 손실·오래된 근거를 판정과 함께 확인해야 합니다. 거리별 검출률과 일반적인 오탐률은 이 저장소의 자동 테스트로 검증하지 않습니다.

## 개발 및 검증

```powershell
.\Setup.ps1 -Dev
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\check_source.py
.\.venv\Scripts\python.exe tools\validate_demo.py
```

기본 테스트는 모델·측정 데이터·하드웨어·외부 영상 없이 실행됩니다. 모델 식별 검사는 가중치가 없으면 건너뜁니다. GitHub Actions는 Windows에서 의존성 설치, 소스 검사, 회귀 테스트, GUI 시작·종료를 확인합니다.

## 문서

- [설치와 장치·모델 설정](docs/SETUP.md)
- [운영 모드·판정·데이터 흐름](docs/ARCHITECTURE.md)
- [외부 구성 요소와 출처](THIRD_PARTY.md)

```text
main.py                 GUI / headless 진입점
d4d/                    수신, 전처리, 추론, 판정, GUI, NU-87 통신
assets/                 브랜드 SVG와 지도 화면 소스
vendor/iq_to_image.py    학습과 호환되는 IQ 전처리 기준 코드
tests/                  소스 및 GUI 회귀 검사
tools/                  모델 변환, 지도 자원 설치, 검증 도구
docs/                   설치·운영 문서
```

런타임에 생성되는 `runtime/`, `output/`, `settings.json`과 별도 모델·샘플은 Git에서 제외됩니다. 소스 검사 도구가 커밋 대상의 바이너리, 실측 데이터, 개인 PC 경로와 인증정보 패턴을 추가로 확인합니다.

## UNO Q 보드 실험 기록

[UNO Q 추론 파이프라인·사양·실측 및 GPU 검토](docs/UNO_Q_INFERENCE.md): 별도 보드에서 수행한 ClikaRT CPU 실행 결과와 향후 연동 계획입니다. 현재 Windows 앱의 실행 경로와 구분합니다.
