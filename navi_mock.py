"""navi_mock.py — 에뮬레이터 내비가 GPX를 따라가지 않아 TBT가 멈춰 있으므로, 내비 TBT만 대신 보냄 (시연·테스트용)
  - 위치·방향·깜박이·기어는 에뮬레이터 GPX + SoloM 앱이 그대로 보냄
  - 이 스크립트는 /latest 의 현재 위치를 읽어 회전 지점까지 거리를 계산 → navi_next_turn 으로 전송
사용법:  python navi_mock.py 경로.gpx   (GPX에서 회전 지점을 자동으로 찾음, GPX 재생 전에 먼저 실행, Ctrl+C로 종료)
         python navi_mock.py            (GPX 없이 실행 → 아래 TURNS 기본값 사용)
시연용 TBT 모의 입력 (실차는 내비 TBT 사용)
"""
import sys, re, time, math, requests

SERVER = "http://127.0.0.1:8000"
PERIOD = 0.5                                                 # 0.5초마다 위치 확인
RESEND = 2.0                                                 # 값이 같아도 2초마다 다시 전송 (앱이 보내는 멈춘 TBT 값을 덮어씀)
ANNOUNCE = 300                                               # 회전 지점 300m 안부터 TBT 전송 (실제 내비 예고 거리와 비슷하게)
PASSED = 10                                                  # 회전 지점 10m 안에 들어갔다가 멀어지면 '지나감'

# 경로상 회전 지점 (GPX 순서대로) — 보라매로 우회전 (case1_boramae_right_turn.gpx, codriver_all_cases_v3.gpx 공통)
TURNS = [
    ("TURN_RIGHT", 37.492280, 126.926986),
]

def dist(lat1, lon1, lat2, lon2):                            # 두 좌표 거리(m)
    dy = (lat1 - lat2) * 111320
    dx = (lon1 - lon2) * 111320 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)

def bearing(a, b):                                           # a→b 진행 방향(°)
    y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0]))
    x = math.cos(math.radians(a[0])) * math.sin(math.radians(b[0])) - \
        math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1]))
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def turns_from_gpx(path, span=30):
    """GPX에서 회전 지점 자동 추출: 앞뒤 약 30m 구간의 방향이 60~120° 바뀐 곳
       시계방향 = TURN_RIGHT, 반시계방향 = TURN_LEFT"""
    pts = [(float(a), float(b)) for a, b in re.findall(r'lat="([-\d.]+)"\s+lon="([-\d.]+)"', open(path, encoding="utf-8").read())]
    pts = [p for i, p in enumerate(pts) if i == 0 or dist(*p, *pts[i - 1]) > 0.5]   # 정차 중 같은 좌표 제거
    found = []
    for i in range(1, len(pts) - 1):
        j = i                                                # 뒤로 span m 떨어진 점
        while j > 0 and dist(*pts[i], *pts[j]) < span: j -= 1
        k = i                                                # 앞으로 span m 떨어진 점
        while k < len(pts) - 1 and dist(*pts[i], *pts[k]) < span: k += 1
        if j == i or k == i:
            continue
        ch = (bearing(pts[i], pts[k]) - bearing(pts[j], pts[i]) + 540) % 360 - 180   # 방향 변화 (+ 시계, - 반시계)
        if 60 <= abs(ch) <= 120:
            found.append((abs(ch), i, "TURN_RIGHT" if ch > 0 else "TURN_LEFT"))
    turns, used = [], []                                     # 같은 회전이 여러 점에서 잡히면 변화가 가장 큰 점 1개만
    for ch, i, kind in sorted(found, reverse=True):
        if all(dist(*pts[i], *pts[u]) > 2 * span for u in used):
            used.append(i)
    for i in sorted(used):                                   # GPX 순서대로
        kind = next(k for c, n, k in found if n == i)
        turns.append((kind, pts[i][0], pts[i][1]))
    return turns

def send(value):
    requests.post(f"{SERVER}/signal", json={"type": "navi_next_turn", "value": value, "ts": int(time.time() * 1000)})

if len(sys.argv) > 1:
    TURNS = turns_from_gpx(sys.argv[1])                      # GPX에서 회전 지점 자동 추출
    m = re.search(r'lat="([-\d.]+)"\s+lon="([-\d.]+)"', open(sys.argv[1], encoding="utf-8").read())
    START = (float(m.group(1)), float(m.group(2)))            # GPX 출발점 (다시 재생 감지용)
    print(f"{sys.argv[1]} 에서 회전 {len(TURNS)}개 찾음:")
    for kind, la, lo in TURNS:
        print(f"   {kind}  {la:.6f},{lo:.6f}")
    if not TURNS:
        print("   회전 없음 → navi_next_turn 은 계속 null,null")

START = globals().get("START")                               # GPX 없이 실행하면 None
left_start = False                                           # 출발점에서 한 번 벗어났는지
idx, near, last_sent, last_loc, last_t = 0, False, None, None, 0.0        # 다음 회전 번호, 10m 안에 들어왔었는지, 마지막 전송값, 마지막 위치
print("navi_mock 시작 — GPX를 재생하세요 (Ctrl+C 종료)")
while True:
    try:
        loc = requests.get(f"{SERVER}/latest", timeout=2).json().get("location")
    except Exception as e:
        print("서버 연결 실패:", e); time.sleep(2); continue
    if loc and loc != "none":
        lat, lon = map(float, loc.split(","))
        if idx < len(TURNS):
            kind, tl, tn = TURNS[idx]
            d = dist(lat, lon, tl, tn)                       # 회전 지점까지 남은 거리
            if d <= PASSED:
                near = True                                  # 회전 지점 도착
            elif near:                                       # 도착했다가 다시 멀어짐 → 이 회전은 지나감
                print(f"   회전 {idx + 1} 통과"); idx, near = idx + 1, False
                continue
            if near:
                value = "null,null"                          # 회전 중에는 TBT 없음 (회전 확정 후 예고가 다시 나가지 않게)
            else:
                value = f"{kind},{d:.1f}" if d <= ANNOUNCE else "null,null"   # 300m 밖이면 '다음 회전 없음'
        else:
            value = "null,null"                              # 모든 회전 지남
        if value != last_sent or time.time() - last_t >= RESEND:   # 값이 바뀌었거나 2초 지났을 때만 전송 (서버 로그 줄이기)
            send(value)
            last_t = time.time()
        if value != last_sent:
            print(f"   위치 {lat:.6f},{lon:.6f} → navi_next_turn = {value}")
            last_sent = value
        if START:
            d0 = dist(lat, lon, *START)                      # 출발점까지 거리
            if d0 > 30:
                left_start = True
            elif d0 <= 10 and left_start:                    # 출발점에 다시 돌아옴 = GPX 다시 재생 → 회전 목록 초기화
                print("   GPX 출발점 재진입 → 처음부터"); idx, near, left_start = 0, False, False
        if last_loc:
            p_lat, p_lon = last_loc
            if dist(lat, lon, p_lat, p_lon) > 100:           # 0.5초에 100m 넘게 이동 = GPX를 처음부터 다시 재생 → 회전 목록 초기화
                print("   위치 점프 감지 → 처음부터"); idx, near = 0, False
        last_loc = (lat, lon)
    time.sleep(PERIOD)