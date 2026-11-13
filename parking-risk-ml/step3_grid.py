import pandas as pd
from config import PROC

df = pd.read_parquet(f"{PROC}/base.parquet").dropna(subset=["dt", "경도", "위도"])

t = df["dt"].dt.strftime("%H:%M:%S")
print("정확히 00:00:00 인 건수:", (t == "00:00:00").sum())
print("0시대 전체 건수:", (df["dt"].dt.hour == 0).sum())

df = df[df["위도"].between(37.41, 37.72) & df["경도"].between(126.76, 127.19)]

df["gy"] = ((df["위도"] - 37.41) / 0.0009).astype(int)
df["gx"] = ((df["경도"] - 126.76) / 0.00113).astype(int)
df["cell"] = df["gx"].astype(str) + "_" + df["gy"].astype(str)
df["dow"] = df["dt"].dt.dayofweek
df["hour"] = df["dt"].dt.hour

cell_cnt = df["cell"].value_counts()
print("단속이 1번이라도 있었던 격자 수:", len(cell_cnt))
print("격자당 단속 건수 분포:\n", cell_cnt.describe().round(1))
print("상위 10% 격자가 차지하는 비중:",
      round(cell_cnt.head(len(cell_cnt)//10).sum() / len(df), 3))

df[["cell", "gx", "gy", "dt", "dow", "hour", "gu"]].to_parquet(f"{PROC}/cell.parquet", index=False)
print("저장 완료:", len(df))

print("분 단위 비교:\n", t.value_counts().reindex(["23:59:00", "00:00:00", "00:01:00", "00:02:00"]))
