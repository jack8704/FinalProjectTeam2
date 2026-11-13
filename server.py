# server.py — 신호 수신 API. 판정 로직은 case1.py, case2.py … 에 있음
# 실행: uvicorn server:app --host 0.0.0.0 --port 8000 --reload
from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime
import csv, os, time
import requests
 
from core import latest, RAG_URL, case_lock, guidance_log    # 공통 상태
import case1, case2                                          # Case 추가 시 여기에 import
 
CASES = [case1, case2]                                       # 신호마다 순서대로 판정 (Case 3 추가 시 여기에)
 
app = FastAPI()
LOG_FILE = "signals.csv"                                     # 신호 기록 파일
 
class Signal(BaseModel):
    type: str                                                # 신호 이름 (예: turn_signal)
    value: str                                               # 값 (예: RIGHT)
    ts: int                                                  # 앱에서 보낸 시각 (ms)
 
@app.post("/signal")
def receive_signal(s: Signal):
    latest[s.type] = s.value                                 # 최신값 갱신
    if s.type == "location":
        latest["loc_ts"] = time.time()                       # 위치 받은 시각 (오래된 위치 판정 보류용)
    print(f"[{datetime.now():%H:%M:%S}] {s.type} = {s.value}")
    new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new: w.writerow(["time", "type", "value", "ts"])
        w.writerow([datetime.now().isoformat(), s.type, s.value, s.ts])
    with case_lock:                                          # 다른 요청이 판정 중이면 끝날 때까지 대기
        for c in CASES:
            try:
                c.evaluate()                                 # Case별 판정
            except Exception as e:
                print(f"!!! {c.__name__} 판정 오류: {e!r}")   # 한 Case 오류가 다른 Case를 막지 않게
    return {"ok": True, "message": f"{s.type} 수신 완료"}
 
@app.get("/latest")
def get_latest():
    return latest
 
@app.get("/guidance")                                        # SoloM 앱이 1초마다 호출: /guidance?after=마지막id
def get_guidance(after: int = 0):
    return [g for g in guidance_log if g["id"] > after]      # after 번호보다 새 안내만 반환
 
@app.get("/ask")                                             # 질문 응답 테스트: 브라우저에서 /ask?q=우회전할 때 일시정지해야 해?
def ask(q: str):
    if not RAG_URL: return {"error": "RAG_URL 미설정"}
    return requests.post(f"{RAG_URL}/ask", json={"question": q}, timeout=60).json()
 
@app.get("/")
def root():
    return {"status": "SoloM 서버 실행 중", "docs": "/docs", "rag": RAG_URL or "미설정"}