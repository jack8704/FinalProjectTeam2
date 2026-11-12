"""
시설 위치 원본 CSV(공공데이터) → 판정에 쓸 열만 남긴 정제 파일 3개
  실행: python prepare_facilities.py      (한 번만, 원본이 바뀌면 다시)
  입력: data/raw/ 안의 CSV 아무 이름이나 (열 이름을 보고 종류를 자동 구분)
  출력: data/fac_crosswalk.csv, data/fac_hydrant.csv, data/fac_camera.csv
"""
import glob, os, sys
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")                      # 윈도우 한글 출력
RAW_DIR, OUT_DIR = "data/raw", "data"

# 종류 구분용 열 → (출력 파일, 원본 열 → 표준 열 이름)
KINDS = {
    "횡단보도관리번호": ("fac_crosswalk.csv", {
        "횡단보도관리번호": "id", "위도": "lat", "경도": "lon", "도로명": "road",
        "시군구명": "gu", "차로수": "lanes", "횡단보도연장": "length_m"}),
    "시설유형코드": ("fac_hydrant.csv", {
        "시설번호": "id", "위도": "lat", "경도": "lon", "시설유형코드": "type_code",
        "시군구명": "gu", "상세위치": "detail"}),
    "무인교통단속카메라관리번호": ("fac_camera.csv", {
        "무인교통단속카메라관리번호": "id", "위도": "lat", "경도": "lon", "도로노선명": "road",
        "시군구명": "gu", "단속구분": "enforce_code", "제한속도": "speed_limit", "보호구역구분": "zone_code"}),
}

def read_any(path):
    for enc in ("utf-8-sig", "cp949"):                        # 공공데이터는 둘 중 하나
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            pass
    raise ValueError(f"인코딩을 알 수 없음: {path}")

def clean(df, colmap):
    df = df[list(colmap)].rename(columns=colmap)              # 필요한 열만 + 표준 이름
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")     # 숫자가 아닌 좌표는 빈칸 처리
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["lat", "lon"])                     # 좌표 빈칸 제거
    df = df[df.lat.between(33, 39) & df.lon.between(124, 132)]  # 한국 범위 밖(0, 뒤바뀐 값) 제거
    df = df.drop_duplicates(subset=["lat", "lon"])            # 같은 좌표 중복 제거
    return df.reset_index(drop=True), before

os.makedirs(OUT_DIR, exist_ok=True)                           # data 폴더 없으면 생성
files = glob.glob(os.path.join(RAW_DIR, "*.csv"))             # data/raw 안의 모든 CSV
if not files:
    sys.exit(f"{RAW_DIR} 폴더에 원본 CSV를 넣어주세요.")
for path in files:
    raw = read_any(path)
    kind = next((k for k in KINDS if k in raw.columns), None)  # 열 이름으로 종류 판별
    if not kind:
        print(f"건너뜀 (종류 모름): {path}"); continue
    out_name, colmap = KINDS[kind]
    df, before = clean(raw, colmap)
    df.to_csv(os.path.join(OUT_DIR, out_name), index=False, encoding="utf-8-sig")  # 엑셀에서도 한글 안 깨짐
    print(f"{os.path.basename(path)} → {out_name}: {before}행 → {len(df)}행 (시군구 {df.gu.nunique()}곳)")