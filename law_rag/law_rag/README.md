# 도로교통법 RAG 파이프라인 v2

원본: 국가법령정보센터 저장본 `도로교통법 [법률 제22067호, 2026.10.13. 시행]`

```
[원본 .doc(RTF)] → step1_parse → chunks.jsonl ─┬→ step2_index → Pinecone (Dense, 임베딩 공급자 선택)
  (조문 구조 청킹 + 카테고리·참조조문 메타데이터)  └→ BM25 (로컬, Kiwi 형태소)

자유 질문 → 조문번호 직접조회 + 질의 표준화(사전/LLM) → [카테고리 필터] → BM25 ∪ Dense → RRF
         → [2단계 리랭크: TF-IDF / Cross-Encoder] → 날짜 필터 → 프롬프트 → Gleo LLM → 답변 검증
상황 판정 → (규칙엔진: 금지/주의/가능) → 상황별 고정 근거 조문 + 보조 검색 → 설명 프롬프트 → Gleo LLM → 검증
```

---

## v1 → v2 변경점

| 구분 | 내용 |
|---|---|
| 상황 연결 | `situations.py` — 규칙엔진 판정(금지/주의/가능)에 고정 근거 조문을 붙여 설명. 판정은 LLM이 못 바꿈 |
| 답변 검증 | `guard.py` — 근거 밖 조문 인용·판정 뒤집기 감지 → 대체 멘트 |
| 수업 ch9_12 | 청크에 `category`(가중치 키워드), `refs`(인용 조문) 메타데이터 + 카테고리 `$in` 필터(선택) + 참고 조항 출력 |
| 수업 ch9_11 | 질의 표준화 2방식: `rule`(사전 덧붙임, 기본) / `llm`(사전 기반 LLM 재작성) |
| 수업 ch9_13·14 | 2단계 리랭크: `tfidf`(문자 2~3gram, 무료) / `pinecone`(Cross-Encoder) |
| 수업 ch9_01~04 | 임베딩(pinecone/upstage/openai)·LLM(openai/upstage/ollama) 공급자를 `.env`로 전환 |
| 수업 ch9_11 | RTF 표(탭 구분) → Markdown 표 변환 (시행령 별표 추가 대비) |
| 평가 | `step4_eval.py`가 기법별 on/off 비교표를 한 번에 출력 + `eval/results.csv` 누적 |
| 안정성 | 원본 자동 탐색, 중복 조문 방지, 한시 규정(~까지 유효함) 만료 처리, 윈도우 한글 출력 |

**청크 ID 형식이 바뀌어(`act-` 접두어) Pinecone은 반드시 `python step2_index.py --reset`으로 다시 올려야 함.**

---

## 실행 (Windows / VS Code 터미널)

```bash
.venv\Scripts\activate
pip install -r requirements.txt
pip install openai                   # Upstage/OpenAI 임베딩·서버 LLM을 쓸 때만

python step1_parse.py                # 1) 파싱·청킹 → data/chunks.jsonl (원본 .doc는 data/ 또는 상위 폴더에 두면 자동 탐색)
python step2_index.py --reset        # 2) 임베딩 → Pinecone (ID 형식 변경 때문에 처음 1번은 --reset)
python step3_ask.py "소화전 앞에 잠깐 차 세워도 돼?"          # 3) 자유 질문
python step4_eval.py                 # 4) 기법별 비교 (개발셋)
python step4_eval.py --holdout       #    최종 성적 (홀드아웃)
python step5_situation.py --check    # 5) 상황별 고정 근거가 원문에 있는지 점검
python step5_situation.py parking_hydrant 금지 "소화전까지 4.2m"
```

Pinecone 키 없이: 모든 스크립트에 `--no-dense`

---

## 파일 구성

| 파일 | 역할 |
|---|---|
| `config.py` | 경로·법령 목록·공급자·검색 파라미터 (값은 `.env`로도 변경) |
| `law_parser.py` | RTF 디코딩, 조문 파싱, 현행/시행예정/만료 구분, 구조 청킹, 메타데이터 |
| `categories.py` | 가중치 키워드 카테고리 분류 |
| `synonyms.py` | 구어 → 법령 용어 사전 |
| `query_normalizer.py` | 질의 표준화 (rule / llm) |
| `embedder.py` | 임베딩 공급자 전환 |
| `retriever.py` | 하이브리드 검색기 (핵심) + 참고 조항 문자열 |
| `situations.py` | 규칙엔진 상황코드 → 고정 근거 조문 |
| `prompt.py` | Q&A 프롬프트 / 상황 설명 프롬프트 |
| `guard.py` | LLM 답변 검증 + 대체 멘트 |
| `llm.py` | 서버 LLM 호출 (테스트·백업용, 실서비스는 Gleo) |
| `step1~5_*.py` | 실행 스크립트 |
| `eval/questions.jsonl` · `holdout.jsonl` | 개발셋 35 / 홀드아웃 15 (**홀드아웃 보고 튜닝 금지**) |
| `django_example/` | `/api/law/search`, `/api/law/situation`, `/api/law/check` |

---

## 수업 자료(소득세법 예제)와 다르게 한 부분과 이유 (심사 방어용)

| 수업 방식 | 이 프로젝트 | 이유 |
|---|---|---|
| RecursiveCharacterTextSplitter 1500자 | 조→항→호 구조 청킹 500자 | 법령은 구조가 명확함. 글자 수로 자르면 "5미터 이내인 곳"만 남고 "주정차 금지"가 잘림. e5 입력 한도 507토큰 |
| LLM으로 청크 title 생성 | 법령 공식 조문 제목 사용 | 이미 정확한 제목이 있음. LLM 요약은 비용·환각 위험만 추가 |
| 카테고리 `$in` 필터 상시 적용 | 기본 OFF, 평가로 결정 | 구어체 질문은 카테고리가 비거나 틀리게 잡혀 정답을 필터로 잘라낼 위험 |
| LLM이 질문을 '다시 씀' | 원 질문 + 표준화 질문을 함께 검색 | 오변환 시 원래 단어가 사라지는 피해 방지 |
| Cohere Rerank | Pinecone bge-reranker (같은 Cross-Encoder 방식) | 키 하나로 해결. 단 무료 월 한도가 작아 개발 중엔 TF-IDF/none |
| Upstage `embedding-query`(4096차원) | `solar-embedding-2`(1024차원) 옵션 | 기존 모델은 2026-12-31 종료 예정 (Upstage 공지) |
| Dense 검색만 | BM25 + Dense 하이브리드 | 법령은 "제27조", "횡단보도" 같은 정확한 단어가 중요 |

---

## 측정 결과 (v1, BM25 단독, 실제 원문 기준)

| 설정 | 개발셋 Hit@1 / @3 / @5 | 홀드아웃 Hit@1 / @3 / @5 |
|---|---|---|
| BM25, 머리문장 보존, 질의확장 X | 43% / 63% / 66% | 80% / 93% / 100% |
| BM25, 머리문장 보존 + 질의확장 | 63% / 86% / 94% | 80% / 93% / 100% |
| v2 신규 기법 (카테고리·TF-IDF·Dense·LLM표준화) | **step4_eval.py로 측정 필요** | **측정 필요** |

- 질의확장 사전은 개발셋 실패를 보고 만든 것이라 개발셋 수치가 부풀려져 있음 (홀드아웃 효과 0)
- 문항이 적어 1문항 = 개발셋 약 3%p, 홀드아웃 약 7%p → 실제 운전자 질문 100개 이상으로 확장 권장

---

## 한계 (반드시 보완)

- **법률만 들어 있음.** 과태료 금액은 시행령 별표, 신호 색깔별 의미는 시행규칙 별표에 있음 → `config.LAWS`에 추가 (표는 Markdown 변환됨, 별표 파싱은 실제 파일로 확인 필요)
- 상황별 고정 근거(`situations.py`)의 조문·키워드는 사람이 정한 것 → `step5_situation.py --check`로 원문 대조 필수
- 부칙(개정 이력) 제외. 법 개정 시 원본 교체 → step1, step2 재실행
