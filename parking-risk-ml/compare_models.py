import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import lightgbm as lgb
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier

FEATS = ["dow", "hour", "hist_rate", "recent_rate", "recent3_rate", "trend",
         "rate_h-1", "rate_h+1", "rate_allday", "nb_slot_rate",
         "cell_total", "nb_total"]
KOR = {"enforce": "단속", "report": "신고"}
SAMPLE = 600_000
SEED = 42

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

def top1(y, s):
    k = int(len(s) * 0.01)
    return float(np.asarray(y)[np.argsort(-s)[:k]].mean())

def run(name):
    proc = f"data/processed/{name}"
    train = pd.read_parquet(f"{proc}/train.parquet")
    test = pd.read_parquet(f"{proc}/test.parquet")
    y_te = test["label"].to_numpy()
    print(f"\n===== {KOR[name]} | 학습 {len(train):,}행 (정답1 {train['label'].mean():.2%}) / 테스트 {len(test):,}행 =====")

    rows = []
    def add(model, s, sec):
        rows.append({"모델": model, "PR-AUC": average_precision_score(y_te, s),
                     "ROC-AUC": roc_auc_score(y_te, s), "상위1%적중률": top1(y_te, s),
                     "학습시간(초)": round(sec, 1)})
        print(f"  {model:22s} PR-AUC {rows[-1]['PR-AUC']:.4f} | AUC {rows[-1]['ROC-AUC']:.4f} | 상위1% {rows[-1]['상위1%적중률']:.3f} | {sec:.0f}초")

    add("기준선 (과거 빈도)", test["hist_rate"].to_numpy(), 0)

    pos = train[train["label"] == 1]
    neg = train[train["label"] == 0]
    neg = neg.sample(min(len(neg), SAMPLE - len(pos)), random_state=SEED)
    sm = pd.concat([pos, neg])

    others = {
        "로지스틱 회귀": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
        "랜덤 포레스트": RandomForestClassifier(n_estimators=200, min_samples_leaf=50, n_jobs=-1, random_state=SEED),
    }
    for model, m in others.items():
        t = time.time(); m.fit(sm[FEATS], sm["label"])
        add(model, m.predict_proba(test[FEATS])[:, 1], time.time() - t)

    t = time.time()
    hgb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED)
    hgb.fit(train[FEATS], train["label"])
    add("HistGradientBoosting", hgb.predict_proba(test[FEATS])[:, 1], time.time() - t)

    rng = np.random.default_rng(42)
    cells = train["cell"].unique()
    is_val = train["cell"].isin(rng.choice(cells, size=len(cells) // 10, replace=False))
    tr, va = train[~is_val], train[is_val]
    t = time.time()
    lgbm = lgb.LGBMClassifier(n_estimators=3000, learning_rate=0.02, num_leaves=31, min_child_samples=500,
                              reg_lambda=1.0, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
    lgbm.fit(tr[FEATS], tr["label"].astype(np.float32), eval_set=[(va[FEATS], va["label"].astype(np.float32))],
             eval_metric="average_precision", callbacks=[lgb.early_stopping(200, verbose=False)])
    add("LightGBM (채택)", lgbm.predict_proba(test[FEATS])[:, 1], time.time() - t)

    res = pd.DataFrame(rows).sort_values("PR-AUC", ascending=False)
    res.to_csv(f"model_compare_{name}.csv", index=False, encoding="utf-8-sig")
    draw(res, name)

def draw(res, name):
    order = res.sort_values("PR-AUC")
    best = res.iloc[0]["모델"]
    fig, axes = plt.subplots(1, 3, figsize=(17, 6.4), facecolor="white")
    for ax, col, fmt, title in [(axes[0], "PR-AUC", "{:.3f}", "PR-AUC (주 지표)"),
                                (axes[1], "상위1%적중률", "{:.1%}", "상위 1% 적중률 ('상' 등급 정확도)"),
                                (axes[2], "ROC-AUC", "{:.3f}", "ROC-AUC (참고)")]:
        c = ["#2f6fbf" if m == best else ("#b8b4aa" if "기준선" in m else "#9cc3f0") for m in order["모델"]]
        ax.barh(order["모델"], order[col], color=c, height=0.6)
        for y, v in enumerate(order[col]):
            ax.text(v, y, " " + fmt.format(v), va="center", fontsize=12)
        lo = 0.8 if col == "ROC-AUC" else 0
        ax.set_xlim(lo, lo + (order[col].max() - lo) * 1.22)
        ax.set_title(title, loc="left", fontsize=14)
        for s in ["top", "right"]: ax.spines[s].set_visible(False)
        ax.tick_params(labelsize=12)
        if ax is not axes[0]: ax.set_yticklabels([])
    fig.suptitle(f"{KOR[name]} 위험 예측 모델 비교 — PR-AUC 1위: {best}", x=0.01, ha="left", fontsize=18)
    fig.text(0.01, 0.015, "학습: 피처 2021.10~2023.12 → 정답 2024 · 검증: 피처 2022.10~2024.12 → 정답 2025 (학습에 안 쓴 해) · "
             f"같은 피처 12개 · 로지스틱·랜덤포레스트는 표본 {SAMPLE:,}행 학습 · 기준선 = 과거 빈도만", fontsize=10, color="#6b6a66")
    plt.tight_layout(rect=(0, 0.04, 1, 0.92))
    plt.savefig(f"model_compare_{name}.png", dpi=160)
    plt.close()
    print("  저장:", f"model_compare_{name}.png")

if __name__ == "__main__":
    for n in (sys.argv[1:] or ["enforce", "report"]):
        if Path(f"data/processed/{n}/train.parquet").exists():
            run(n)
        else:
            print(f"[{n}] train.parquet 없음 → config.py NAME='{n}' 로 바꾸고 step4_dataset.py 먼저 실행")
