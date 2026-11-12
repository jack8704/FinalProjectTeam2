"""
STEP 5. 규칙엔진 판정 → 근거 조문 → 설명 프롬프트 (6단계 '상황별 결합'의 RAG 쪽)
실행:
  python step5_situation.py --check                                   (모든 상황의 고정 근거가 원문에 있는지 점검)
  python step5_situation.py parking_hydrant 금지 "소화전까지 4.2m" --no-dense
  python step5_situation.py right_turn 주의 "전방 횡단보도 보행자 감지"
  python step5_situation.py door_open 주의 --llm                      (OpenAI로 설명 생성 + 검증)
"""
import argparse
import sys

from guard import check_answer, fallback_message
from prompt import build_situation_prompt
from retriever import HybridRetriever
from situations import SITUATIONS, anchor_chunks, explain_situation

sys.stdout.reconfigure(encoding="utf-8")


def check_all(r):
    ok = True
    for code, s in SITUATIONS.items():
        found, missing = anchor_chunks(r, code)
        mark = "OK " if not missing else "!! "
        ok &= not missing
        print(
            f"{mark}{code:22s} {s['name']:16s} → {[c['article'] for c in found]}"
            + (f"  누락: {missing}" if missing else "")
        )
        for c in found:
            print(f"      {c['text'][:90].replace(chr(10), ' / ')}…")
    print("\n모든 고정 근거 확인됨" if ok else "\n!! 표시된 상황은 situations.py의 anchor를 원문에 맞게 고치세요")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code", nargs="?", choices=list(SITUATIONS))
    ap.add_argument("verdict", nargs="?", choices=["금지", "주의", "가능"])
    ap.add_argument("facts", nargs="?", default="")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--date", type=int, default=None)
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()

    r = HybridRetriever(use_dense=not a.no_dense)
    if a.check or not a.code:
        return check_all(r)
    if not a.verdict:
        sys.exit("판정(금지/주의/가능)을 함께 입력하세요.")

    sit = explain_situation(r, a.code, a.verdict, a.facts, on=a.date)
    print(f"── {sit['name']} / 판정: {sit['verdict']} ──")
    print(
        "고정 근거:",
        [c["article"] for c in sit["anchors"]],
        " 보조 근거:",
        [c["article"] for c in sit["extra"]],
    )
    if sit["missing"]:
        print("⚠ 누락:", sit["missing"])
    if sit["note"]:
        print("한계:", sit["note"])

    prompt = build_situation_prompt(sit, a.date)
    if not a.llm:
        print("\n── LLM에 보낼 프롬프트 ──\n" + prompt)
        return
    from llm import generate

    answer = generate(prompt)
    chk = check_answer(answer, sit["anchors"] + sit["extra"], a.verdict)
    print("\n── 설명 ──\n" + answer)
    print(f"\n── 검증 ── {'통과' if chk['ok'] else '실패: ' + ' / '.join(chk['problems'])}")
    if not chk["ok"]:
        print("대체 멘트:", fallback_message(sit["anchors"], a.verdict, sit["name"]))


if __name__ == "__main__":
    main()
