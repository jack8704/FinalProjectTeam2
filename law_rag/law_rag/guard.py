"""
LLM 답변 검증 (환각 방지 안전장치)

LLM이 [근거 조문]에 없는 조문 번호를 지어내거나, 규칙엔진 판정과 반대로 말하거나,
예/아니요 질문에 결론을 먼저 말하지 않으면 잡아냄.
→ 문제가 있으면 앱은 LLM 답변 대신 안전한 고정 멘트를 읽도록 사용.
"""
import re

from prompt import NO_ANSWER, is_yes_no_question

RE_CITE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
RE_ANNEX = re.compile(r"별표\s*(\d+(?:의\d+)?)")  # 시행규칙 별표 인용

RE_YES = re.compile(r"^\s*(예|네)\s*[.,!]")
RE_NO = re.compile(r"^\s*(아니요|아니오|아뇨)\s*[.,!]")


def cited_articles(answer: str) -> set:
    arts = {
        f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        for m in RE_CITE.finditer(answer)
    }
    return arts | {f"별표 {m.group(1)}" for m in RE_ANNEX.finditer(answer)}


def answer_label(answer: str) -> str:
    """답변 첫 마디 → "yes" / "no" / "unknown"(근거 없음) / "" (설명형) — 앱 화면 색상·아이콘용"""
    if RE_YES.match(answer):
        return "yes"
    if RE_NO.match(answer):
        return "no"
    if NO_ANSWER in answer:
        return "unknown"
    return ""


def check_answer(
    answer: str, chunks, verdict: str = None, question: str = None
) -> dict:
    """
    반환: {"ok": bool, "problems": [...], "warnings": [...], "cited": [...], "label": "yes|no|unknown|"}
    - 문제(→ 대체 멘트 사용): 근거에 없는 조문 인용 / 조문 번호 미표기 / 판정 불일치
    - 경고(→ 로그만):        예/아니요 질문인데 예/아니요로 시작하지 않음 (질문 유형 판별이 추정이라 경고 처리)
    """
    allowed = {c["article"] for c in chunks}
    cited = cited_articles(answer)
    label = answer_label(answer)
    problems, warnings = [], []
    if cited - allowed:
        problems.append(f"근거에 없는 조문 인용: {sorted(cited - allowed)}")
    if chunks and not cited and label != "unknown":
        problems.append("근거 조문 번호를 밝히지 않음")
    if verdict:
        others = {"금지", "주의", "가능"} - {verdict}
        head = answer.strip().split("\n")[0][:40]  # 첫 문장 앞부분에서 판정을 말했는지 확인
        if verdict not in head and any(o in head for o in others):
            problems.append(f"판정 불일치: 시스템 판정은 '{verdict}'")
    if (
        question
        and not verdict
        and is_yes_no_question(question)
        and label not in ("yes", "no", "unknown")
    ):
        warnings.append("예/아니요 질문인데 결론으로 시작하지 않음")
    return {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "cited": sorted(cited),
        "label": label,
    }


def fallback_message(chunks, verdict: str = None, name: str = "") -> str:
    """LLM 답변을 쓸 수 없을 때 읽을 고정 멘트 (LLM 없이 조립 — 예/아니요는 판단하지 않음)"""
    if not chunks:
        return NO_ANSWER
    arts = ", ".join(dict.fromkeys(c["article"] for c in chunks[:2]))
    if verdict:
        return f"{name} {verdict}입니다. 자세한 내용은 도로교통법 {arts}를 확인하세요.".strip()
    return f"관련 규정은 도로교통법 {arts}입니다. 화면에서 조문을 확인하세요."
