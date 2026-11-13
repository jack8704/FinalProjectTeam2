"""SoloM RAG 서버: server.py(8000)가 상황을 판정하면 호출 → 근거 조문 검색 + LLM 설명"""
import sys, time
from fastapi import FastAPI
from pydantic import BaseModel

import config                                                    # 팀 RAG 설정 (.env 자동 로드)
from retriever import HybridRetriever, references                # 하이브리드 검색기
from situations import explain_situation                         # 상황 코드 → 고정 근거 + 보조 검색
from prompt import build_situation_prompt, build_prompt          # 상황 설명 / 자유 질문 프롬프트
from guard import check_answer, fallback_message                 # 답변 검증 + 대체 멘트

sys.stdout.reconfigure(encoding="utf-8")                         # 윈도우 한글 출력
app = FastAPI()

USE_DENSE = bool(config.PINECONE_API_KEY)                        # 키 있으면 Pinecone 벡터 검색도 사용
t0 = time.time()
R = HybridRetriever(use_dense=USE_DENSE)                         # 서버 켤 때 1번만 로드 (형태소 분석기·BM25 색인)
print(f"검색기 준비 완료: {time.time() - t0:.1f}초, dense={USE_DENSE}")

class SituationReq(BaseModel):
    code: str                                                    # 상황 코드 (예: right_turn)
    verdict: str                                                 # 규칙엔진 판정: 금지 / 주의 / 가능
    facts: str = ""                                              # 측정 사실 (예: 전방 횡단보도 40m)
    use_llm: bool = True                                         # False면 검색만 (LLM 없이 지연 비교용)

class AskReq(BaseModel):
    question: str                                                # 운전자 자유 질문
    use_llm: bool = True

def _llm(prompt: str) -> str:
    from llm import chat                                         # 팀 llm.py (OPENAI_API_KEY 필요)
    return chat(prompt)

@app.post("/situation")                                          # 상황 판정 → RAG 설명
def situation(q: SituationReq):
    t = time.time()
    sit = explain_situation(R, q.code, q.verdict, q.facts)       # 고정 근거 + 보조 검색
    t_search = time.time() - t                                   # 검색 소요
    chunks = sit["anchors"] + sit["extra"]
    prompt = build_situation_prompt(sit)

    answer, chk, t_llm = None, None, 0.0
    if q.use_llm:
        t = time.time()
        try:
            answer = _llm(prompt)                                # LLM 설명 생성
            chk = check_answer(answer, chunks, q.verdict)        # 근거 밖 조문·판정 뒤집기 검사
        except Exception as e:
            print("LLM 실패:", e)
        t_llm = time.time() - t                                  # LLM 소요

    used_fallback = not answer or (chk is not None and not chk["ok"])
    if used_fallback:                                            # LLM 실패·검증 실패 → 고정 멘트
        answer = fallback_message(sit["anchors"], q.verdict, sit["name"])
    return {
        "answer": answer,
        "articles": [c["article"] for c in chunks],              # 근거 조문 번호
        "references": references(chunks),                        # 참고 조항 문자열
        "used_fallback": used_fallback,
        "guard": chk,
        "missing": sit["missing"],
        "t_search": round(t_search, 3),
        "t_llm": round(t_llm, 3),
    }

@app.post("/ask")                                                # 운전자 자유 질문 (3단계 질문 응답용)
def ask(q: AskReq):
    t = time.time()
    res = R.search(q.question, detail=True)
    t_search = time.time() - t
    hits = res["chunks"]
    prompt = build_prompt(q.question, hits)
    answer, chk, t_llm = None, None, 0.0
    if q.use_llm:
        t = time.time()
        try:
            answer = _llm(prompt)
            chk = check_answer(answer, hits, question=q.question)
        except Exception as e:
            print("LLM 실패:", e)
        t_llm = time.time() - t
    if not answer or (chk is not None and not chk["ok"]):
        answer = fallback_message(hits)
    return {"answer": answer, "articles": [c["article"] for c in hits],
            "references": references(hits), "t_search": round(t_search, 3), "t_llm": round(t_llm, 3)}

@app.get("/")
def root():
    return {"status": "RAG 서버 실행 중", "dense": USE_DENSE}