import pandas as pd
from pathlib import Path

def load(path, **kw):
    for enc in ["utf-8-sig", "cp949"]:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False, **kw)
        except UnicodeDecodeError:
            continue

seoul_files = sorted(Path("data/raw/seoul").glob("*.csv"))
print("서울 컬럼:", list(load(seoul_files[0], nrows=5).columns))

dfs = []
for f in seoul_files:
    d = load(f)
    d = d[["단속일", "단속시간", "경도", "위도", "구주소"]]
    dfs.append(d)

df = pd.concat(dfs, ignore_index=True)
df["dt"] = pd.to_datetime(df["단속일"].astype("Int64").astype(str) + " " + df["단속시간"],
                          errors="coerce")
df["gu"] = df["구주소"].str.split().str[1]
df = df.drop(columns=["단속일", "단속시간", "구주소"])

print("변환 실패(dt 결측):", df["dt"].isna().sum())
print("좌표 결측:", df[["경도", "위도"]].isna().any(axis=1).sum())
print("기간:", df["dt"].min(), "~", df["dt"].max())
print(df["gu"].value_counts().head(25))

Path("data/processed/enforce").mkdir(parents=True, exist_ok=True)
df.to_parquet("data/processed/enforce/base.parquet", index=False)
print("저장 완료:", len(df), "행")
