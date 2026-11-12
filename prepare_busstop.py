# prepare_busstop.py — 국토교통부 전국 버스정류장 위치정보 CSV → data/fac_busstop.csv (FacilityDB 형식)
# 실행: source 폴더에서  python prepare_busstop.py data/raw/전국버스정류장.csv
import sys
import pandas as pd
 
src = sys.argv[1] if len(sys.argv) > 1 else "data/raw/전국버스정류장.csv"   # 내려받은 원본 경로
OUT = "data/fac_busstop.csv"
 
raw = None
for enc in ("utf-8-sig", "cp949"):                           # 공공데이터 CSV는 둘 중 하나인 경우가 많음
    try:
        raw = pd.read_csv(src, encoding=enc, dtype=str); break
    except UnicodeDecodeError:
        continue
if raw is None:
    sys.exit("인코딩을 읽지 못했습니다 (utf-8 / cp949 아님)")
 
df = raw.rename(columns={"정류장번호": "id", "정류장명": "road", "위도": "lat", "경도": "lon",
                         "도시명": "gu", "관리도시명": "src"})   # FacilityDB가 쓰는 열 이름으로 (road = 안내에 쓸 이름)
df = df[["id", "road", "lat", "lon", "gu", "src"]]
df["lat"] = pd.to_numeric(df["lat"], errors="coerce")        # 숫자로 변환 (문자·빈칸 → NaN)
df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
before = len(df)
df = df.dropna(subset=["lat", "lon"])                        # 좌표 빈칸 제거
df = df[df.lat.between(33, 39) & df.lon.between(124, 132)]   # 한국 범위 밖(0, 위경도 뒤바뀜 등) 제거
df = df.drop_duplicates(subset=["lat", "lon"])               # 같은 좌표 중복 제거
df.to_csv(OUT, index=False, encoding="utf-8-sig")
 
print(f"{src} → {OUT}: {before}행 → {len(df)}행 (도시 {df.gu.nunique()}곳)")
seoul = df[df.gu.str.contains("서울", na=False)]
print(f"서울 {len(seoul)}개 · 동작구/관악구 여부는 find_near.py로 확인")