"""
질의 표준화 2가지 방식 (수업 ch9_11 dictionary_chain)

  1) rule : synonyms.py 사전으로 법령 용어를 '덧붙임' (무료, 즉시, 결과 예측 가능)  ← 기본
  2) llm  : 사전을 LLM에 주고 질문을 법령 용어로 '다시 씀' (유연하지만 호출 비용·지연·오변환 위험)

차이: 수업 예제는 LLM이 질문을 바꿔 씀 → 원래 단어가 사라질 수 있음.
      여기서는 [원 질문 + 표준화 질문]을 함께 검색에 넣어 오변환 피해를 줄임.
"""
from synonyms import SYNONYMS, expand_query

_cache = {}

NORMALIZE_PROMPT = """사용자의 운전 관련 질문을 도로교통법 조문에 쓰이는 용어로 바꿔 쓰세요.
아래 사전을 참고하되, 질문의 뜻은 바꾸지 마세요. 오직 바뀐 질문 한 줄만 출력하세요.
사전:
{dictionary}
질문: {question}"""


def normalize(question: str, mode: str = "rule") -> str:
    if mode == "none":
        return question
    if mode == "rule":
        return expand_query(question, SYNONYMS)
    if mode == "llm":
        if question in _cache:  # 같은 질문은 다시 호출하지 않음 (평가 비용 절약)
            return _cache[question]
        from llm import chat

        dictionary = "\n".join(f"{k} -> {v}" for k, v in SYNONYMS.items())
        rewritten = chat(
            NORMALIZE_PROMPT.format(dictionary=dictionary, question=question),
            temperature=0,
        )
        _cache[question] = f"{question} {rewritten.splitlines()[0]}"  # 원 질문 + 표준화 질문
        return _cache[question]
    raise ValueError(f"알 수 없는 표준화 방식: {mode}")
