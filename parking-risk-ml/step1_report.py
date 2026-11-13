import pandas as pd
from pathlib import Path
from config import PROC

def load(path):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949", errors="replace")
    n_nul = text.count("\x00")
    text = text.replace("\x00", "")

    rows, bad = [], 0
    for line in text.splitlines()[1:]:
        p = line.split(",")
        if len(p) < 5:
            bad += 1
            continue
        rows.append((p[0], p[1], p[-2], p[-1]))

    print(f"  {path.name}: {len(rows):,}행 | 버린 줄 {bad:,} | NUL 제거 {n_nul:,}")
    return pd.DataFrame(rows, columns=["date", "time", "경도", "위도"])

dfs = []
for f in sorted(Path("data/raw/seoul_report").glob("*.csv")):
    d = load(f)
    d = d.apply(lambda s: s.str.strip().str.strip('"'))
    dfs.append(d)

df = pd.concat(dfs, ignore_index=True)
date = df["date"].str.replace(r"\D", "", regex=True).str[:8]
df["dt"] = pd.to_datetime(date + " " + df["time"].str.strip(),
                          format="%Y%m%d %H:%M:%S", errors="coerce")
df["경도"] = pd.to_numeric(df["경도"], errors="coerce")
df["위도"] = pd.to_numeric(df["위도"], errors="coerce")
df["gu"] = "서울"

bad = df[df["dt"].isna()]
print("전체:", len(df), "| 날짜 변환 실패:", len(bad), "| 좌표 결측:", df[["경도", "위도"]].isna().any(axis=1).sum())
print("변환 실패 예시:\n", bad[["date", "time"]].head())
print("기간:", df["dt"].min(), "~", df["dt"].max())

Path(PROC).mkdir(parents=True, exist_ok=True)
df[["dt", "경도", "위도", "gu"]].to_parquet(f"{PROC}/base.parquet", index=False)
