# find_near.py — 보라매로 근처 소화전·횡단보도·버스정류장 좌표 찾기 (Case 2 테스트 좌표 정하기용)
# 실행: source 폴더에서  python find_near.py
from facility import FacilityDB                              # server와 같은 시설 DB 사용

CENTER = (37.4930, 126.92699)                                # 보라매로 테스트 구간 중심 (Case 1 GPX 근처)
RADIUS = 300                                                 # 반경 300m 안에서 찾기

for path, name in (("data/fac_hydrant.csv", "소화전"), ("data/fac_crosswalk.csv", "횡단보도"), ("data/fac_busstop.csv", "버스정류장")):
    db = FacilityDB(path, name)
    near = db.nearby(CENTER[0], CENTER[1], radius_m=RADIUS)  # 가까운 순 목록
    print(f"\n[{name}] 반경 {RADIUS}m 안 {len(near)}개 (가까운 5개)")
    for f in near[:5]:
        print(f"  {f.get('id')}  {f['lat']:.6f},{f['lon']:.6f}  중심에서 {f['dist_m']:.0f}m  {f.get('road', '')}")