# core.py — 모든 Case가 함께 쓰는 것: 최신 신호값, 시설 DB, 거리·GPS 계산, RAG 호출·안내 저장
# latest, SITU는 여러 파일이 같은 객체를 공유 (재대입 금지, 내용만 수정)
from datetime import datetime
import os, re, math, time, threading
import requests                                              # RAG 서버 호출용
 
latest = {}                                                  # 신호별 최신값 (server.py가 갱신, 각 Case가 읽음)
RAG_URL = os.getenv("RAG_URL", "")                           # 예: http://127.0.0.1:8001 (비어 있으면 RAG 호출 생략)
 
from facility import FacilityDB                              # source\facility.py
CW  = FacilityDB("data/fac_crosswalk.csv", "횡단보도")         # 서버 시작 시 1번 로드 (Case 1, Case 2 A10)
HYD = FacilityDB("data/fac_hydrant.csv", "소방용수시설")        # Case 2 A7
CAM = FacilityDB("data/fac_camera.csv", "단속카메라")           # Case 3용 (지금은 로드만)
BUS = FacilityDB("data/fac_busstop.csv", "버스정류장")         # Case 2 A9 (prepare_busstop.py로 생성)
 
case_lock = threading.Lock()                                 # 판정은 한 번에 하나씩만 (중복 안내 방지)
 
# ───────── Case → 팀 RAG 상황 코드·판정: 각 Case 파일이 자기 코드를 등록함 ─────────
SITU = {}                                                    # 예: case1.py 에서 SITU.update({...})
 
# ───────── 안내 저장소: SoloM 앱(GuidanceService)이 /guidance 로 가져감 ─────────
guidance_log = []                                            # 최근 안내 목록
guidance_id = 0                                              # 안내마다 1씩 증가하는 번호
guidance_lock = threading.Lock()                             # 저장할 때 번호 겹침 방지
 
def push_guidance(case_id, text):
    global guidance_id
    with guidance_lock:
        guidance_id += 1
        guidance_log.append({"id": guidance_id, "code": case_id, "text": text, "ts": time.time()})
        del guidance_log[:-20]                               # 최근 20개만 보관
        save_guidance(guidance_id, case_id, text)            # 파일에도 기록

def save_guidance(gid, case_id, text):                       # 안내 문구 기록 (TTS로 보낸 실제 문장)
    import csv
    now = datetime.now().isoformat()
    try:
        new = not os.path.exists("guidance.csv")
        with open("guidance.csv", "a", newline="", encoding="utf-8-sig") as f:   # 안내만 모은 파일
            w = csv.writer(f)
            if new: w.writerow(["time", "id", "code", "text"])
            w.writerow([now, gid, case_id, text])
        with open("signals.csv", "a", newline="", encoding="utf-8-sig") as f:    # 신호 파일에도 같은 시간 순서로 1줄
            csv.writer(f).writerow([now, "guidance", f"{case_id}: {text}", ""])
    except Exception as e:
        print("    안내 기록 실패:", e)
 
# ───────── 거리·방향 계산 ─────────
def haversine(lat1, lon1, lat2, lon2):                       # 두 좌표 사이 거리 (m)
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))
 
dist_m = haversine                                           # 같은 계산이라 이름만 연결 (잠금 해제 로직에서 사용)
 
def bearing(lat1, lon1, lat2, lon2):                         # 1 → 2 방향 각도 (북=0, 동=90)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360
 
def angle_diff(a, b):                                        # 두 각도 차이 (0~180)
    return abs((a - b + 180) % 360 - 180)
 
def gps_tier(dist, acc, limit):                              # GPS 오차 반영 3단계
    if acc > 30:            return "판정 보류"                # 오차가 너무 큼
    if dist + acc <= limit: return "확정"                     # 오차를 더해도 기준 안
    if dist - acc <= limit: return "가능성"                   # 오차 범위에 걸침
    return "해당 없음"
 
# ───────── 음성용 문장 다듬기 (RAG 응답은 그대로, TTS로 보내는 문장만 짧게) ─────────
SPEAK_LAW = "short"                                          # 조문 읽기: "short" = "제25조"만 / "full" = "도로교통법 제25조" / "none" = 안 읽음
SPEAK_VERDICT_CAUTION = False                                # False: 맨 앞 "주의하세요."는 읽지 않음 ("금지입니다."는 의미가 커서 유지)

def speech(text):
    t = (text or "").strip()
    if SPEAK_LAW == "none":
        t = re.sub(r"\s*\((?:도로교통법|관련)[^)]*\)", "", t)   # 괄호 조문 통째로 제거
    elif SPEAK_LAW == "short":
        t = re.sub(r"\(\s*도로교통법\s+", "(", t)              # "(도로교통법 제25조)" → "(제25조)"
        t = re.sub(r",\s*도로교통법\s+", ", ", t)               # "(…, 도로교통법 제27조)" 같은 경우도 정리
    if not SPEAK_VERDICT_CAUTION and t.startswith("주의하세요.") and len(t) > len("주의하세요."):
        t = t[len("주의하세요."):].strip()                     # 맨 앞 판정 단어 제거 → 한 문장으로
    return t

# ───────── 판정 → RAG 실시간 호출 → 안내 ─────────
def rag_guidance(case_id, detail, push=True):               # push=False면 저장하지 않고 문구만 돌려줌
    code, verdict = SITU[case_id]
    label = "Case 판정" if push else "미리 요청(아직 안 읽음)"   # 미리 판정용 요청은 판정 로그와 구분
    print(f"\n[{datetime.now():%H:%M:%S}] {label}: {case_id} {detail} → RAG 요청: {code}/{verdict}")
    if not RAG_URL:
        print("    RAG_URL 없음 → 호출 생략"); return None
    t0 = time.time()                                         # 전체 왕복 지연 측정 시작
    try:
        r = requests.post(f"{RAG_URL}/situation",
                          json={"code": code, "verdict": verdict, "facts": detail}, timeout=60)
        if r.status_code != 200:                             # RAG 서버 오류 → 원인이 보이게 응답 앞부분 표시
            print(f"    RAG 오류 {r.status_code}: {r.text[:200]} ({time.time() - t0:.2f}초)"); return None
        res = r.json()
        sec = time.time() - t0                               # 전체 소요 (네트워크 + 검색 + LLM)
        print(f"{'>>> [안내' if push else '    [준비 문구(아직 안 읽음)'} {case_id}] {speech(res.get('answer'))}")   # 실제로 읽는 문장
        print(f"    RAG 원문: {res.get('answer')}")                 # 판정 단어·조문 포함 원문 (근거 확인용)
        if push:
            push_guidance(case_id, speech(res.get("answer")))   # 앱이 가져갈 수 있게 저장 (괄호 조문 제외)
        print(f"    근거: {res.get('references')}  (대체멘트 사용: {res.get('used_fallback')})")
        print(f"    소요: 전체 {sec:.2f}초 = 검색 {res.get('t_search')}초 + LLM {res.get('t_llm')}초 + 기타\n")
        latest["guidance"] = f"{case_id}|{res.get('answer')}|{sec:.2f}s"   # /latest 에서 확인 가능
        with open("rag_latency.csv", "a", encoding="utf-8-sig") as f:      # 지연 기록 누적
            f.write(f"{datetime.now().isoformat()},{case_id},{sec:.3f},{res.get('t_search')},{res.get('t_llm')}\n")
        return speech(res.get("answer"))
    except Exception as e:
        print(f"    RAG 호출 실패: {e} ({time.time() - t0:.2f}초)")
        return None
 
def trigger(case_id, detail=""):
    # RAG 응답을 기다리는 동안 다른 신호 수신이 막히지 않도록 별도 스레드로 실행
    threading.Thread(target=rag_guidance, args=(case_id, detail), daemon=True).start()
def trigger_group(items):
    # 같은 순간에 나갈 안내 여러 개를 '한 번에' 저장 → TTS가 앞 안내를 끊지 않음
    # items: [(case_id, detail), ...] 말할 순서대로
    def run():
        texts = [t for cid, d in items if (t := rag_guidance(cid, d, push=False))]   # 순서대로 문구 생성
        if texts:
            code = "+".join(cid for cid, _ in items)
            push_guidance(code, " ".join(texts))             # 한 문장 묶음으로 1번만 저장
            print(f">>> [안내 묶음 {code}] {' '.join(texts)}\n")
    threading.Thread(target=run, daemon=True).start()