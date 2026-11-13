# Co-Driver 주정차 단속·신고 위험 예측 모델

서울을 100m 격자로 나누고, 격자 × 요일 × 시간(168칸)마다 2026년 주정차 **단속 위험**과 **주민신고 위험**을 예측합니다.
결과는 등급표(JSON)로 저장되며, Co-Driver 서버가 정차 위치·시각으로 조회해 음성 안내에 사용합니다.

## 성능 (2025년 실제 기록으로 검증, 학습에 쓰지 않은 해)

| 지표 | 단속: 기준선 → LightGBM | 신고: 기준선 → LightGBM |
| --- | --- | --- |
| PR-AUC (주 지표) | 0.493 → **0.556** (+13%) | 0.221 → **0.316** (+43%) |
| ROC-AUC | 0.929 → 0.956 | 0.903 → 0.954 |
| 상위 1% 적중률 | 53.5% → **57.5%** | 22.1% → **25.4%** |

- 기준선: 같은 칸의 과거 기록 빈도만으로 순위를 매긴 방식
- 모델 5개 비교(`compare_models.py`) 결과 단속·신고 모두 LightGBM이 PR-AUC 1위 (랜덤 포레스트와 근소한 차)

| 모델 | 단속 PR-AUC | 신고 PR-AUC |
| --- | --- | --- |
| LightGBM (채택) | 0.556 | 0.316 |
| 랜덤 포레스트 | 0.554 | 0.315 |
| 로지스틱 회귀 | 0.537 | 0.299 |
| HistGradientBoosting | 0.520 | 0.253 |
| 기준선 (과거 빈도) | 0.493 | 0.221 |

## 정의

- **예측 단위**: 100m 격자(위도 0.0009° × 경도 0.00113°, 기준점 37.41, 126.76) × 요일(월=0) × 시간(0~23)
- **정답(label)**: 다음 1년 중 그 요일·시간에 기록이 있던 주의 비율 ≥ 10% (약 5주 이상)
- **피처 12개**: `dow`, `hour`, `hist_rate`, `recent_rate`, `recent3_rate`, `trend`, `rate_h-1`, `rate_h+1`, `rate_allday`, `nb_slot_rate`, `cell_total`, `nb_total`
- **검증**: 시간 순서 분할
  - 학습: 피처 2021.10 ~ 2023.12 → 정답 2024
  - 검증: 피처 2022.10 ~ 2024.12 → 정답 2025
  - 서비스: 피처 2023.10 ~ 2025.12 → 2026 예측
- **등급**: 전체 칸(격자 × 168) 중 예측 점수 상위 1% = 상, 그다음 4% = 중, 나머지 = 하

> JSON에는 '상'·'중'이 있는 격자만 저장합니다. 저장된 격자만 분모로 계산하면 '상'이 약 3.3%로 보이지만, 전체 격자로 나누면 정확히 1%입니다 (단속: 55,331 ÷ (32,935 × 168)).

## 폴더 구조

```
├── config.py            NAME = "enforce"(단속) / "report"(신고)
├── step1_seoul.py       단속 원본 CSV → data/processed/enforce/base.parquet
├── step1_report.py      신고 원본 CSV → data/processed/report/base.parquet
├── step3_grid.py        좌표 → 100m 격자, 요일·시간
├── step4_dataset.py     피처·정답 생성 → train.parquet, test.parquet
├── step5_train.py       LightGBM 학습·검증 → lgbm_eval.txt
├── step6_predict.py     최종 학습 + 2026 예측·등급 → risk_2026.parquet
├── step7_export.py      서비스용 등급표 → risk_2026.json
├── compare_models.py    모델 5개 비교 → model_compare_*.png / .csv
└── explore/             데이터 확인용 (모델 학습에는 사용 안 함)
    ├── check_raw.py
    ├── check_report.py
    └── step2_compare.py  강남구 단속 방식(CCTV·PDA) 비교
```

## 실행

```
pip install -r requirements.txt
```

데이터(원본 CSV)는 저장소에 포함하지 않습니다. 아래 폴더에 넣은 뒤 실행합니다.

```
data/raw/seoul/          서울시 불법주정차 단속 CSV
data/raw/seoul_report/   서울시 주정차 주민신고 CSV
```

**단속 / 신고 전환**: `config.py`는 기본값이 `NAME = "enforce"`(단속)입니다. 신고 모델을 돌릴 때는 `NAME = "report"`로 바꾼 뒤 아래 순서대로 실행합니다. 결과는 `data/processed/{NAME}/`에 따로 저장됩니다.

```
NAME = "enforce"   # 단속 모델
NAME = "report"    # 신고 모델
```

단속 모델 (`config.py`의 `NAME = "enforce"`)

```
python step1_seoul.py
python step3_grid.py
python step4_dataset.py
python step5_train.py
python step6_predict.py
python step7_export.py
```

신고 모델 (`config.py`의 `NAME = "report"`)

```
python step1_report.py
python step3_grid.py
python step4_dataset.py
python step5_train.py
python step6_predict.py
python step7_export.py
```

모델 비교 (두 모델의 step4까지 실행한 뒤)

```
python compare_models.py
```

결과 JSON(`data/processed/{NAME}/risk_2026.json`)을 서버의 `data/enforce_2026.json`, `data/report_2026.json`으로 복사해 사용합니다.

## 데이터 출처

- 서울시 불법주정차 단속 현황: https://data.seoul.go.kr/dataList/OA-22190/F/1/datasetView.do (서울시열린데이터광장)
- 서울시 주정차 주민신고 현황: https://data.seoul.go.kr/dataList/OA-22189/F/1/datasetView.do (서울시열린데이터광장)

## 한계

- 정답이 '불법 주정차 발생'이 아니라 '단속·신고 기록'이므로 단속이 자주 이뤄진 곳이 높게 나올 수 있음 → 신고 모델을 따로 두어 보완
- 등급은 확률이 아니라 상대 순위 → 서비스 문구는 "단속이 잦은 구역"으로 표현
- 2026년 전체에 하나의 등급표 (계절·공휴일 미반영), 서울 지역만 대상
