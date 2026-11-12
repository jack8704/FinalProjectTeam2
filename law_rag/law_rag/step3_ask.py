"""
STEP 3. 자유 질문 → 검색 → 프롬프트 (→ 선택: LLM 답변 + 검증)  ※ 수업 ch9_12 ask_with_reference 대응
실행:
  python step3_ask.py "초록불에 우회전할 때 횡단보도에 사람 있으면?"
  python step3_ask.py "소화전 앞에 주차해도 돼?" --no-dense         (Pinecone 없이 BM25만)
  python step3_ask.py "음주운전 기준" --date 20270701                (특정 날짜 기준 법 적용)
  python step3_ask.py "스쿨존 속도" --rerank tfidf --cat             (TF-IDF 리랭크 + 카테고리 필터)
  python step3_ask.py "연봉 말고 면허 취소 기준" --norm llm          (LLM 질의 표준화, 서버 LLM 키 필요)
  python step3_ask.py "음주운전 기준" --llm                          (서버 LLM으로 답변 생성 + 검증)
"""
import argparse
import sys

from guard import check_answer, fallback_message
from prompt import build_prompt
from retriever import HybridRetriever, references

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default="횡단보도 앞에서 일시정지해야 하는 경우는?")
    ap.add_argument("--no-dense", action="store_true", help="Pinecone 없이 BM25만")
    ap.add_argument("--rerank", choices=["none", "tfidf", "pinecone"], default=None)
    ap.add_argument(
        "--norm", choices=["none", "rule", "llm"], default="rule", help="질의 표준화 방식"
    )
    ap.add_argument("--cat", action="store_true", help="카테고리 필터 켜기")
    ap.add_argument("--date", type=int, default=None, help="기준일 yyyymmdd (기본: 오늘)")
    ap.add_argument("--llm", action="store_true", help="서버 LLM으로 답변 생성 후 검증")
    a = ap.parse_args()

    r = HybridRetriever(
        use_dense=not a.no_dense,
        rerank=a.rerank,
        norm=a.norm,
        category_filter=True if a.cat else None,
    )
    res = r.search(a.question, on=a.date, detail=True)
    hits = res["chunks"]

    print("=" * 60)
    print(f"원본 질문  : {a.question}")
    print(f"표준화 질문: {res['query']}")
    print(
        f"설정       : {res['used']}"
        + (f"  / 질문 카테고리 {res['categories']}" if res["categories"] else "")
    )
    print("=" * 60)
    for c in hits:
        print(
            f"· {c['article']}({c['title']}) [{c['status']}] {c.get('category')} {c['id']}"
        )
    print(f"참고 조항  : {references(hits)}")
    if not res["confident"]:
        print(f"⚠ 근거 부족 (리랭크 최고점 {res['top_score']:.3f}) → 앱은 '확인 불가' 안내 권장")

    prompt = build_prompt(a.question, hits, a.date)
    if not a.llm:
        print("\n── LLM에 보낼 프롬프트 (Gleo LLM SDK generateContent에 그대로 전달) ──\n" + prompt)
        return

    from llm import chat

    answer = chat(prompt)
    chk = check_answer(answer, hits)
    print("\n── 답변 ──\n" + answer)
    print(f"\n── 검증 ── {'통과' if chk['ok'] else '실패: ' + ' / '.join(chk['problems'])}")
    if not chk["ok"]:
        print("대체 멘트:", fallback_message(hits))


if __name__ == "__main__":
    main()
