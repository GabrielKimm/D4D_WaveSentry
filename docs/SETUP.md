# 설치와 설정

## Python 환경

Windows 11 x64 / Python 3.12 x64를 사용합니다. 저장소는 설정과 로그를 자체 폴더에 기록하므로 사용자에게 쓰기 권한이 있는 위치에 둡니다. 가상환경은 PC마다 새로 생성합니다.

```powershell
.\Setup.ps1                         # GUI와 데모
.\Setup.ps1 -Dev                    # 테스트 도구 추가
.\Setup.ps1 -Inference              # OpenVINO, PyTorch, Ultralytics 추가
.\Setup.ps1 -Satellite              # 해시를 검증한 Cesium 자원 설치
```

스위치는 함께 사용할 수 있습니다. Python이 자동으로 검색되지 않으면 `-Python`으로 Python 3.12 실행 파일을 지정합니다. 모든 설치 경로는 `requirements-lock.txt`의 검증 환경 버전으로 제한합니다. 설치 뒤 `python -m pip check`로 의존성을 확인할 수 있습니다.

## 모델

가중치는 별도 전달 경로에서 준비합니다. 아래 중 하나를 사용합니다.

- 저장소의 `models/model_02a_picked.pt`에 복사.
- `D4D_MODEL_PATH` 환경 변수에 모델의 절대 경로 지정.

기준 SHA-256:

```text
06b998be1d8dd85389803ba5f1704c673ba38f3fcac15044e6bf54e5ea0b088f
```

```powershell
# 선택 사항: 저장소 밖에 보관한 모델 사용
$env:D4D_MODEL_PATH = 'D:\WaveSentryData\model_02a_picked.pt'
.\Setup.ps1 -Inference -OptimizeModel
```

모델 변환본은 원본 옆의 `<모델명>_openvino_model/`에 생성됩니다. 변환본의 `source.json`은 원본과 XML/BIN 파일의 해시를 기록합니다. 실행 시 원본·변환본을 확인하며 불일치하면 추론을 중단합니다. 변환본이 없으면 PyTorch CPU를 사용합니다. `AUTO`는 OpenVINO GPU를 우선 선택하고 초기화 실패 시 CPU로 전환합니다.

## HackRF One

LIVE/SURVEY에는 WinUSB 드라이버와 **libhackrf 2026.01.3**이 필요합니다. 수신 코드가 이 버전의 내부 구조를 사용하므로 다른 버전은 거부합니다. 사용 패키지의 정확한 버전, 배포 URL, SHA-256은 [`tools/hackrf-packages.json`](../tools/hackrf-packages.json)에 있습니다. DLL과 드라이버 바이너리는 저장소에 포함하지 않습니다.

호환되는 Windows x64 배포본에서 `hackrf-0.dll`, `libusb-1.0.dll`, `libwinpthread-1.dll`을 함께 준비합니다.

- 기본 위치: `runtime/hackrf/`
- 외부 설치 사용: `D4D_HACKRF_BIN`에 해당 DLL 폴더 지정.

```powershell
$env:D4D_HACKRF_BIN = 'D:\SDR\Library\bin'
.\.venv\Scripts\python.exe main.py --survey
```

USB 장치를 사용하는 다른 SDR 앱을 종료한 뒤 수신을 시작합니다. 이 앱은 RF AMP와 Bias-T를 끈 상태로 수신합니다. 펌웨어 업로드나 전파 송신은 수행하지 않습니다.

## 녹화 이미지 분석

학습 전처리와 동일한 640×640 PNG를 `assets/replay/`에 넣거나 `D4D_REPLAY_DIR`에 이미지 폴더를 지정합니다. 파일은 폴더 바로 아래에 있어야 합니다. 재생 샘플과 모델은 자동 다운로드하지 않습니다.

```powershell
$env:D4D_REPLAY_DIR = 'D:\WaveSentryData\replay'
.\.venv\Scripts\python.exe main.py --replay --autostart
```

REPLAY는 실제 모델을 실행하지만 RF를 수신하지 않습니다. 이미지 분류를 확인하는 모드이므로 LIVE의 고정 채널 필터를 적용하지 않습니다.

## NU-87 USB 경보

NU-87용 호환 경보 펌웨어가 설치된 보드를 연결합니다. 펌웨어 소스·바이너리는 이 Windows 앱 저장소의 배포 대상이 아닙니다.

```powershell
.\.venv\Scripts\python.exe -m serial.tools.list_ports -v
$env:D4D_NU87_SERIAL = '<연결할 보드의 USB 시리얼>'
.\'Start WaveSentry.cmd'
```

VID `10C4`, PID `EA60`과 지정한 시리얼이 모두 일치하는 포트 하나만 사용합니다. 시리얼을 설정하지 않으면 `NU-87 · 미설정`으로 표시합니다. 동일한 식별자를 가진 포트가 여러 개면 연결하지 않습니다. HELLO 응답도 확인한 뒤 경보 명령을 보냅니다.

| 요청 | 예상 응답 |
|---|---|
| `NU87/1 HELLO` | `NU87/1 READY DroneIndicator 1.0.0` |
| `NU87/1 SET 1` | `NU87/1 OK ALARM` |
| `NU87/1 SET 0` | `NU87/1 OK CLEAR` |

LIVE/SURVEY/REPLAY의 최신 확정 탐지와 DEMO의 활성 경보를 전달합니다. 종료·중지·입력 만료 시 경보를 해제합니다. 상태 표시를 오른쪽 클릭하면 3초 LED 테스트를 실행할 수 있습니다. 보드 통신을 끄려면 `D4D_NU87_DISABLED=1`을 설정합니다.

## 지도

`Setup.ps1 -Satellite` 또는 `python tools/vendor_cesium.py`가 CesiumJS 1.146.0 공식 npm 배포본의 SHA-512를 확인하고 필요한 자원과 라이선스를 `assets/satellite/vendor/cesium/`에 설치합니다. 설치 결과는 Git에서 제외됩니다.

Esri 공개 영상 타일에는 인터넷 연결이 필요합니다. 계정 토큰을 코드에 넣지 않습니다. 설치 누락·연결 실패 시 개략 지도를 사용하며, 다음 설정으로 처음부터 오프라인 모드를 선택할 수 있습니다.

```powershell
$env:WAVESENTRY_DEMO_MAP = 'schematic'
.\'Start Demo.cmd'
```

## 검증과 문제 확인

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe tools\check_source.py
.\.venv\Scripts\python.exe tools\validate_demo.py
# Cesium 설치와 인터넷 연결이 있을 때:
.\.venv\Scripts\python.exe tools\validate_satellite.py
```

시작 오류는 `runtime/startup-error.log`, NU-87 상태는 `runtime/nu87-indicator.jsonl`, 수신 결과는 `output/<세션>/`에 기록합니다. `settings.json`을 제거하면 기본 수신 설정으로 돌아갑니다. GUI의 **작업영역 → 패널 배치 초기화**로 화면 배치를 복원합니다.

로그와 IQ 스냅샷은 자동 삭제하지 않습니다. 수신 앱은 남은 공간을 검사하지만 장시간 운용 전에 저장 공간을 확보해야 합니다.
