import numpy as np, pandas as pd, lightgbm as lgb
from step4_dataset import make
from config import PROC, NAME

FEATS = ["dow", "hour", "hist_rate", "recent_rate", "recent3_rate", "trend",
         "rate_h-1", "rate_h+1", "rate_allday", "nb_slot_rate",
         "cell_total", "nb_total"]
CUTS = {"상": 0.01, "중": 0.05}

def grade(score):
    q_hi = np.quantile(score, 1 - CUTS["상"])
    q_mid = np.quantile(score, 1 - CUTS["중"])
    return np.where(score >= q_hi, "상", np.where(score >= q_mid, "중", "하"))

test = pd.read_parquet(f"{PROC}/test.parquet")
v3 = lgb.Booster(model_file=f"{PROC}/lgbm_eval.txt")
test["grade"] = grade(v3.predict(test[FEATS]))
print("[2025 테스트] 등급별 실제 단속률 (라벨=1 비율):")
print(test.groupby("grade")["label"].agg(["mean", "size"]).round(3))

train = pd.read_parquet(f"{PROC}/train.parquet")
full = pd.concat([train, test], ignore_index=True)
y = np.ascontiguousarray(full["label"].to_numpy(dtype=np.float32))

final = lgb.LGBMClassifier(
    n_estimators=470 if NAME != "report" else 300,
    learning_rate=0.02,
    num_leaves=31, min_child_samples=500, reg_lambda=1.0,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
    random_state=42, verbose=-1)
final.fit(full[FEATS], y)
final.booster_.save_model(f"{PROC}/lgbm_final.txt")
del train, test, full

pred = make("2023-10-01", "2026-01-01", "2026-01-01", "2027-01-01")
pred["score"] = final.predict_proba(pred[FEATS])[:, 1]
pred["grade"] = grade(pred["score"].to_numpy())

pred["lat"] = 37.41 + (pred["gy"] + 0.5) * 0.0009
pred["lon"] = 126.76 + (pred["gx"] + 0.5) * 0.00113

out = pred[["cell", "gx", "gy", "lat", "lon", "dow", "hour", "score", "grade"]]
out.to_parquet(f"{PROC}/risk_2026.parquet", index=False)

print("\n[2026 예측] 등급 분포:\n", out["grade"].value_counts())
print("격자 수:", out["cell"].nunique(), "| 행 수:", len(out))
print("\n'상' 등급이 가장 많은 시간대 TOP5:\n",
      out[out["grade"] == "상"]["hour"].value_counts().head())
