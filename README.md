# SoloM — 망설이는 순간, 나만의 운전 비서

차량 신호(방향지시등·기어·문·차속)와 위치로 운전자가 판단을 망설이는 순간을 먼저 감지하고,
그 자리의 교통 규칙을 **도로교통법 근거 조문과 함께 한 문장 음성**으로 안내하는 Pleos Connect 차량용 앱입니다.

> 현대자동차그룹 Pleos Playground 차량용 앱 개발 공모전 출품작

| 항목 | 링크 |
|---|---|
| 시연 영상 | https://youtu.be/uHOdaeCrt6Y |
| APK (release) | [GitHub Release v1.0](https://github.com/jack8704/FinalProjectTeam2/releases/tag/v1.0) |

---

## 핵심 기능

| 상황 | 감지 조건 | 안내 예시 |
|---|---|---|
| 우회전 횡단보도 (Case 1) | 내비 우회전 100m 이내 + 우측 깜빡이 + 회전 지점 횡단보도 50m 이내 | "빨간불이면 정지선에서 멈추고, 보행자가 없을 때 우회전하세요" |
| 소화전 주정차 (A7) | 주행 후 기어 P 2초 유지 + 소화전 5m 이내 | "금지입니다. 소화전 5미터 안에는 세울 수 없습니다." |
| 횡단보도 주정차 (A10) | 기어 P 2초 + 횡단보도 10m 이내 | "금지입니다. 횡단보도 10미터 안에는 세울 수 없습니다." |
| 버스정류장 주정차 (A9) | 기어 P 2초 + 버스정류장 10m 이내 | "금지입니다. 버스정류장 10미터 안에는 세울 수 없습니다." |
| 주정차 단속·신고 예상 지역 | 정차 + 위 시설 해당 없음 + 예측 등급 '상' (서울) | 단속·신고 다발 구역 안내 (고정 문구) |

- **GPS 오차 반영:** 위치 정확도에 따라 확정 / 가능성 / 판정 보류 3단계로 표현하고, 확실하지 않으면 단정하지 않습니다.
- **법 판단은 규칙엔진이, 근거 설명은 RAG가** 담당합니다. 법 판단을 LLM에 맡기지 않습니다.
- **음성 안내는 차량 앱이 Pleos TTS(온디바이스)로 직접 출력**합니다.

---

## 시스템 구성

```
[차량 앱]  신호 수집 ──POST /signal──▶ [판정 서버 :8000]  Case 판정 (규칙엔진 + 시설 위치 DB + 위험 예측)
   ▲  Pleos TTS 음성 출력                     │
   └────── GET /guidance (1초마다) ◀──────────┤──POST /situation──▶ [RAG 서버 :8001]  근거 조문 검색 + 설명
```

## 폴더 구조

| 경로 | 내용 |
|---|---|
| `server.py`, `core.py`, `case1.py`, `case2.py` | 판정 서버 (FastAPI) — 신호 수신, Case 1·2 판정, 안내 저장 |
| `risk_lookup.py` | 주정차 단속·신고 위험도 조회 (100m 격자 × 요일 × 시간) |
| `facility.py` | 시설 위치 DB (횡단보도·소화전·버스정류장, 약 29.8만 곳) |
| `prepare_facilities.py`, `prepare_busstop.py` | 공공데이터 원본 → 판정용 시설 CSV 정제 |
| `data/` | 판정용 시설 CSV, 위험 예측 결과(`enforce_2026.json` 단속, `report_2026.json` 신고) |
| `model/` | 주정차 위험 예측 모델 학습·예측 코드 (LightGBM) |
| `law_rag/law_rag/` | 도로교통법 RAG 서버 (하이브리드 검색 + 답변 검증) |
| `navi_mock.py` | **모의 TBT 입력** (시연용, 아래 고지 참고) |
| `simulate_case1.py`, `check_risk_spot.py`, `find_near.py` | 시험 도구 |
| `*.gpx` | 에뮬레이터 시연 경로 |
| `android/` | 차량 앱 SoloM (Kotlin) — 신호 수집, 서버 통신, Pleos TTS 음성 안내 |
| `docs/` | 발표자료 (PDF) |

---

## 테스트 환경

| 항목 | 내용 |
|---|---|
| 에뮬레이터 | **Pleos Connect v2.1.0** (Android 14 · API 34 · x86_64) |
| 화면 규격 | **2560 × 1440 px, 160 dpi** |
| 앱 빌드 | release APK, minSdk 28 · targetSdk 37 |
| 서버 PC | Windows, Python (Anaconda) |
| 앱 → 서버 주소 | `http://10.0.2.2:8000` (에뮬레이터에서 본 실행 PC 자신) |

### 필요한 설정
1. `law_rag/law_rag/.env`에 API 키 입력 (아래 실행 방법 2)
2. RAG 서버(:8001) → 판정 서버(:8000) 순서로 먼저 실행
3. 서버는 **에뮬레이터를 실행하는 PC**에서 띄웁니다. 다른 PC에서 띄우면 포트 연결(port proxy) 설정이 필요합니다.
4. 앱 첫 실행 시 위치·알림 권한을 허용합니다. 권한 창이 뜨지 않으면 adb로 허용합니다. (Pleos 에뮬레이터의 운전자 계정 = user 10)
```bat
adb shell pm grant --user 10 com.aixlab.app android.permission.ACCESS_FINE_LOCATION
adb shell pm grant --user 10 com.aixlab.app android.permission.ACCESS_COARSE_LOCATION
adb shell pm grant --user 10 com.aixlab.app android.permission.POST_NOTIFICATIONS
```
5. 위치는 에뮬레이터 **Extended controls → Location → Routes**에서 GPX 재생, 회전 정보(TBT)는 `navi_mock.py`로 입력합니다.

---

## 실행 방법 (Windows)

### 1. 설치
```bat
pip install -r requirements.txt
```

### 2. 환경변수
`law_rag/law_rag/.env` 파일에 키를 넣습니다. (저장소에는 포함되지 않음)
```
OPENAI_API_KEY=your_openai_api_key
PINECONE_API_KEY=your_pinecone_api_key
```

### 3. RAG 서버 실행 (포트 8001)
```bat
cd law_rag\law_rag
uvicorn rag_server:app --host 0.0.0.0 --port 8001
```

### 4. 판정 서버 실행 (포트 8000)
```bat
cd 저장소 최상위 폴더
set RAG_URL=http://127.0.0.1:8001
set RISK_DEMO_TIME=0-9
uvicorn server:app --host 0.0.0.0 --port 8000
```
- `RISK_DEMO_TIME`: 시연용 요일-시각 고정 (0-9 = 월요일 9시). 실제 운행 시에는 설정하지 않음

### 5. 앱 설치·실행
```bat
adb install solom_solom_release.apk
```
- APK는 [GitHub Release v1.0](https://github.com/jack8704/FinalProjectTeam2/releases/tag/v1.0)에서 받습니다.
- 에뮬레이터 앱 목록에서 **SoloM** 실행 → 권한 허용 (위 "필요한 설정" 4)

### 6. 시연 보조
```bat
python navi_mock.py codriver_all_cases_v4.gpx    # 모의 TBT 입력 (GPX 재생 전에 실행)
```
- 안내 음성은 **차량 앱이 Pleos TTS(온디바이스)로 직접 출력**합니다.

---

## 시연 관련 고지

- Pleos 에뮬레이터의 내비게이션은 가상 GPS를 인식하지 않습니다 (Pleos 운영사무국 확인).
- 따라서 위치는 **GPX 경로 재생**으로, 회전 정보(TBT)는 **NaviHelper와 같은 형식의 모의값(`navi_mock.py`)**으로 입력해 시연했습니다. 운영사무국 안내에 따른 방식입니다.
- 실차에서는 NaviHelper TBT를 그대로 받는 구조입니다.
- 안내 음성은 앱에서 Pleos TTS(3.3.1, 온디바이스)로 출력하며 동작을 확인했습니다.
- 주정차 단속·신고 위험 예측은 **서울 지역 시범 적용**입니다.

---

## 주정차 위험 예측 모델

- 데이터: 서울시 불법주정차 단속·신고 기록 (2023.10–2025.12)
- 단위: 100m 격자 × 요일 × 시간 (격자마다 168칸)
- 모델: LightGBM (피처 12개), 2025년 시간순 검증

| 모델 | PR-AUC (기준선 → LightGBM) |
|---|---|
| 단속 | 0.493 → 0.556 (+13%) |
| 신고 | 0.221 → 0.316 (+43%) |

---

## 차량 앱 (android/)

| 항목 | 내용 |
|---|---|
| 앱 이름 / 패키지 | SoloM / `com.aixlab.app` |
| 개발 환경 | Kotlin, Jetpack Compose, Android Studio |
| 대상 | Pleos Connect (Android Automotive OS), minSdk 28 · targetSdk 37 |
| Pleos SDK | Vehicle 2.3.2, NaviHelper 3.0.5, TextToSpeech 3.3.1 |
| AAOS API | Car API (`useLibrary("android.car")`) — 차속 |

**구성**
- `MainActivity.kt`: 차량 신호(문·방향지시등·기어·차속)와 위치를 받아, 값이 바뀔 때 서버로 전송 (POST /signal)
- `GuidanceService.kt`: Foreground Service. 1초마다 서버 안내를 받아(GET /guidance) Pleos TTS(온디바이스)로 읽음. 내비게이션이 화면 앞에 있어도 동작

**주요 권한**
- Pleos: `TTS_SERVICE`, `CAR_DOORS`, `CAR_LIGHTS`, `CAR_DRIVE`, `CAR_SAFETY`, `NAVI_ROUTE`
- AAOS: `CAR_SPEED`
- Android: 정밀 위치, 인터넷, Foreground Service, 알림

**빌드**
- Pleos SDK는 Pleos Playground Maven 저장소(`nexus-playground.pleos.ai`)에서 받습니다 (`settings.gradle.kts`에 설정).
- 에뮬레이터에서 일부 권한은 adb로 허용해야 합니다 (위 "테스트 환경 → 필요한 설정" 4).
- 제출 APK: release 빌드, [GitHub Release v1.0](https://github.com/jack8704/FinalProjectTeam2/releases/tag/v1.0)
- 앱은 판정 서버(포트 8000)와 통신해야 안내가 나옵니다. 위 "실행 방법"대로 서버를 먼저 실행한 뒤 앱을 켜 주세요.
- 서버 없이 앱만 실행하면 신호 수집은 동작하지만 음성 안내는 나오지 않습니다. 전체 동작은 시연 영상을 참고해 주세요.

---

## 사용 기술

| 구분 | 내용 |
|---|---|
| 차량 앱 | Kotlin, Pleos Vehicle SDK 2.3.2, NaviHelper SDK 3.0.5, Pleos TTS 3.3.1 |
| 판정 서버 | Python, FastAPI |
| RAG | Pinecone, BM25 하이브리드 검색, OpenAI — 도로교통법 조문을 먼저 검색해, 찾은 조문만 근거로 안내 문장을 생성 (RAG: 검색 증강 생성) |
| 위험 예측 | LightGBM |

## 데이터 출처

- 공공데이터포털: 전국횡단보도표준데이터, 전국소방용수시설표준데이터
- 국토교통부: 전국 버스정류장 위치정보
- 서울 열린데이터광장: 서울시 불법주정차 단속 정보(OA-22190), 신고 현황(OA-22189) — 공공누리 1유형(출처표시)
- 국가법령정보센터: 도로교통법, 시행령, 시행규칙
- 원본 데이터와 법령 원문 파일은 용량 때문에 저장소에 포함하지 않았습니다. 위 출처에서 내려받아 `data/raw/`와 `law_rag/law_rag/data/`에 넣으면 됩니다.

## 팀

SoloM (솔롬) 팀
