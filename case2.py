# case2.py — Case 2: 정차 판정 (트리거 = P단 2초 유지)
#   A7 소화전 5m / A10 횡단보도 10m / A9 버스정류장 10m / D2 문 열림 시 후방 확인 (A6 스쿨존은 보호구역 데이터 도착 후 추가)
import time, threading, os
from core import latest, SITU, CW, HYD, BUS, case_lock, trigger_group, gps_tier, push_guidance

# ★ 11/10 추가: 주정차 단속·신고 위험 예측 (동료 ML 결과, risk_lookup.py + data/*.json)
try:
    import risk_lookup                                       # 같은 폴더의 risk_lookup.py
    if os.environ.get("RISK_DEMO_TIME"):                     # 시연용 요일-시 고정 (예: set RISK_DEMO_TIME=0-9 → 월요일 9시)
        risk_lookup.DEMO_TIME = os.environ["RISK_DEMO_TIME"]
    print(f"[Case 2] 위험 예측 로드: 단속 {len(risk_lookup.ENF)}칸 / 신고 {len(risk_lookup.REP)}칸"
          f" / 시각 {'고정 ' + risk_lookup.DEMO_TIME if risk_lookup.DEMO_TIME else '현재 시각'}")
except Exception as e:                                       # 파일이 없어도 서버는 계속 동작 (예측 안내만 꺼짐)
    risk_lookup = None
    print(f"[Case 2] 위험 예측 사용 안 함: {e}")
RISK_ID = {"parking_risk_enforce": "P_ENFORCE", "parking_risk_report": "P_REPORT"}   # 로그·guidance.csv에 남는 코드

SITU.update({                                                # 이 Case가 쓰는 RAG 상황 코드 등록 (팀 RAG situations.py 이름과 동일)
    "A7_STOP":  ("parking_hydrant",   "금지"),                 # 소화전 5m 이내 정차
    "A10_STOP": ("parking_crosswalk", "금지"),                 # 횡단보도 10m 이내 정차
    "A9_STOP":  ("parking_bus_stop",  "금지"),                 # 버스정류장 10m 이내 정차
    "D2_EXIT":  ("door_open",         "주의"),                 # 정차 중 문이 열리는 순간 후방 확인
})

PARK_CONFIRM_SEC = 2                                         # P단이 2초 유지되면 정차 확정 (1~3초에서 조정)
LOC_MAX_AGE = 10                                             # 위치가 10초보다 오래되면 판정 보류 (BL-03)
ACC_HOLD    = 15                                             # GPS 오차 15m 이상이면 거리 판정 생략 (개발지침 3-2)
case2 = {"parked": False, "done": set(), "timer": None, "armed": False, "checked": None}   # 정차 확정 여부, 낸 안내, 확정 대기 타이머, 주행 이력
MOVE_KMH = 5                                                # 이 속도를 넘게 달린 적이 있어야 다음 P단을 "주차"로 봄

def is_parking_now():                                        # 지금 P단 + 정지 상태인지
    return latest.get("gear") == "GEAR_PARK" and float(latest.get("speed_kmh") or 0) <= 5

def judge_parking():                                         # 정차 확정 순간 1회 실행 → 안내할 (코드, 내용) 또는 None
    case2["checked"] = None                                  # ★ 법규 판정을 끝까지 마쳤을 때만 위치를 남김 (보류면 None)
    loc = latest.get("location")                             # "위도,경도"
    ts = latest.get("loc_ts")                                # 위치를 받은 서버 시각
    if not loc or ts is None or time.time() - ts > LOC_MAX_AGE:
        print("    Case 2 보류: 위치 없음 또는 오래됨"); return None
    lat, lon = map(float, loc.split(","))
    acc_raw = latest.get("gps_accuracy")
    acc = float(acc_raw) if acc_raw not in (None, "none") else 99.0   # 정확도 없으면 보류 쪽으로
    if acc >= ACC_HOLD:
        print(f"    Case 2 보류: GPS 오차 ±{acc:.0f}m (기준 {ACC_HOLD}m 이상)"); return None

    for cid, db, name, limit in (("A7_STOP", HYD, "소화전", 5), ("A10_STOP", CW, "횡단보도", 10), ("A9_STOP", BUS, "버스정류장", 10)):  # 우선순위 순서
        near = db.nearby(lat, lon, radius_m=limit + acc + 15)     # 후보 검색 (횡단보도 길이 보정 여유 15m)
        if not near:
            print(f"    {cid}: 반경 안 {name} 없음"); continue
        f = near[0]                                          # 가장 가까운 시설
        half = float(f.get("length_m") or 0) / 2             # 횡단보도는 중심점이 아니라 끝까지 거리 (길이 정보 있을 때)
        dist = max(0.0, f["dist_m"] - half)
        tier = gps_tier(dist, acc, limit)                    # 확정 / 가능성 / 해당 없음
        print(f"    {cid}: {name} {f.get('id')} {dist:.1f}m / 기준 {limit}m / GPS ±{acc:.0f}m → {tier}")
        if tier in ("확정", "가능성"):
            case2["done"].add(cid)
            return (cid, f"({f.get('road', '')} {name} {f.get('id')} {dist:.0f}m, GPS ±{acc:.0f}m → {tier})")   # 겹치면 1개만 (A7 > A10 > A9)
    case2["checked"] = (lat, lon, acc)                       # ★ 금지 구역 아님이 '확인'된 위치 → 위험 예측에 사용
    return None

def judge_risk():                                            # ★ 11/10 추가: 금지 구역이 아닐 때만 단속·신고 위험 예측 조회
    if risk_lookup is None or not case2.get("checked"):      # 모듈 없음 또는 법규 판정이 보류됨(위치·오차) → 조회 안 함
        return None
    lat, lon, acc = case2["checked"]
    code, msg = risk_lookup.parking_risk(lat, lon, acc_m=acc)   # '상'일 때만 (코드, 문구), 아니면 (None, None)
    tkey = risk_lookup.time_key()
    print(f"    위험 예측: 격자 {risk_lookup.to_key(lat, lon)} / 요일-시 {tkey} → {code or '안내 없음 (중·하·데이터 없음)'}")
    return (RISK_ID[code], msg) if code else None

def confirm_park():                                          # P단 진입 2초 뒤 타이머가 실행
    with case_lock:                                          # 신호 수신 판정과 겹치지 않게
        case2["timer"] = None
        if case2["parked"] or not is_parking_now():          # 이미 확정됐거나 그사이 P단이 풀림 → 판정 안 함
            return
        case2["parked"] = True
        case2["armed"] = False                               # 이번 주차에 사용함 → 다시 달려야 다음 판정
        print(f"\n--- 정차 확정 (P단 {PARK_CONFIRM_SEC}초 유지) → Case 2 판정")
        hit = judge_parking()                                # A7 / A10 / A9 위치 판정
        if hit:                                              # 금지 구역이면 주정차 금지 안내 1건 (법규 우선)
            trigger_group([hit])
            return
        risk = judge_risk()                                  # ★ 금지 구역 아님 → 단속·신고 위험 예측
        if risk:                                             # '상' 등급 → LLM 없이 고정 문구 바로 안내 (빠름, 판정 아닌 예측이라 꾸밀 필요 없음)
            cid, msg = risk
            case2["done"].add(cid)
            print(f"    {cid} 안내 (고정 문구): {msg}")
            push_guidance(cid, msg)
        else:
            print("    금지 구역 아님 + 위험 예측 해당 없음 → 안내 없음")

def is_moving():                                            # 실제로 달리고 있는지 (차량 속도 또는 3초 안의 GPS 속도)
    spd = float(latest.get("speed_kmh") or 0)
    if time.time() - latest.get("loc_ts", 0) <= 3:           # 오래된 GPS 속도는 무시
        spd = max(spd, float(latest.get("gps_speed_kmh") or 0))
    return latest.get("gear") in ("GEAR_DRIVE", "GEAR_REVERSE") and spd > MOVE_KMH

# ───────── D2: 시동이 켜진 상태(앱이 신호를 받는 중)에서 문이 '열리는 순간' 후방 확인 안내 ─────────
d2 = {"was_open": None, "done": False}                       # 직전 문 상태(None=아직 모름), 이번 정차에서 안내했는지

def door_open_now():                                         # 문 신호 중 하나라도 열림이면 True
    found = False
    for k, v in latest.items():
        if not k.startswith("door"):                         # door, door_row_1_left 등 문 관련 신호만
            continue
        found = True
        val = str(v).strip().upper()
        try:
            if float(val) > 0: return True                   # Pleos 문 위치: 0 = 닫힘, 0 초과 = 열림
        except ValueError:
            if "OPEN" in val or val == "TRUE": return True   # 문자 값으로 오는 경우
    return False if found else None                          # 문 신호를 아직 한 번도 못 받았으면 None

def check_door():
    now = door_open_now()
    if now is None:
        return
    spd = float(latest.get("speed_kmh") or 0)
    if spd > 5:                                              # 달리는 중 → 다음 정차에서 다시 안내 가능
        d2["done"] = False
    opened = d2["was_open"] is False and now                 # 닫힘 → 열림으로 바뀐 순간만 (앱 시작 때 첫 값은 기준으로만 사용)
    d2["was_open"] = now
    if opened and spd <= 5 and not d2["done"]:              # 멈춘 상태에서 문이 열림 (기어 무관: D단 정차 후 하차도 포함)
        d2["done"] = True
        trigger_group([("D2_EXIT", "(정차 중 문 열림, 하차 시 후방 확인)")])

def evaluate():                                              # server.py가 신호마다 호출
    check_door()                                             # D2는 정차 판정과 따로 동작
    if is_moving() and not case2["armed"]:
        case2["armed"] = True                                # 주행 이력 기록 → 다음 P단부터 판정
        print("--- Case 2 준비 (주행 감지)")
    if not is_parking_now():                                 # 정차가 아님 (주행, 신호 대기, 후진, N, 이상값)
        if case2["timer"]:
            case2["timer"].cancel(); case2["timer"] = None   # 2초 안에 P단이 풀리면 확정 취소
        if case2["parked"]:
            print("--- Case 2 초기화 (P단 해제)")
        case2["parked"] = False
        case2["done"].clear()                                # 다음 정차 때 다시 판정
        return
    if not case2["armed"]:                                   # 시동 직후처럼 달린 적 없이 P단 → 출발 전이므로 판정 안 함
        return
    if not case2["parked"] and case2["timer"] is None:       # P단 진입 순간 → 2초 타이머 시작
        # 앱은 값이 바뀔 때만 보내서, 2초 뒤에 새 신호가 안 올 수 있음 → 타이머로 직접 확인
        case2["timer"] = threading.Timer(PARK_CONFIRM_SEC, confirm_park)
        case2["timer"].daemon = True
        case2["timer"].start()