"""
검색 결과 → LLM 프롬프트 (Gleo LLM SDK / OpenAI 등 어떤 LLM에도 그대로 사용)
  - build_prompt           : 자유 질문 Q&A ("소화전 앞에 세워도 돼?")
  - build_situation_prompt : 규칙엔진 판정 설명 (판정은 바꾸지 말고 근거만 설명)
"""
import re

from retriever import today_int

NO_ANSWER = "해당 내용은 도로교통법 조문에서 확인되지 않습니다."

SYSTEM_QA = f"""너는 운전자에게 도로교통법을 안내하는 차량용 음성 비서다.
답변은 짧게, 아래 [답변 형식]대로만 말한다.
- [근거 조문]에 있는 내용만 쓴다. 관련 근거가 없으면 "{NO_ANSWER}"라고만 말한다.
- 과태료·범칙금·벌금의 금액과 벌점은 말하지 않는다. 위반 결과를 말해야 하면 "위반 시 과태료나 범칙금이 부과될 수 있습니다" 정도로만 말한다.
- 신호 색깔별 의미는 근거에 없으면 말하지 않는다. '시행 예정' 조문은 현재 규칙처럼 말하지 않는다.
- 조문 번호는 근거 조문 머리의 법령명과 함께 쓴다. 예: (도로교통법 제32조) / (도로교통법 시행규칙 별표 2)"""

# 공통: 첫 문장에서 질문의 상황·조건을 되풀이하지 않는다 (운전자는 자기가 한 질문을 다시 들을 필요가 없음)
NO_ECHO = """- 첫 문장에 질문 속 상황이나 조건(예: "우회전 시 신호가 적색일 경우")을 다시 말하지 않는다. 해야 할 행동이나 답부터 말한다.
  나쁜 예: "우회전 시 전방 신호가 적색일 경우 정지해야 합니다."
  좋은 예: "정지해야 합니다. 이 경우 보행자나 자전거에 주의하며 진행해야 합니다(도로교통법 제25조)." """

FORMAT_YES_NO = (
    """[답변 형식] 2문장 이내
1. "예." 또는 "아니요."로 시작해 핵심을 한 문장으로 말한다. 애매하면 원칙(안전한 쪽) 기준으로 답한다.
2. 보충: 이유나 예외를 한 문장으로, 끝에 조문 번호. 예: 단, 승객 승하차 때는 예외입니다(도로교통법 제32조).
"""
    + NO_ECHO
)

FORMAT_EXPLAIN = (
    """[답변 형식] 2문장 이내
1. 질문에 대한 답(해야 할 행동, 기준, 금지 여부)을 한 문장으로 바로 말한다. 예: "정지해야 합니다." / "운전할 수 없습니다."
2. 보충: "이 경우", "단," 등으로 이어서 조건이나 예외를 한 문장으로, 끝에 조문 번호. 예: (도로교통법 제44조)
"""
    + NO_ECHO
)

# 예/아니요로 답할 질문인지 (말끝 패턴 추정 → 서버가 판별해 답변 형식을 지정)
RE_YES_NO_Q = re.compile(
    r"(돼|되나|되냐|될까|되는|해도|하나요|하나|야\s*해|야\s*하|있어|있나|없어|없나|맞아|맞나|"
    r"인가|이야|아니야|가능|괜찮|불법|위반|안\s*돼|안\s*되|되지|하지|않지|맞지)\s*(요)?\s*[?？]?\s*$"
)
RE_WH = re.compile(r"(언제|어디|얼마|어떻게|어떤|무엇|무슨|뭐|뭘|누가|누구|왜|몇)")  # 의문사가 있으면 설명형


def is_yes_no_question(question: str) -> bool:
    q = question.strip()
    return bool(RE_YES_NO_Q.search(q)) and not RE_WH.search(q)


SYSTEM_SITUATION = """너는 운전자에게 현재 상황의 도로교통법 판정을 설명하는 차량용 음성 비서다.
규칙:
1. [판정]은 시스템이 위치·거리로 계산한 확정값이다. 절대 바꾸거나 반대로 말하지 않는다.
2. 판정 이유를 [근거 조문]에 적힌 내용만으로 설명한다. 근거에 없는 거리·금액·처벌은 말하지 않는다.
3. 2문장 이내: 첫 문장에 판정("금지입니다." / "주의하세요." / "가능합니다.")과 핵심,
   둘째 문장에 이유나 예외 + 조문 번호. 예: (도로교통법 제32조)"""


def _tag(c, on):
    return f" ※{c['eff_from']} 시행 예정(현재 효력 없음)" if c["eff_from"] > on else ""


def build_context(chunks, on=None) -> str:
    on = on or today_int()
    return "\n\n".join(
        f"<{i}> {c['text']}{_tag(c, on)}" for i, c in enumerate(chunks, 1)
    )


def build_prompt(question: str, chunks, on=None) -> str:
    ctx = build_context(chunks, on) if chunks else "(관련 조문을 찾지 못함)"
    fmt = FORMAT_YES_NO if is_yes_no_question(question) else FORMAT_EXPLAIN
    return f"{SYSTEM_QA}\n{fmt}\n\n[근거 조문]\n{ctx}\n\n[질문]\n{question}\n\n[답변]"


def build_situation_prompt(sit: dict, on=None) -> str:
    """sit = situations.explain_situation() 결과"""
    chunks = sit["anchors"] + sit["extra"]
    facts = f"\n[측정 사실]\n{sit['facts']}" if sit["facts"] else ""
    point = f"\n\n[안내 핵심]\n{sit['point']}" if sit.get("point") else ""   # [추가] 상황별로 꼭 말할 내용 (위치별 문구 구분)
    return (
        f"{SYSTEM_SITUATION}\n\n[상황]\n{sit['name']}{point}\n\n[판정]\n{sit['verdict']}{facts}"
        f"\n\n[근거 조문]\n{build_context(chunks, on)}\n\n[설명]"
    )