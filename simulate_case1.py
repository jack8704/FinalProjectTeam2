"""Case 1 (우회전 횡단보도) 시뮬레이션 — 보라매로 GPX와 같은 경로를 서버에 직접 보냄
사용법:  python simulate_case1.py 1      (시나리오 번호 1~5)
  1. 깜박이 + 내비 우회전          → C1_PRE, C1_STOP_F (회전 전, 52m 지점에선 전방 횡단보도만 잡힘)
  2. 깜박이 없음 + 내비 우회전     → C1_PRE, A1_STOP_NOSIG_F (회전 30m 전까지 깜박이 안 켜면)
  3. 깜박이만 (내비 없음)          → A1_POST_SIG_B (회전 후)
  4. 깜박이·내비 둘 다 없음        → A1_POST_NOSIG_F (회전 후)
  5. 깜박이 + 직진 (차로 변경)     → 안내 없음
⚠ 사후 안내(3·4)는 같은 횡단보도 5분에 1번 → 3 다음 4를 하려면 main 서버 재시작 또는 5분 대기
"""
import sys, time, math, requests

URL = "http://127.0.0.1:8000/signal"                         # main 서버
STEP = 0.5                                                   # 위치 간격(초) — 실제 1초를 절반으로 줄여 시연 단축
TURN = (37.492280, 126.926986)                               # 우회전 지점 (횡단보도 3859 부근)

def send(t, v):
    requests.post(URL, json={"type": t, "value": str(v), "ts": int(time.time() * 1000)})   # 앱과 같은 형식

def dist(a, b):                                              # 두 좌표 거리(m)
    dy = (a[0] - b[0]) * 111320
    dx = (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)

def head(a, b):                                              # a→b 진행 방향(°)
    y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0]))
    x = math.cos(math.radians(a[0])) * math.sin(math.radians(b[0])) - \
        math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1]))
    return (math.degrees(math.atan2(y, x)) + 360) % 360

# 경로: 남쪽으로 직진(약 1.3초에 8m) → 우회전 → 서쪽으로 진행 (case1_boramae_right_turn.gpx와 동일)
south = [(37.493500 - 0.000075 * i, 126.926986) for i in range(17)]     # 37.4935 → 37.4923 (약 135m)
west = [(37.492280, 126.926891 - 0.0000945 * i) for i in range(12)]      # 회전 후 서쪽 약 100m
STRAIGHT = south + [(37.492205 - 0.000075 * i, 126.926986) for i in range(12)]   # 시나리오 5: 회전 없이 계속 남쪽

def drive(path, blinker_at=None, navi=False, turn_idx=None):
    """path를 따라 이동. blinker_at: 회전 지점까지 남은 거리(m)가 이 값 이하가 되면 깜박이 RIGHT
       turn_idx: path에서 회전이 시작되는 위치 번호 (None이면 회전 없음)"""
    send("gear", "GEAR_DRIVE"); send("speed_kmh", 30); send("gps_accuracy", 5)
    send("turn_signal", "OFF")
    send("navi_next_turn", "null,null")                      # 이전 내비 정보 지우기
    on = False
    for i in range(1, len(path)):
        a, b = path[i - 1], path[i]
        before = turn_idx is None or i < turn_idx            # 아직 회전 전인지
        d_turn = dist(b, TURN) if before else 0              # 회전 지점까지 남은 거리
        if navi:
            send("navi_next_turn", f"TURN_RIGHT,{d_turn:.1f}" if before else "null,null")   # 회전 후엔 내비 정보 없음
        if blinker_at is not None and not on and before and d_turn <= blinker_at:
            send("turn_signal", "RIGHT"); on = True
            print(f"   깜박이 RIGHT (회전까지 {d_turn:.0f}m)")
        if on and turn_idx is not None and i >= turn_idx + 3:   # 회전 후 3칸(약 25m) 가면 깜박이 OFF
            send("turn_signal", "OFF"); on = False
            print("   깜박이 OFF (회전 완료)")
        send("gps_speed_kmh", 30)
        send("heading", f"{head(a, b):.0f}")
        send("location", f"{b[0]:.6f},{b[1]:.6f}")           # 위치를 마지막에 보내 판정
        print(f"   {i:2d} 위치 {b[0]:.6f},{b[1]:.6f} 방향 {head(a, b):3.0f}° 회전까지 {d_turn:5.0f}m")
        time.sleep(STEP)
    send("speed_kmh", 0); send("turn_signal", "OFF")

T = len(south)                                               # 회전 시작 위치 번호
n = sys.argv[1] if len(sys.argv) > 1 else "1"
title = {"1": "깜박이 + 내비 우회전 → C1_PRE, C1_STOP_F",
         "2": "깜박이 없음 + 내비 우회전 → C1_PRE, A1_STOP_NOSIG_F (30m 전)",
         "3": "깜박이만 (내비 없음) → 회전 후 A1_POST_SIG_B",
         "4": "깜박이·내비 없음 → 회전 후 A1_POST_NOSIG_F",
         "5": "깜박이 + 직진 (차로 변경) → 안내 없음"}[n]
print(f"\n===== 시나리오 {n}: {title} =====")
if n == "1": drive(south + west, blinker_at=60, navi=True, turn_idx=T)
if n == "2": drive(south + west, navi=True, turn_idx=T)
if n == "3": drive(south + west, blinker_at=60, turn_idx=T)
if n == "4": drive(south + west, turn_idx=T)
if n == "5": drive(STRAIGHT, blinker_at=60)              # 회전 없음 → 깜박이 계속 켜진 채 직진
print("완료 — main 서버 콘솔에서 '>>> [안내' 줄 확인")
