import pandas as pd, numpy as np, lightgbm as lgb
from sklearn.metrics import roc_auc_score, average_precision_score
from config import PROC

train = pd.read_parquet(f"{PROC}/train.parquet")
test  = pd.read_parquet(f"{PROC}/test.parquet")

rng = np.random.default_rng(42)
cells = train["cell"].unique()
val_cells = rng.choice(cells, size=len(cells) // 10, replace=False)
is_val = train["cell"].isin(val_cells)
tr, va = train[~is_val].copy(), train[is_val].copy()

y_tr = np.ascontiguousarray(tr["label"].to_numpy(dtype=np.float32))
y_va = np.ascontiguousarray(va["label"].to_numpy(dtype=np.float32))

FEATS = ["dow", "hour", "hist_rate", "recent_rate", "recent3_rate", "trend",
        "rate_h-1", "rate_h+1", "rate_allday", "nb_slot_rate",
        "cell_total", "nb_total"]

model = lgb.LGBMClassifier(
    n_estimators=3000, learning_rate=0.02,
    num_leaves=31, min_child_samples=500,
    reg_lambda=1.0,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
    verbose=-1)

model.fit(tr[FEATS], y_tr,
          eval_set=[(va[FEATS], y_va)],
          eval_metric="average_precision",
          callbacks=[lgb.early_stopping(200), lgb.log_evaluation(100)])

def report(name, score):
    top = test.assign(s=score).nlargest(int(len(test) * 0.01), "s")
    print(f"{name:10s} AUC {roc_auc_score(test['label'], score):.4f} | "
          f"PR-AUC {average_precision_score(test['label'], score):.4f} | "
          f"상위1% 적중률 {top['label'].mean():.3f}")

p = model.predict_proba(test[FEATS])[:, 1]
report("베이스라인", test["hist_rate"])
report("LightGBM", p)

imp = pd.Series(model.booster_.feature_importance("gain"), index=FEATS).sort_values(ascending=False)
print("\n피처 중요도(gain):\n", (imp / imp.sum()).round(3))

model.booster_.save_model(f"{PROC}/lgbm_eval.txt")
