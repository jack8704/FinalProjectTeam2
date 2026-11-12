"""
STEP 4. 검색 품질 평가 (Hit@k, MRR) + 기법별 효과 비교(ablation)

"수업에서 배운 기법을 다 넣었다"가 아니라 "넣어서 몇 %p 올랐다/떨어져서 뺐다"를 보여주는 스크립트.

실행:
  python step4_eval.py                     (개발셋, Pinecone 키 있으면 Dense 구성까지)
  python step4_eval.py --holdout           (홀드아웃 = 최종 성적, 이걸 보고 튜닝하면 안 됨)
  python step4_eval.py --no-dense          (키 없이 BM25 구성만)
  python step4_eval.py --pinecone-rerank   (Cross-Encoder 리랭크 구성 추가 — 문항 수만큼 무료 한도 소모)
  python step4_eval.py --llm-norm          (LLM 질의 표준화 구성 추가 — 서버 LLM 키 필요, 문항 수만큼 호출)
  python step4_eval.py --show-fails        (마지막 구성의 실패 질문 출력)

결과는 eval/results.csv에 누적 저장 (임베딩 공급자 포함) → 발표 자료 비교표로 사용
"""
import argparse
import csv
import json
import sys
from datetime import datetime

import config
from retriever import HybridRetriever

sys.stdout.reconfigure(encoding="utf-8")


def label(c) -> str:
    """정답 비교용 이름: 법률 조문은 '제27조', 시행규칙은 '시행규칙 제19조' / '시행규칙 별표 2'"""
    return (
        c["article"]
        if c["law"] == "도로교통법"
        else f"{c['law'].replace('도로교통법 ', '')} {c['article']}"
    )


def norm_answer(a: str) -> str:
    return f"시행규칙 {a}" if a.startswith("별표") else a


def evaluate(r, qs):
    h1 = h3 = h5 = 0
    mrr = 0.0
    fails = []
    for item in qs:
        arts = [label(c) for c in r.search(item["q"], top_k=5)]
        answers = [norm_answer(a) for a in item["answers"]]
        rank = next(
            (i + 1 for i, a in enumerate(arts) if a in answers), None
        )  # 첫 정답 순위
        h1 += rank == 1
        h3 += bool(rank and rank <= 3)
        h5 += bool(rank and rank <= 5)
        mrr += 1 / rank if rank else 0
        if not rank or rank > 3:
            fails.append((item["q"], item["answers"], arts))
    n = len(qs)
    return {
        "N": n,
        "Hit@1": h1 / n,
        "Hit@3": h3 / n,
        "Hit@5": h5 / n,
        "MRR": mrr / n,
    }, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--situations", action="store_true", help="팀 상황 리스트(엑셀) 기반 문항")
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--pinecone-rerank", action="store_true")
    ap.add_argument("--llm-norm", action="store_true")
    ap.add_argument("--show-fails", action="store_true")
    a = ap.parse_args()

    fname = (
        "situations.jsonl"
        if a.situations
        else ("holdout.jsonl" if a.holdout else "questions.jsonl")
    )
    qs = [json.loads(l) for l in open(config.EVAL_DIR / fname, encoding="utf-8")]
    use_dense = not a.no_dense and bool(config.PINECONE_API_KEY)
    if not a.no_dense and not use_dense:
        print("※ PINECONE_API_KEY 없음 → BM25 구성만 평가합니다.")
    r = HybridRetriever(
        use_dense=use_dense, rerank="none", norm="none", category_filter=False
    )

    # (이름, bm25, dense, 표준화, 카테고리필터, 리랭크)
    C = [
        ("BM25", 1, 0, "none", 0, "none"),
        ("BM25+사전", 1, 0, "rule", 0, "none"),
        ("BM25+사전+카테고리", 1, 0, "rule", 1, "none"),
        ("BM25+사전+TF-IDF", 1, 0, "rule", 0, "tfidf"),
    ]
    if use_dense:
        C += [
            ("Dense", 0, 1, "none", 0, "none"),
            ("하이브리드", 1, 1, "none", 0, "none"),
            ("하이브리드+사전", 1, 1, "rule", 0, "none"),
            ("하이브리드+사전+카테고리", 1, 1, "rule", 1, "none"),
            ("하이브리드+사전+TF-IDF", 1, 1, "rule", 0, "tfidf"),
        ]
        if a.pinecone_rerank:
            C += [("하이브리드+사전+CrossEnc", 1, 1, "rule", 0, "pinecone")]
    if a.llm_norm:
        C += [("BM25+LLM표준화", 1, 0, "llm", 0, "none")]
        if use_dense:
            C += [("하이브리드+LLM표준화", 1, 1, "llm", 0, "none")]

    rows, fails = [], []
    print(
        f"\n[{fname}]  N={len(qs)}  임베딩={config.EMBED_PROVIDER if use_dense else '-'}"
    )
    print(f"{'구성':26s} Hit@1  Hit@3  Hit@5  MRR")
    for name, bm25, dense, norm, cat, rr in C:
        r.use_bm25, r.use_dense, r.norm, r.category_filter, r.rerank = (
            bool(bm25),
            bool(dense),
            norm,
            bool(cat),
            rr,
        )
        m, fails = evaluate(r, qs)
        print(
            f"{name:26s} {m['Hit@1']:5.0%}  {m['Hit@3']:5.0%}  {m['Hit@5']:5.0%}  {m['MRR']:.3f}"
        )
        rows.append(
            {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "set": fname,
                "embed": config.EMBED_PROVIDER if dense else "-",
                "config": name,
                **{
                    k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in m.items()
                },
            }
        )

    out = config.EVAL_DIR / "results.csv"
    new = not out.exists()
    with open(
        out, "a", newline="", encoding="utf-8-sig"
    ) as f:  # utf-8-sig → 엑셀에서 한글 안 깨짐
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f"\n저장: {out}")
    print("※ 문항 수가 적어 1문항 = 개발셋 약 3%p / 홀드아웃 약 7%p. 차이가 1~2문항이면 '효과 불분명'으로 해석")

    if a.show_fails:
        print(f"\n── [{C[-1][0]}] 3위 안에 정답 없는 질문 ──")
        for q, ans, got in fails:
            print(f"· {q}  정답{ans}  검색{got}")
        if a.holdout:
            print("※ 홀드아웃 실패를 보고 사전·코드를 고치면 홀드아웃이 더 이상 공정한 시험이 아닙니다.")


if __name__ == "__main__":
    main()
