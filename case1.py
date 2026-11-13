# case1.py — Case 1: 우회전 횡단보도 (상황 표 A1 + A2)
import time, math, threading
from collections import deque
from core import latest, SITU, CW, trigger, gps_tier, bearing, angle_diff, dist_m, rag_guidance, push_guidance

SITU.update({                                                # 이 Case가 쓰는 RAG 상황 코드 등록
    "C1_PRE":  ("right_turn", "주의"),                         # 내비 300m 앞 우회전 예고
    "C1_STOP": ("right_turn", "주의"),                         # 내비 우회전 100m 이내 + 깜박이 RIGHT + 정면/오른쪽 횡단보도
    "A1_STOP_NOSIG": ("right_turn", "주의"),                   # 내비 우회전 100m 이내인데 깜박이 OFF → 사전 안내 + 방향지시등 안내
    "A1_POST_NOSIG": ("right_turn", "주의"),                   # 깜박이 없이 횡단보도 앞 우회전 → 사후 교육 안내
    "A1_POST_SIG": ("right_turn", "주의"),                     # 내비 없이 깜박이 켜고 우회전 → 사후 안내 (사전 판정 근거 부족)
})

# 횡단보도 위치별로 RAG 코드를 나눠 문구를 다르게 함
#   앞쪽(회전 전) → right_turn_front: "빨간불이면 반드시 멈춘 뒤 우회전"
#   오른쪽(회전 후) → right_turn_after: "보행자가 있거나 건너려 하면 정지"
for base in ("C1_STOP", "A1_STOP_NOSIG", "A1_POST_SIG", "A1_POST_NOSIG"):
    SITU[base + "_F"] = ("right_turn_front", "주의")
    SITU[base + "_R"] = ("right_turn_after", "주의")
    SITU[base + "_B"] = ("right_turn_both", "주의")             # 둘 다 있을 때
POS = {"앞쪽": "전방(회전 전) 횡단보도", "오른쪽": "회전 후 횡단보도"}

def fire(base, sides, detail):                               # 위치별 안내 (둘 다 있으면 합친 문구 1개 = RAG 1번 호출)
    if {"앞쪽", "오른쪽"} <= sides:
        trigger(base + "_B", f"{detail} 위치: {POS['앞쪽']} + {POS['오른쪽']}")   # 신호를 모르니 두 규칙 모두, 한 번에
    elif "앞쪽" in sides:
        trigger(base + "_F", f"{detail} 위치: {POS['앞쪽']}")
    elif "오른쪽" in sides:
        trigger(base + "_R", f"{detail} 위치: {POS['오른쪽']}")

NOSIG_WINDOW = 30                                            # 우회전 직전 30초 안의 횡단보도 접근 이력만 사용
approach = deque()                                           # (시각, 횡단보도 id, 도로명, 접근 방향, 위치) — 사후 감지용 접근 기록
post_done = {}                                               # 횡단보도 id → 사후 안내한 시각 (같은 곳 반복 방지)
last_right = {"t": 0.0, "pre": 0.0}                          # 깜박이 RIGHT를 마지막으로 본 시각, 사전 안내 시각

case1 = {"pre_alerted": False, "alerted": False, "start_heading": None, "pre_time": 0.0}
PRE_ENABLED = False                                          # 우회전 예고(C1_PRE) 끔 — C1_STOP과 내용 중복, 음성 밀림 원인 (다시 쓰려면 True)
PRE_GAP = 60                                                 # 우회전 예고는 60초에 1번까지 (TBT 값이 깜빡여도 반복 안내 방지)
TBT_NEAR = 100                                               # 내비 우회전이 이 거리(m) 안이면 '우회전 예정'으로 봄
SIG_DUE = 30                                                 # 방향지시등은 회전 지점 30m 전부터 켜야 함 (도로교통법 시행령 별표2)
                                                             #        → 깜박이 OFF 안내는 30m 안에 들어와도 안 켰을 때만

def side_of(lat, lon, cw, h):                                # 횡단보도가 진행 방향 기준 어디에 있는지
    rel = (bearing(lat, lon, cw["lat"], cw["lon"]) - h) % 360    # 0 = 정면, 90 = 오른쪽
    if rel <= 45 or rel >= 315:
        return "앞쪽"
    if 45 < rel <= 135:
        return "오른쪽"
    return None                                              # 왼쪽·뒤쪽은 대상 아님

# ───────── 미리 판정: 내비 우회전 150m 안에 들어오면 회전 지점 횡단보도를 미리 찾고 안내 문장도 미리 받아 둠 ─────────
#   → 깜박이를 켜는 순간 RAG를 기다리지 않고 바로 음성 (RAG는 그대로 사용, 회전마다 그때그때 생성)
PREP_NEAR = 150                                              # 이 거리(m) 안에서 미리 판정 시작
prep = {"tp": None, "sides": set(), "detail": "", "texts": {}, "busy": False}   # 회전 지점 추정 좌표, 횡단보도 위치, 준비된 문장

def project(lat, lon, h, d):                                 # (lat, lon)에서 방향 h로 d(m) 간 지점
    dy = d * math.cos(math.radians(h)) / 111320
    dx = d * math.sin(math.radians(h)) / (111320 * math.cos(math.radians(lat)))
    return lat + dy, lon + dx

def suffix(sides):                                           # 횡단보도 위치 → 코드 접미사
    if {"앞쪽", "오른쪽"} <= sides: return "_B"
    return "_F" if "앞쪽" in sides else "_R"

def prepare(lat, lon, h, tbt_d, acc):
    tp = project(lat, lon, h, tbt_d)                         # 내비 거리로 추정한 회전 지점
    if prep["tp"] and dist_m(*prep["tp"], *tp) < 40:
        return                                               # 같은 회전은 이미 준비함
    vp = project(lat, lon, h, max(tbt_d - 30, 0))            # 회전 30m 전 위치(그때 내 차가 있을 곳)에서 본 횡단보도
    hits = []
    for cw in CW.nearby(vp[0], vp[1], radius_m=50 + acc):
        side = side_of(vp[0], vp[1], cw, h)
        if side in ("앞쪽", "오른쪽") and gps_tier(cw["dist_m"], acc, 50) in ("확정", "가능성"):
            hits.append((cw, side))
    prep.update(tp=tp, sides={s for _, s in hits}, texts={}, busy=False)
    if not hits:
        print(f"--- [미리 판정] 내비 우회전 {tbt_d:.0f}m: 회전 지점 주변 횡단보도 없음 → 안내 대상 아님"); return
    cw = hits[0][0]
    pos = " + ".join(POS[s] for s in ("앞쪽", "오른쪽") if s in prep["sides"])
    prep["detail"] = f"({cw['road']} 횡단보도 {cw['id']} 외 {len(hits)-1}곳, 내비 우회전 {tbt_d:.0f}m 지점) 위치: {pos}"
    print(f"--- [미리 판정] 내비 우회전 {tbt_d:.0f}m: {pos} → 안내 문장 미리 요청")
    prep["busy"] = True
    def run(sfx=suffix(prep["sides"]), detail=prep["detail"], tp_now=tp):
        for base, extra in (("C1_STOP", ", 근거: 깜박이 + 내비 우회전"), ("A1_STOP_NOSIG", ", 깜박이 OFF → 방향지시등 켜기 안내 포함")):
            text = rag_guidance(base + sfx, detail + extra, push=False)
            if prep["tp"] == tp_now:                         # 그사이 다른 회전으로 바뀌지 않았으면 저장
                prep["texts"][base] = text
        prep["busy"] = False
    threading.Thread(target=run, daemon=True).start()

def fire_prepared(base):                                     # 깜박이 순간: 준비된 문장을 바로 저장 (아직 준비 중이면 끝날 때까지 기다림)
    cid = base + suffix(prep["sides"])
    def run():
        for _ in range(100):                                 # 최대 10초 대기
            if base in prep["texts"] or not prep["busy"]: break
            time.sleep(0.1)
        text = prep["texts"].get(base)
        if text and base == "A1_STOP_NOSIG" and "방향지시" not in text:
            text = "방향지시등을 켜세요. " + text            # 깜박이 미점등 안내 (도로교통법 제38조)
        if text:
            push_guidance(cid, text)
            print(f">>> [안내 {cid} · 미리 준비] {text}\n")
        else:
            trigger(cid, prep["detail"])                     # 준비 실패 → 실시간 RAG
    threading.Thread(target=run, daemon=True).start()

# 방향값 튐 방지: 에뮬레이터는 멈추는 순간 방향을 0°로 보냄 (속도 0보다 먼저 도착하기도 함)
#   → 직전 방향과 45° 넘게 다른 값은 1초 뒤에도 같은 값일 때만 인정 (실제 회전은 1초 뒤에도 그 방향이라 통과)
hd = {"ok": None, "pend": None, "t": 0.0}
def heading_filter(raw):
    if raw in (None, "none"):
        return raw
    v, now = float(raw), time.time()
    if hd["ok"] is None or angle_diff(v, hd["ok"]) <= 45:
        hd.update(ok=v, pend=None)                           # 자연스러운 변화 → 바로 반영
    elif hd["pend"] is not None and angle_diff(v, hd["pend"]) <= 10 and now - hd["t"] >= 1.0:
        hd.update(ok=v, pend=None)                           # 1초 뒤에도 같은 방향 → 실제 회전으로 인정
    elif hd["pend"] is None or angle_diff(v, hd["pend"]) > 10:
        hd.update(pend=v, t=now)                             # 처음 튄 값 → 보류
    return hd["ok"]

def evaluate():                                              # server.py가 신호마다 호출
    turn = latest.get("turn_signal")                         # OFF / RIGHT / LEFT
    speed = float(latest.get("speed_kmh", 0))                # 차량 신호 기준 속도
    if time.time() - latest.get("loc_ts", 0) <= 3:           # GPS 속도는 3초 안에 받은 위치일 때만 반영 (GPX 끝난 뒤 남은 값 무시)
        speed = max(speed, float(latest.get("gps_speed_kmh") or 0))
    if latest.get("gear") in ("GEAR_PARK", "GEAR_NEUTRAL", "GEAR_REVERSE") and speed <= 5:
        return                                               # P·N·R로 서 있을 때만 판정 안 함 (에뮬레이터는 P단에서도 GPX로 움직일 수 있어 속도로 함께 판단)
    loc = latest.get("location")                             # "위도,경도"
    head = heading_filter(latest.get("heading"))             # 진행 방향 (갑자기 튄 값은 1초 확인 후 반영)
    if speed <= 5:
        head = None                                          # 멈춰 있을 때 방향값은 믿을 수 없음 (에뮬레이터는 정차 시 0°로 보냄 → 회전 오판 방지)
    acc_raw = latest.get("gps_accuracy")
    acc = float(acc_raw) if acc_raw not in (None, "none") else 99.0   # 정확도 없으면 99m로 간주 (보류)
    nxt = latest.get("navi_next_turn")                       # "TURN_RIGHT,250.0"
 
    now = time.time()
    if turn == "RIGHT":
        last_right["t"] = now                                # 깜박이를 켠 적이 있으면 사후 안내 대상 아님
    tbt_right, tbt_d = False, float("inf")                   # 내비 다음 회전이 우회전인지, 남은 거리

    # ① 내비 예고: 다음 회전이 우회전이고 300m 이내
    if nxt:
        try:
            t, d = nxt.split(",")[0], float(nxt.split(",")[1])       # "TURN_RIGHT,250.0" → ("TURN_RIGHT", 250.0)
        except (ValueError, IndexError):
            t, d = None, float("inf")                                 # "null,null"(경로 없음) → 판정 안 함
        tbt_right, tbt_d = (t == "TURN_RIGHT"), d
        if PRE_ENABLED and t == "TURN_RIGHT" and d <= 300 and not case1["pre_alerted"] and now - case1["pre_time"] > PRE_GAP:
            trigger("C1_PRE", f"(내비 {d:.0f}m)")
            case1["pre_alerted"] = True
            case1["pre_time"] = now                          # 예고 시각 기록
        elif t != "TURN_RIGHT":
            case1["pre_alerted"] = False                     # 다른 회전으로 바뀌면 초기화
    if tbt_right and tbt_d <= PREP_NEAR and loc and head not in (None, "none") and not case1["alerted"]:
        p_lat, p_lon = map(float, loc.split(","))
        prepare(p_lat, p_lon, float(head), tbt_d, acc)      # 미리 판정 (회전마다 1번)
 
    # 안내 후 회전 없이 150m 넘게 이동했거나 30초가 지나면 해제
    if case1["alerted"] and case1.get("alert_pos") and loc:
        a_lat, a_lon = case1["alert_pos"]                    # 안내했던 위치
        c_lat, c_lon = map(float, loc.split(","))            # 현재 위치
        moved = dist_m(a_lat, a_lon, c_lat, c_lon)           # 안내 위치 → 현재 위치 거리(m)
        if moved > 150 or time.time() - case1["alert_time"] > 30:   # 80 → 150m (미리 판정으로 100m 앞에서 안내하므로)
            print(f"--- C1 안내 해제 (이동 {moved:.0f}m, 회전 확정 없음)")
            case1.update(alerted=False, start_heading=None, alert_pos=None)
 
    # ② 우회전 예정(내비 우회전 100m 이내) + 우측 깜박이 + 정면/오른쪽 50m 이내 횡단보도
    if turn == "RIGHT" and speed > 0 and loc and head not in (None, "none") and not case1["alerted"] and not case1.get("wait_off"):
        lat, lon = map(float, loc.split(","))
        h = float(head)
        tbt_ok = tbt_right and tbt_d <= TBT_NEAR             # 내비도 곧 우회전이라고 함
        hits = []                                            # 앞쪽·오른쪽 횡단보도를 모두 모아 규칙을 함께 안내
        for cw in CW.nearby(lat, lon, radius_m=50 + acc):    # 반경 (50m + GPS 오차) 안 횡단보도, 가까운 순
            side = side_of(lat, lon, cw, h)                  # 앞쪽 / 오른쪽 / None
            tier = gps_tier(cw["dist_m"], acc, 50)           # 확정 / 가능성 / 판정 보류
            if side in ("앞쪽", "오른쪽") and tier in ("확정", "가능성"):
                hits.append((cw, side, tier))
        if tbt_ok and prep["sides"]:                         # 미리 판정된 회전 → 준비된 문장 바로 안내
            print(f"\n--- Case 판정: C1_STOP{suffix(prep['sides'])} (깜박이 + 내비 우회전 {tbt_d:.0f}m, 미리 판정 사용)")
            fire_prepared("C1_STOP")
            case1.update(alerted=True, start_heading=h, alert_pos=(lat, lon), alert_time=time.time(), wait_off=True)
            last_right["pre"] = now
        elif tbt_ok and hits:                                # 내비 우회전 100m 이내일 때만 (깜박이만으로는 안내 안 함: 차로 변경 오안내 방지)
            cw, side, tier = hits[0]                         # 가장 가까운 것
            sides = {x[1] for x in hits}
            why = f"깜박이 + 내비 우회전 {tbt_d:.0f}m"          # 근거 2개
            fire("C1_STOP", sides, f"({cw['road']} 횡단보도 {cw['id']} {cw['dist_m']:.0f}m 외 {len(hits)-1}곳, GPS ±{acc:.0f}m → {tier}, 근거: {why})")
            case1.update(alerted=True, start_heading=h, alert_pos=(lat, lon), alert_time=time.time(), wait_off=True)  # 위치·시각 기록, 깜박이 OFF 전 재안내 금지
            last_right["pre"] = now                          # 사전 안내했으니 사후 안내 생략

    # ②-b 횡단보도 접근 이력 기록 (사후 감지용) + 내비 우회전인데 깜박이 OFF면 사전 안내
    if speed > 5 and loc and head not in (None, "none"):    # 깜박이 RIGHT여도 기록 (내비 없는 깜박이 우회전 사후 안내용)
        lat, lon = map(float, loc.split(","))
        h = float(head)
        tbt_ok = tbt_right and tbt_d <= TBT_NEAR
        hits = []
        for cw in CW.nearby(lat, lon, radius_m=50 + acc):
            side = side_of(lat, lon, cw, h)
            tier = gps_tier(cw["dist_m"], acc, 50)
            if tier not in ("확정", "가능성"):
                continue
            if side == "앞쪽" or (side == "오른쪽" and turn == "RIGHT"):   # 오른쪽은 깜박이 켰을 때만 (직진 중 옆 골목 횡단보도 제외)
                approach.append((now, cw["id"], cw["road"], h, side))
            if side in ("앞쪽", "오른쪽"):
                hits.append((cw, side))
        if turn != "RIGHT" and tbt_right and tbt_d <= SIG_DUE and prep["sides"] and not case1["alerted"]:   # 미리 판정 사용
            print(f"\n--- Case 판정: A1_STOP_NOSIG{suffix(prep['sides'])} (내비 우회전 {tbt_d:.0f}m, 깜박이 OFF, 미리 판정 사용)")
            fire_prepared("A1_STOP_NOSIG")
            case1.update(alerted=True, start_heading=h, alert_pos=(lat, lon), alert_time=now)
            last_right["pre"] = now
        elif turn != "RIGHT" and tbt_right and tbt_d <= SIG_DUE and hits and not case1["alerted"]:   # 30m 안인데도 깜박이 OFF일 때만 (100m~30m 구간은 아직 켤 시간)
            cw, side = hits[0]
            sides = {x[1] for x in hits}
            fire("A1_STOP_NOSIG", sides, f"({cw['road']} 횡단보도 {cw['id']} {cw['dist_m']:.0f}m, 내비 우회전 {tbt_d:.0f}m, 깜박이 OFF → 방향지시등 켜기 안내 포함)")
            case1.update(alerted=True, start_heading=h, alert_pos=(lat, lon), alert_time=now)
            last_right["pre"] = now                          # 이미 사전 안내했으니 이번 회전의 사후 안내는 생략
    while approach and now - approach[0][0] > NOSIG_WINDOW:
        approach.popleft()                                   # 30초 지난 기록 삭제

    # ②-c 사전 안내 없이 우회전 완료 감지 → 사후 안내 (깜박이 켰으면 A1_POST_SIG, 안 켰으면 A1_POST_NOSIG)
    if approach and head not in (None, "none") and now - last_right["pre"] > NOSIG_WINDOW and case1["start_heading"] is None:
        h = float(head)
        for t0, cid, road, h0, side in approach:
            change = (h - h0) % 360                          # 시계방향 변화량
            if 60 <= change <= 120 and prep["tp"] is not None and not prep["sides"] and loc \
                    and dist_m(*prep["tp"], *map(float, loc.split(","))) < 80:
                # 내비로 미리 판정한 회전인데 '회전 지점 주변 횡단보도 없음'이었으면 사후 안내도 안 함 (사전·사후 기준 통일)
                print(f"--- 우회전 감지 (방향 {h0:.0f}° → {h:.0f}°): 미리 판정 결과 횡단보도 없음 → 사후 안내 생략")
                for e in approach:
                    post_done[e[1]] = now
                approach.clear()
                prep.update(tp=None, sides=set(), texts={}, busy=False)
                last_right["t"] = 0.0
                break
            if 60 <= change <= 120 and now - post_done.get(cid, 0) > 300:   # 우회전 + 같은 횡단보도 5분 내 반복 금지
                sides = {e[4] for e in approach if now - e[0] <= NOSIG_WINDOW}
                if now - last_right["t"] <= NOSIG_WINDOW:    # 깜박이는 켰지만 내비가 없어 미리 판단 못 함
                    fire("A1_POST_SIG", sides, f"({road} 횡단보도 {cid} 부근 우회전, 깜박이 ON·내비 경로 없음 → 사후 안내, 다음 우회전 때 일시정지 확인)")
                else:
                    fire("A1_POST_NOSIG", sides, f"({road} 횡단보도 {cid} 앞 우회전, 방향지시등 미점등 → 사후 교육 안내)")
                print(f"--- 사전 안내 없는 우회전 감지 (방향 {h0:.0f}° → {h:.0f}°)")
                for e in approach:
                    post_done[e[1]] = now                    # 이번 교차로 횡단보도 모두 처리
                last_right["t"] = 0.0                        # 깜박이 기록 정리 (다음 회전에 넘어가지 않게)
                approach.clear()                             # 이번 회전 기록 정리
                prep.update(tp=None, sides=set(), texts={}, busy=False)   # 다음 회전은 새로 미리 판정
                break

    # ③ 우회전 확정: 진행 방향이 시계방향으로 60~120° 바뀜
    if case1["start_heading"] is not None and head not in (None, "none"):
        change = (float(head) - case1["start_heading"]) % 360
        if 60 <= change <= 120:
            print(f"--- 우회전 확정 (방향 {case1['start_heading']:.0f}° → {float(head):.0f}°)")
            case1.update(pre_alerted=False, alerted=False, start_heading=None, alert_pos=None, pre_time=0.0)   # 회전 완료 → 다음 회전 예고는 바로 가능
            latest.pop("navi_next_turn", None)               # 지나간 회전 정보 삭제 (새 TBT가 오면 다시 판정)
            for e in approach:
                post_done[e[1]] = time.time()                # 사전 안내로 처리한 횡단보도 → 사후 안내 대상에서 제외
            approach.clear()                                 # 이번 회전의 접근 기록 정리 (30초 뒤 사후 안내 중복 방지)
            last_right["t"] = 0.0                            # 이번 회전의 깜박이 기록은 여기까지 (다음 회전에 넘어가지 않게)
            prep.update(tp=None, sides=set(), texts={}, busy=False)   # 다음 회전은 새로 미리 판정
 
    # 깜빡이 OFF: 다음 깜빡이부터 다시 안내 가능 / 회전하지 않았으면 안내 상태도 초기화 (차로 변경 등)
    if turn == "OFF":
        case1["wait_off"] = False                            # 깜박이 재조작 확인
        if case1["start_heading"] is None:
            case1["alerted"] = False