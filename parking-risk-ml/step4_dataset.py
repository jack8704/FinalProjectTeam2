import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score
from config import PROC, NAME

df = pd.read_parquet(f"{PROC}/cell.parquet")
if NAME != "report":
    df = df[df["dt"].dt.strftime("%H:%M:%S") != "00:00:00"]
df["week"] = df["dt"].dt.to_period("W").astype(str)
KEY = ["cell", "dow", "hour"]

def slot_rate(d, name):
    n_weeks = d["week"].nunique()
    return (d.groupby(KEY)["week"].nunique() / n_weeks).rename(name)

def make(f_start, f_end, l_start, l_end):
    f = df[(df["dt"] >= f_start) & (df["dt"] < f_end)]
    l = df[(df["dt"] >= l_start) & (df["dt"] < l_end)]

    cells = f[["cell", "gx", "gy", "gu"]].drop_duplicates("cell")
    X = (cells.merge(pd.DataFrame({"dow": range(7)}), how="cross")
            .merge(pd.DataFrame({"hour": range(24)}), how="cross"))

    recent = f[f["dt"] >= pd.Timestamp(f_end) - pd.DateOffset(months=6)]
    X = X.join(slot_rate(f, "hist_rate"), on=KEY)
    X = X.join(slot_rate(recent, "recent_rate"), on=KEY)
    X = X.join(f.groupby("cell").size().rename("cell_total"), on="cell")

    tot = f.groupby(["gx", "gy"]).size().rename("n").reset_index()
    nb = pd.concat([tot.assign(gx=tot.gx + dx, gy=tot.gy + dy)
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)])
    nb = nb.groupby(["gx", "gy"])["n"].sum().rename("nb_total")
    X = X.join(nb, on=["gx", "gy"])

    h = slot_rate(f, "r").reset_index()
    for dh in (-1, 1):
        s = h.assign(hour=h["hour"] - dh).set_index(KEY)["r"]
        X = X.join(s.rename(f"rate_h{dh:+d}"), on=KEY)

    wk = (f.groupby(["cell", "hour"])["week"].nunique() / f["week"].nunique()).rename("rate_allday")
    X = X.join(wk, on=["cell", "hour"])

    hg = h.merge(cells[["cell", "gx", "gy"]], on="cell")
    nbs = pd.concat([hg.assign(gx=hg.gx + dx, gy=hg.gy + dy)
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)])
    nbs = nbs.groupby(["gx", "gy", "dow", "hour"])["r"].sum().rename("nb_slot_rate")
    X = X.join(nbs, on=["gx", "gy", "dow", "hour"])

    rec3 = f[f["dt"] >= pd.Timestamp(f_end) - pd.DateOffset(months=3)]
    X = X.join(slot_rate(rec3, "recent3_rate"), on=KEY)

    X = X.join(slot_rate(l, "y_rate"), on=KEY)
    num_cols = X.select_dtypes("number").columns
    X[num_cols] = X[num_cols].fillna(0)
    X["gu"] = X["gu"].fillna("미상")
    X["trend"] = X["recent_rate"] / (X["hist_rate"] + 0.01)

    X["label"] = (X["y_rate"] >= 0.1).astype(int)
    return X

if __name__ == "__main__":
    train = make("2021-10-01", "2024-01-01", "2024-01-01", "2025-01-01")
    test  = make("2022-10-01", "2025-01-01", "2025-01-01", "2026-01-01")

    for name, d in [("train", train), ("test", test)]:
        print(f"{name}: {len(d):,}행, 정답(1) 비율 {d['label'].mean():.3f}")

    print("\n[베이스라인] 과거빈도만 사용")
    print("AUC:", round(roc_auc_score(test["label"], test["hist_rate"]), 4))
    print("PR-AUC:", round(average_precision_score(test["label"], test["hist_rate"]), 4))

    train.to_parquet(f"{PROC}/train.parquet", index=False)
    test.to_parquet(f"{PROC}/test.parquet", index=False)
