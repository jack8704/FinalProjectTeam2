# check_risk_spot.py — 시연 정차 지점이 법규 금지 구역에 걸리지 않는지 + 예측 결과 확인 (main 서버 폴더에서 실행)
import os, sys
os.environ.setdefault("RISK_DEMO_TIME", "0-9")
from core import HYD, CW, BUS                     # 서버와 같은 소화전·횡단보도·버스정류장 DB
import risk_lookup as R
R.DEMO_TIME = os.environ["RISK_DEMO_TIME"]
lat, lon = (float(x) for x in sys.argv[1:3]) if len(sys.argv) > 2 else (37.49145, 126.924415)   # 기본 = GPX 정차 지점
for name, db, limit in (("소화전", HYD, 5), ("횡단보도", CW, 10), ("버스정류장", BUS, 10)):
    near = db.nearby(lat, lon, radius_m=60)       # 60m 안 시설
    d = near[0]["dist_m"] if near else None
    ok = d is None or d - float(near[0].get("length_m") or 0)/2 > limit + 10   # 기준 + GPS 여유 10m
    print(f"{name:6s}: 가장 가까운 {('%.1fm' % d) if d is not None else '60m 안 없음'} → {'OK' if ok else '★ 금지 판정 걸림 → 지점 이동 필요'}")
print("위험 예측:", R.to_key(lat, lon), R.DEMO_TIME, "→", R.parking_risk(lat, lon, acc_m=5)[0])
