"""
규칙엔진(3단계) ↔ RAG(4단계) 연결부

역할 분담 (심사 방어 핵심)
  - 금지/주의/가능 "판정"은 규칙엔진이 한다 (좌표·거리 계산 = 결정적, 재현 가능)
  - RAG는 그 판정의 "법적 근거"를 찾아 설명만 한다 (LLM이 판정을 바꾸지 못하게 프롬프트로 고정)

왜 상황별 '고정 근거 조문(anchor)'을 두나?
  - 앱이 이미 상황을 안다면(예: 소화전 4m 앞 정차) 검색을 돌릴 필요가 없음 → 검색 실패 0%, 응답 빠름
  - 검색은 보조 근거(관련 조문 추가)로만 사용

⚠ anchor의 조문·키워드는 step5_situation.py --check 로 실제 원문에 있는지 반드시 확인할 것
"""
from typing import Optional

from retriever import HybridRetriever, today_int

# code: {name, anchors: [(조, 가지번호, 청크 선택 키워드)], query: 보조검색 질문, note: 한계}
SITUATIONS = {
    # ── 1차 시연 시나리오 (2개) ──
    "right_turn": {
        "name": "교차로 우회전",
        "anchors": [(25, 0, "우회전"), (27, 0, "횡단보도")],
        "query": "교차로에서 우회전할 때 횡단보도 보행자 보호 일시정지",
        "note": "신호 색깔별 우회전 방법(적색 신호 시 일시정지 등)은 시행규칙 별표에 있어 현재 미수록",
    },
    # [추가] 우회전: 횡단보도 위치별로 안내 문구를 다르게 (point = LLM에 주는 안내 핵심)
    "right_turn_front": {
        "name": "교차로 우회전 - 전방(회전 전) 횡단보도",
        "anchors": [(25, 0, "우회전"), (27, 0, "횡단보도")],
        "static": ["rt_red"],                                    # 시행규칙 별표2 적색 등화 (코퍼스 미수록 → 고정 청크)
        "point": "신호 정보가 없으므로 '빨간불이면' 조건을 반드시 붙인다. 판정 단어 뒤에 딱 한 문장, 30자 안팎으로: "
                 "'빨간불이면 정지선에서 멈추고, 보행자가 없을 때 우회전하세요' + 조문 번호.",
        "query": "교차로 우회전 적색 신호 정지선 일시정지",
        "note": "신호 색은 측정 불가 → 가정형 안내",
    },
    "right_turn_after": {
        "name": "교차로 우회전 - 회전 후 횡단보도",
        "anchors": [(25, 0, "우회전"), (27, 0, "횡단보도")],
        "point": "판정 단어 뒤에 딱 한 문장, 30자 안팎으로: '회전 후 횡단보도에 보행자가 있으면 멈추세요' + 조문 번호.",
        "query": "우회전 후 횡단보도 보행자 통행하려고 하는 때 일시정지",
        "note": "보행자 유무는 측정 불가 → 조건형 안내",
    },
    "right_turn_both": {                                         # [추가] 전방·회전 후 횡단보도가 둘 다 있을 때 (신호 모름 → 둘 다 1번에 안내)
        "name": "교차로 우회전 - 전방(회전 전)과 회전 후 횡단보도",
        "anchors": [(25, 0, "우회전"), (27, 0, "횡단보도")],
        "static": ["rt_red"],
        "point": "신호 정보가 없으므로 '빨간불이면' 조건을 반드시 붙인다. 판정 단어 뒤에 딱 한 문장, 35자 안팎으로: "
                 "'빨간불이면 정지선에서 멈추고, 회전 후 보행자가 있으면 멈추세요' + 조문 번호.",
        "query": "교차로 우회전 횡단보도 보행자 일시정지 적색 신호",
        "note": "신호 색·보행자 유무 측정 불가 → 조건형 안내",
    },
    "door_open": {
        "name": "정차 후 하차·문 열기",
        "anchors": [(49, 0, "문을")],
        "query": "차 문을 열거나 내릴 때 안전 확인 의무",
        "note": "",
    },
    # ── 위치 기반 주정차 (규칙엔진의 좌표·거리 판정과 짝) ──
    "parking_hydrant": {
        "name": "소화전 주변 주정차",
        "anchors": [(32, 0, "소방용수")],
        "query": "소방용수시설 비상소화장치 근처 정차 주차 금지",
        "note": "과태료 금액은 시행령 별표에 있어 현재 미수록",
    },
    "parking_bus_stop": {
        "name": "버스정류장 주변 주정차",
        "anchors": [(32, 0, "정류지")],
        "query": "버스 정류지 근처 정차 주차 금지 거리",
        "note": "과태료 금액은 시행령 별표에 있어 현재 미수록",
    },
    "parking_crosswalk": {
        "name": "횡단보도 주변 주정차",
        "anchors": [(32, 0, "횡단보도")],
        "query": "횡단보도 위나 근처 정차 주차 금지",
        "note": "과태료 금액은 시행령 별표에 있어 현재 미수록",
    },
    "parking_intersection": {
        "name": "교차로·모퉁이 주변 주정차",
        "anchors": [(32, 0, "교차로")],
        "query": "교차로 가장자리 도로 모퉁이 정차 주차 금지",
        "note": "과태료 금액은 시행령 별표에 있어 현재 미수록",
    },
    "school_zone": {
        "name": "어린이 보호구역 주행",
        "anchors": [(12, 0, "어린이")],
        "query": "어린이 보호구역 통행 속도 제한",
        "note": "",
    },
    # ── 주정차 단속·신고 위험 (ML 예측 결과와 짝, risk_lookup.py가 상황 코드를 줌) ──
    "parking_risk_enforce": {
        "name": "주정차 단속 다발 구역",
        "anchors": [(32, 0, "정차하거나 주차")],                 # 제32조 머리문장 (정차·주차 금지 장소)
        "extra_k": 0,                                            # 보조 검색 끄기 (제2조 등 무관한 조문 차단)
        "query": "정차 주차 금지 장소 교차로 횡단보도 보도",
        "note": "위험 등급은 과거 단속 기록 기반 예측(상위 1%)이며 금지 판정이 아님",
        "guide": "과태료(승용차 기준): 일반 4만원, 소방시설 주변 8만원, "
                 "어린이보호구역 12만원 (도로교통법 시행령 별표 6)",   # LLM 미사용 고정 문구
    },
    "parking_risk_report": {
        "name": "주정차 신고 다발 구역",
        "anchors": [(32, 0, "보도")],                             # 제32조 1호 (교차로·횡단보도·보도)
        "extra_k": 0,                                            # 보조 검색 끄기
        "query": "보도 횡단보도 교차로 정차 주차 금지",
        "note": "위험 등급은 과거 신고 기록 기반 예측(상위 1%)이며 금지 판정이 아님",
        "guide": "보도·횡단보도·교차로 등에 세운 차는 1분 간격 사진 2장으로 시민 신고되어 "
                 "현장 확인 없이 과태료(승용차 4만원)가 부과될 수 있습니다. "
                 "신고 단속은 사전 문자 알림이 오지 않습니다.",       # LLM 미사용 고정 문구
    },
}

VERDICTS = ("금지", "주의", "가능")

# [추가] 코퍼스에 없는 조문을 고정 청크로 넣음 (⚠ 국가법령정보센터 원문과 문구 대조 후 사용)
#   출처: 도로교통법 시행규칙 [별표 2] 차량신호등 적색의 등화 (2023.1.22. 시행)
STATIC_CHUNKS = {
    "rt_red": {
        "law": "도로교통법 시행규칙", "article": "별표 2", "eff_from": 20230122,
        "category": [],                                          # 보조검색 카테고리 필터에 영향 주지 않게 비움
        "text": "도로교통법 시행규칙 별표 2 (적색의 등화) 차마는 정지선, 횡단보도 및 교차로의 직전에서 정지해야 한다. "
                "차마는 우회전하려는 경우 정지선, 횡단보도 및 교차로의 직전에서 정지한 후 "
                "신호에 따라 진행하는 다른 차마의 교통을 방해하지 않고 우회전할 수 있다.",
    },
}


def anchor_chunks(r: HybridRetriever, code: str, on: Optional[int] = None):
    """상황별 고정 근거 청크. 반환: (청크 목록, 못 찾은 anchor 목록)"""
    on = on or today_int()
    found, missing = [], []
    for num, sub, kw in SITUATIONS[code]["anchors"]:
        cs = r.article_chunks(num, sub, on)
        if not cs:
            missing.append(f"제{num}조" + (f"의{sub}" if sub else ""))
            continue
        hit = [c for c in cs if kw in c["text"]]  # 키워드가 들어 있는 청크(항·호)를 우선
        found.append(hit[0] if hit else cs[0])
        if not hit:
            missing.append(f"제{num}조 '{kw}' 키워드 없음")
    return found, missing


def explain_situation(
    r: HybridRetriever,
    code: str,
    verdict: str,
    facts: str = "",
    on: Optional[int] = None,
    extra_k: int = 1,
) -> dict:
    """
    code    : 상황 코드 (SITUATIONS의 key)
    verdict : 규칙엔진 판정 ("금지" / "주의" / "가능")
    facts   : 규칙엔진이 계산한 사실 (예: "소화전까지 거리 4.2m")
    """
    if code not in SITUATIONS:
        raise ValueError(f"알 수 없는 상황 코드: {code}  (가능: {list(SITUATIONS)})")
    if verdict not in VERDICTS:
        raise ValueError(f"판정은 {VERDICTS} 중 하나여야 합니다: {verdict}")
    s = SITUATIONS[code]
    extra_k = s.get("extra_k", extra_k)                  # 상황별 보조 검색 개수 (없으면 기존 값 1) — 동료 11/9 추가
    anchors, missing = anchor_chunks(r, code, on)
    anchors += [STATIC_CHUNKS[k] for k in s.get("static", [])]   # [추가] 고정 청크 (별표 등)
    seen = {(c["law"], c["article"]) for c in anchors}
    anchor_cats = {cat for c in anchors for cat in c.get("category", [])}
    extra = [
        c
        for c in r.search(s["query"], top_k=extra_k + len(anchors) + 3, on=on)
        if (c["law"], c["article"]) not in seen  # 고정 근거와 중복 제외
        and anchor_cats & set(c.get("category", []))
    ][
        :extra_k
    ]  # 같은 주제(카테고리)만 → 엉뚱한 조문 차단
    return {
        "code": code,
        "name": s["name"],
        "verdict": verdict,
        "facts": facts,
        "anchors": anchors,
        "extra": extra,
        "missing": missing,
        "note": s["note"],
        "point": s.get("point", ""),                             # [추가] 안내 핵심 (위치별 문구 구분)
        "guide": s.get("guide", ""),                             # 고정 안내 (기존 상황은 빈 문자열) — 동료 11/9 추가
    }
