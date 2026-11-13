# SoloM (솔롬)

운전 중에 판단이 애매한 순간(우회전, 정차)을 차량 신호로 감지해서, 지켜야 할 교통 규칙을 도로교통법 조문과 함께 짧은 음성으로 알려주는 Pleos Connect 차량용 앱입니다.

현대자동차그룹 Pleos Playground 차량용 앱 개발 공모전 출품작입니다.

- 시연 영상: https://youtu.be/uHOdaeCrt6Y
- APK (release): https://github.com/jack8704/FinalProjectTeam2/releases/tag/v1.0

## 주요 기능

| 상황 | 감지 조건 | 안내 예시 |
|---|---|---|
| 우회전 (Case 1) | 내비 우회전 100m 이내 + 우측 깜빡이 + 회전 지점 50m 안 횡단보도 | 빨간불이면 정지선에서 멈추고, 보행자가 없을 때 우회전하세요. |
| 소화전 앞 정차 | 주행 후 기어 P 2초 유지 + 소화전 5m 이내 | 금지입니다. 소화전 5미터 안에는 세울 수 없습니다. |
| 횡단보도 앞 정차 | 기어 P 2초 유지 + 횡단보도 10m 이내 | 금지입니다. 횡단보도 10미터 안에는 세울 수 없습니다. |
| 버스정류장 앞 정차 | 기어 P 2초 유지 + 버스정류장 10m 이내 | 금지입니다. 버스정류장 10미터 안에는 세울 수 없습니다. |
| 단속·신고가 잦은 곳에 정차 | 정차 + 위 시설 없음 + 위험 예측 등급 '상' (서울만) | 단속·신고가 잦은 구역이라는 고정 문구 |

안내 문장은 RAG가 만들기 때문에 실제 표현은 조금씩 다를 수 있습니다.

- 금지인지 아닌지는 규칙엔진(좌표·거리 계산)이 정하고, RAG는 근거 조문을 찾아 설명만 합니다.
- GPS 오차가 크면 단정하지 않고 "가능성"으로 말하거나 안내를 보류합니다.
- 음성은 앱에서 Pleos TTS로 출력합니다.

## 구성

```
차량 앱 --POST /signal--> 판정 서버(:8000) --POST /situation--> RAG 서버(:8001)
차량 앱 <--GET /guidance (1초마다)-- 판정 서버
```

판정 서버는 규칙엔진, 시설 위치 DB, 위험 예측 결과를 써서 상황을 판정하고, RAG 서버는 도로교통법에서 근거 조문을 찾아 안내 문장을 만듭니다.

## 폴더 구조

| 경로 | 내용 |
|---|---|
| `server.py`, `core.py`, `case1.py`, `case2.py` | 판정 서버 (FastAPI). 신호 수신, Case 1·2 판정, 안내 저장 |
| `risk_lookup.py` | 주정차 단속·신고 위험도 조회 (100m 격자 × 요일 × 시간) |
| `facility.py` | 시설 위치 DB (횡단보도·소화전·버스정류장 약 29.8만 곳) |
| `prepare_facilities.py`, `prepare_busstop.py` | 공공데이터 원본을 판정용 CSV로 정리 |
| `data/` | 판정용 시설 CSV, 위험 예측 결과 (`enforce_2026.json` 단속, `report_2026.json` 신고) |
| `parking-risk-ml/` | 위험 예측 모델 학습·예측 코드 (LightGBM, step1~7) |
| `law_rag/law_rag/` | 도로교통법 RAG 서버 (BM25 + 벡터 검색, 답변 검증) |
| `navi_mock.py` | 시연용 TBT 모의 입력 (아래 "시연 관련" 참고) |
| `simulate_case1.py`, `check_risk_spot.py`, `find_near.py` | 테스트용 스크립트 |
| `*.gpx` | 에뮬레이터 시연 경로 |
| `SoloM 서울 주정차 위험 '상' 등급 지도.html` | 위험 예측 결과 지도 (브라우저로 열기) |
| `android/` | 차량 앱 (Kotlin) |
| `docs/` | 발표자료 (PDF) |

## 테스트 환경

| 항목 | 내용 |
|---|---|
| 에뮬레이터 | Pleos Connect v2.1.0 (Android 14, API 34, x86_64) |
| 화면 규격 | 2560 × 1440, 160 dpi |
| 앱 | release APK, minSdk 28, targetSdk 37 |
| 서버 PC | Windows, Python (Anaconda) |
| 앱이 접속하는 서버 주소 | `http://10.0.2.2:8000` (에뮬레이터를 실행한 PC) |

필요한 설정

1. `law_rag/law_rag/.env`에 API 키를 넣습니다. (실행 방법 2 참고)
2. RAG 서버(:8001)를 먼저 켜고 판정 서버(:8000)를 켭니다.
3. 서버는 에뮬레이터를 실행하는 PC에서 띄웁니다. 다른 PC에서 띄울 경우 포트 포워딩(netsh portproxy)이 필요합니다.
4. 앱을 처음 실행하면 위치·알림 권한을 허용합니다. 권한 창이 안 뜨면 adb로 허용합니다. (Pleos 에뮬레이터 운전자 계정은 user 10)

```bat
adb shell pm grant --user 10 com.aixlab.app android.permission.ACCESS_FINE_LOCATION
adb shell pm grant --user 10 com.aixlab.app android.permission.ACCESS_COARSE_LOCATION
adb shell pm grant --user 10 com.aixlab.app android.permission.POST_NOTIFICATIONS
```

5. 위치는 에뮬레이터 Extended controls > Location > Routes에서 GPX를 재생하고, 회전 정보(TBT)는 `navi_mock.py`로 넣습니다.

## 실행 방법 (Windows)

1) 패키지 설치

```bat
pip install -r requirements.txt
```

2) API 키

`law_rag/law_rag/.env` 파일을 만들고 아래처럼 넣습니다. (저장소에는 없음)

```
OPENAI_API_KEY=your_openai_api_key
PINECONE_API_KEY=your_pinecone_api_key
```

3) RAG 서버 (8001)

```bat
cd law_rag\law_rag
uvicorn rag_server:app --host 0.0.0.0 --port 8001
```

4) 판정 서버 (8000)

저장소 최상위 폴더에서 실행합니다.

```bat
set RAG_URL=http://127.0.0.1:8001
set RISK_DEMO_TIME=0-9
uvicorn server:app --host 0.0.0.0 --port 8000
```

`RISK_DEMO_TIME`은 시연할 때 요일·시간을 고정하는 값입니다. (0-9 = 월요일 9시) 평소에는 넣지 않습니다.

5) 앱 설치

```bat
adb install solom_solom_release.apk
```

APK는 위 Release 링크에서 받을 수 있습니다. 설치 후 에뮬레이터에서 SoloM을 실행하고 권한을 허용합니다.

6) 시연 경로 재생

```bat
python navi_mock.py codriver_all_cases_v4.gpx
```

GPX 재생 전에 먼저 실행해 둡니다.

## 시연 관련

- Pleos 에뮬레이터의 내비게이션이 가상 GPS를 따라가지 않아서(운영사무국 확인), 위치는 GPX 재생으로, 회전 정보(TBT)는 NaviHelper와 같은 형식의 모의값(`navi_mock.py`)으로 넣어서 시연했습니다. 운영사무국 안내에 따른 방식이고, 실차에서는 NaviHelper TBT를 그대로 받습니다.
- 안내 음성은 앱의 Pleos TTS(3.3.1)로 출력되는 것을 확인했습니다.
- 주정차 위험 예측은 서울 데이터로만 만들어서 서울에서만 동작합니다.

## 주정차 위험 예측 모델

- 데이터: 서울시 불법주정차 단속·신고 기록 (2023.10 ~ 2025.12)
- 단위: 100m 격자 × 요일 × 시간 (격자당 168칸)
- 모델: LightGBM, 피처 12개, 2025년 데이터로 시간 순서 검증

| 모델 | PR-AUC (기준선 → LightGBM) |
|---|---|
| 단속 | 0.493 → 0.556 |
| 신고 | 0.221 → 0.316 |

자세한 내용은 `parking-risk-ml/README.md`에 있습니다.

## 차량 앱 (android/)

| 항목 | 내용 |
|---|---|
| 앱 이름 / 패키지 | SoloM / `com.aixlab.app` |
| 개발 | Kotlin, Jetpack Compose, Android Studio |
| 대상 | Pleos Connect (Android Automotive OS) |
| Pleos SDK | Vehicle 2.3.2, NaviHelper 3.0.5, TextToSpeech 3.3.1 |
| AAOS | Car API (차속) |

- `MainActivity.kt`: 문·방향지시등·기어·차속 신호와 위치를 받아서 값이 바뀔 때 서버로 보냅니다. (POST /signal)
- `GuidanceService.kt`: Foreground Service로 1초마다 서버에서 안내를 받아(GET /guidance) Pleos TTS로 읽습니다. 내비게이션 화면이 떠 있어도 동작합니다.

권한

- Pleos: `TTS_SERVICE`, `CAR_DOORS`, `CAR_LIGHTS`, `CAR_DRIVE`, `CAR_SAFETY`, `NAVI_ROUTE`
- AAOS: `CAR_SPEED`
- Android: 위치, 인터넷, Foreground Service, 알림

빌드할 때 참고

- Pleos SDK는 Pleos Playground Maven 저장소(`nexus-playground.pleos.ai`)에서 받습니다. (`settings.gradle.kts`)
- release 빌드는 코드 축소(R8)를 끈 상태입니다. 켜면 실행 직후 종료되는 문제가 있었습니다.
- 서버 없이 앱만 실행하면 신호 수집은 되지만 음성 안내는 나오지 않습니다. 전체 동작은 시연 영상에서 볼 수 있습니다.

## 사용 기술

| 구분 | 내용 |
|---|---|
| 차량 앱 | Kotlin, Pleos Vehicle SDK, NaviHelper SDK, Pleos TTS |
| 판정 서버 | Python, FastAPI |
| RAG | BM25 + Pinecone 벡터 검색, OpenAI |
| 위험 예측 | LightGBM |

RAG(검색 증강 생성)는 도로교통법 조문을 먼저 검색하고, 찾은 조문만 근거로 안내 문장을 만드는 방식입니다.

## 데이터 출처

- 공공데이터포털: 전국횡단보도표준데이터, 전국소방용수시설표준데이터
- 국토교통부: 전국 버스정류장 위치정보
- 서울 열린데이터광장: 서울시 불법주정차 단속 정보(OA-22190), 신고 현황(OA-22189), 공공누리 1유형
- 국가법령정보센터: 도로교통법, 시행령, 시행규칙

원본 데이터와 법령 원문 파일은 용량이 커서 넣지 않았습니다. 위 출처에서 받아서 `data/raw/`, `law_rag/law_rag/data/`에 넣으면 됩니다.

## 팀

SoloM (솔롬)
