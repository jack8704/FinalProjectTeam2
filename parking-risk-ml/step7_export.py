import json, pandas as pd
from config import PROC

r = pd.read_parquet(f"{PROC}/risk_2026.parquet")

lookup = {}
for row in r[r["grade"] != "하"].itertuples():
    lookup.setdefault(row.cell, {})[f"{row.dow}-{row.hour}"] = row.grade

out = {"cells": sorted(r["cell"].unique().tolist()),
      "risk": lookup}
with open(f"{PROC}/risk_2026.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print("격자:", len(out["cells"]), "| 상·중 슬롯:", sum(len(v) for v in lookup.values()))
