# risk_lookup.py — 주정차 단속·신고 위험도 조회 (case2.py에서 import 해서 사용)
# 필요 파일 : 이 파일과 같은 폴더의 data/enforce_2026.json, data/report_2026.json
# 격자 규칙 : 동료 모델 코드 step3_grid.py 기준 (키 = "경도칸_위도칸")
import json, datetime
from pathlib import Path

# ---------------- 격자 규칙 (step3_grid.py 와 반드시 같아야 함)
ORIGIN_LAT, ORIGIN_LNG = 37.41, 126.76        # 격자 기준점
SIZE_LAT,  SIZE_LNG    = 0.0009, 0.00113      # 격자 한 칸 크기(도) ≈ 100m
LAT_MAX,   LNG_MAX     = 37.72, 127.19        # 데이터 범위 (밖이면 조회 안 함)

# ---------------- 서비스 설정
DEMO_TIME   = None     # 시연 시 '요일-시' 고정 (예: '0-9' = 월요일 9시). 평소에는 None
ACC_DEFAULT = 10       # GPS 정확도 값이 안 들어왔을 때 가정할 오차(m)
ACC_MAX     = 50       # 오차 반영 최대치(m) : 너무 크면 주변 칸을 과하게 봄

MSG_REP = '도로변에 정차하셨다면, 이곳은 주민 신고가 잦은 구역입니다. 신고 단속은 사전 문자 알림이 오지 않습니다.'
MSG_ENF = '도로변에 정차하셨다면, 이곳은 불법주정차 단속이 잦은 구역입니다.'

# ---------------- 데이터 로드 (서버 시작 시 1번만)
BASE = Path(__file__).parent                                   # 이 파일이 있는 폴더 기준
ENF = json.load(open(BASE / 'data/enforce_2026.json', encoding='utf-8'))['risk']
REP = json.load(open(BASE / 'data/report_2026.json',  encoding='utf-8'))['risk']
RANK = {'상': 2, '중': 1}                                      # 등급 비교용


def to_key(lat, lng):
    'GPS 좌표 → JSON 격자 키 ("경도칸_위도칸"), 범위 밖이면 None'
    if not (ORIGIN_LAT <= lat < LAT_MAX and ORIGIN_LNG <= lng < LNG_MAX):
        return None                                            # 음수 칸 번호 방지
    gx = int((lng - ORIGIN_LNG) / SIZE_LNG)                    # 경도 칸 번호
    gy = int((lat - ORIGIN_LAT) / SIZE_LAT)                    # 위도 칸 번호
    return f'{gx}_{gy}'                                        # 순서 주의 : 경도 먼저


def key_center(key):
    '격자 키 → 격자 중심 좌표 (테스트·시연 위치 찾기용)'
    gx, gy = map(int, key.split('_'))
    return ORIGIN_LAT + (gy + 0.5) * SIZE_LAT, ORIGIN_LNG + (gx + 0.5) * SIZE_LNG


def cells_in_error(lat, lng, acc_m):
    'GPS 오차 반경 안에 걸치는 격자 키들 (중심 + 상하좌우 4점)'
    dlat, dlng = acc_m / 111000, acc_m / 88000                 # 오차(m) → 도 (서울 기준)
    pts = [(lat, lng), (lat + dlat, lng), (lat - dlat, lng), (lat, lng + dlng), (lat, lng - dlng)]
    return {k for k in (to_key(a, b) for a, b in pts) if k}    # 범위 밖(None) 제외


def time_key(now=None):
    '조회할 "요일-시" 키 (월요일=0, 모델과 같은 기준)'
    if DEMO_TIME:                                              # 시연 모드
        return DEMO_TIME
    now = now or datetime.datetime.now()                       # 서버 시각(한국시간)
    return f'{now.weekday()}-{now.hour}'


def grade(table, keys, tkey):
    '여러 격자 중 가장 높은 등급 (없으면 None)'
    gs = [table.get(k, {}).get(tkey) for k in keys]
    gs = [g for g in gs if g]
    return max(gs, key=RANK.get) if gs else None


def parking_risk(lat, lng, acc_m=None, now=None):
    '정차 위치 → (상황코드, 안내 문구). 안내 안 하면 (None, None)'
    acc = min(acc_m or ACC_DEFAULT, ACC_MAX)                   # 오차 반영 범위
    keys = cells_in_error(lat, lng, acc)
    tkey = time_key(now)
    if grade(REP, keys, tkey) == '상':                         # 신고 위험 우선 (사전 알림 없음)
        return 'parking_risk_report', MSG_REP
    if grade(ENF, keys, tkey) == '상':
        return 'parking_risk_enforce', MSG_ENF
    return None, None                                          # 중·하·데이터 없음 → 무음


# ---------------- 단독 테스트 : python risk_lookup.py
if __name__ == '__main__':
    print('격자 수 → 단속:', len(ENF), '/ 신고:', len(REP))

    # 1) 왕복 검사 : 키 → 중심 좌표 → 키 가 같아야 격자 규칙이 맞음
    bad = sum(to_key(*key_center(k)) != k for k in list(ENF) + list(REP))
    print('1) 왕복 불일치:', bad, '(0이어야 정상)')

    # 2) 단속 '상' 격자 중심 + 그 시간대 → P_ENFORCE 또는 P_REPORT 가 나와야 함
    k, v = next((k, v) for k, v in ENF.items() if '상' in v.values())
    t = next(t for t, g in v.items() if g == '상')
    DEMO_TIME = t
    print('2) 상 격자', k, t, '→', parking_risk(*key_center(k), acc_m=5))

    # 3) 서울 밖 좌표 → 무음
    print('3) 서울 밖(안양) →', parking_risk(37.3943, 126.9568))

    # 4) 시연 후보 : 보라매 부근 단속 '상' 격자 145_90, 월요일 9시
    DEMO_TIME = '0-9'
    print('4) 시연 후보 145_90 월 9시 →', parking_risk(*key_center('145_90'), acc_m=5))
