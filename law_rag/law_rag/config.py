"""프로젝트 공통 설정 — 값을 바꿀 땐 이 파일(또는 .env)만 수정"""
import os
from pathlib import Path

from dotenv import load_dotenv  # .env 파일의 API 키를 환경변수로 읽어옴

BASE_DIR = Path(__file__).resolve().parent  # 이 파일이 있는 폴더 = 프로젝트 루트
for env in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):  # 프로젝트 폴더 or 상위 폴더의 .env 사용
    if env.exists():
        load_dotenv(env)
        break

DATA_DIR = BASE_DIR / "data"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"  # 파싱·청킹 결과 (검색 서버가 읽는 파일)
EVAL_DIR = BASE_DIR / "eval"

# ── 법령 목록 ──────────────────────────────────────────
# 지금은 법률만. 시행령·시행규칙을 추가할 때 여기에 한 줄씩 추가 → 같은 인덱스, 다른 namespace
LAWS = [
    {
        "key": "act",
        "name": "도로교통법",
        "namespace": "road-traffic-act",
        "glob": "도로교통법*.doc",
        "exclude": ("시행령", "시행규칙"),
    },
    {
        "key": "rule",
        "name": "도로교통법 시행규칙",
        "namespace": "road-traffic-rule",
        "glob": "도로교통법 시행규칙*.doc",
        "exclude": (),
        # 시행규칙 전체(288청크)를 넣으면 행정 절차 조문이 법률 조문을 밀어내 정답률이 떨어짐(실측)
        # → 운전자 행동과 직접 관련된 조문만 사용. 신호의 뜻(별표 2)은 data/manual_chunks.jsonl
        "include": ("제9조", "제16조", "제19조", "제31조", "제39조", "제40조"),
    },
    # {"key": "dec", "name": "도로교통법 시행령", "namespace": "road-traffic-decree",
    #  "glob": "도로교통법 시행령*.doc", "exclude": ()},
]

# ── 청킹 ─────────────────────────────────────────────
# 수업 예제(소득세법)는 RecursiveCharacterTextSplitter 1500자였지만,
# 법령은 조→항→호 구조가 명확해 '구조 단위' 분할이 더 정확함. e5 임베딩 한도(507토큰) 때문에 500자.
MAX_CHUNK_CHARS = 500

# ── 임베딩 공급자 ───────────────────────────────────────
# pinecone : multilingual-e5-large (추가 키 불필요, 무료)  ← 기본값 (어제 쓰던 것)
# upstage  : solar-embedding-2 (한국어 강점, UPSTAGE_API_KEY 필요)
# openai   : text-embedding-3-small (OPENAI_API_KEY 필요)
# ※ 공급자마다 차원이 달라 인덱스를 따로 만듦 (무료 플랜 인덱스 5개 제한 주의)
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "pinecone")
EMBED_SPECS = {
    "pinecone": {
        "query": "multilingual-e5-large",
        "passage": "multilingual-e5-large",
        "dim": 1024,
    },
    # 수업 자료의 solar-embedding-1-large(4096차원)는 2026-12-31 종료 예정 → 후속 모델 사용
    "upstage": {
        "query": "solar-embedding-2-query",
        "passage": "solar-embedding-2-passage",
        "dim": 1024,
    },
    "openai": {
        "query": "text-embedding-3-small",
        "passage": "text-embedding-3-small",
        "dim": 1536,
    },
}
EMBED_DIM = EMBED_SPECS[EMBED_PROVIDER]["dim"]

# ── Pinecone ────────────────────────────────────────
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
_BASE_INDEX = os.getenv("PINECONE_INDEX", "road-traffic-law")
INDEX_NAME = (
    _BASE_INDEX if EMBED_PROVIDER == "pinecone" else f"{_BASE_INDEX}-{EMBED_PROVIDER}"
)
CLOUD, REGION = "aws", "us-east-1"  # Starter(무료) 플랜은 aws us-east-1만 가능
PINECONE_RERANK_MODEL = "bge-reranker-v2-m3"  # Pinecone 호스팅 다국어 리랭커 (Cross-Encoder)

# ── 리랭크 방식 ────────────────────────────────────────
# none     : 리랭크 안 함  ← 기본값 (step4_eval.py로 효과 확인 후 바꿀 것)
# tfidf    : 문자 n-gram TF-IDF 코사인 (수업 ch9_14, 무료·오프라인)
# pinecone : bge-reranker (수업 ch9_13의 Cohere와 같은 Cross-Encoder 방식, 무료 플랜 월 한도 작음)
RERANK_MODE = os.getenv("RERANK_MODE", "none")

# ── 카테고리 필터 (수업 ch9_12) ─────────────────────────
# 질문에서 카테고리를 뽑아 같은 카테고리 청크만 검색. 구어체 질문은 카테고리가 틀리게 잡힐 수 있어
# 기본은 끔 → step4_eval.py에서 켰을 때 성능이 오르는지 확인 후 결정
USE_CATEGORY_FILTER = os.getenv("USE_CATEGORY_FILTER", "0") == "1"

# ── LLM 공급자 (답변 생성·질의 표준화용, 선택) ─────────────
# 실제 서비스 답변은 앱의 Gleo LLM이 생성. 서버 LLM은 테스트·질의표준화·백업용
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai / upstage / ollama
LLM_SPECS = {
    "openai": {
        "base_url": None,
        "key_env": "OPENAI_API_KEY",
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    },
    # solar-mini·solar-pro2/3은 2026-10-30 종료 예정 → solar-pro4 / solar-mini4 사용
    "upstage": {
        "base_url": "https://api.upstage.ai/v1",
        "key_env": "UPSTAGE_API_KEY",
        "model": os.getenv("UPSTAGE_MODEL", "solar-mini4"),
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "key_env": None,
        "model": os.getenv("OLLAMA_MODEL", "exaone3.5:2.4b"),
    },
}

# ── 법률 우선 원칙 ─────────────────────────────────────
# 시행규칙·별표는 법률을 보충하는 근거. 질문에 아래 단어가 없으면 법률 조문 뒤로 보냄
# (예: "우회전 적색" → 법률 제25조·제27조가 먼저, "우회전 신호등" → 시행규칙 별표 2가 먼저)
SUBLAW_TRIGGERS = (
    "신호등",
    "삼색등",
    "화살표",
    "시행규칙",
    "별표",
    "빗길",
    "눈길",
    "폭우",
    "안개",
    "감속",
    "고장자동차의 표지",
    "안전삼각대",
    "안전띠 미착용",
    "수신호",
    "지정차로",
    "1차로",
)

# ── 검색 파라미터 ─────────────────────────────────────
BM25_TOP_K = 20  # 키워드 검색 후보 수
DENSE_TOP_K = 20  # 벡터 검색 후보 수
RERANK_CANDIDATES = 10  # 리랭크에 넘길 후보 수 (수업: 1차 k=10 → 2차 top 3~5)
FINAL_TOP_K = 5  # LLM에 넘길 최종 근거 수
RRF_K = 60  # RRF 융합 상수 (논문 기본값)
MIN_RERANK_SCORE = 0.05  # Pinecone 리랭크 1위 점수가 이보다 낮으면 "근거 부족" (실측 후 조정)


def find_raw_doc(law: dict) -> Path:
    """원본 법령 파일 자동 탐색: data/ → 프로젝트 폴더 → 상위 폴더"""
    for folder in (DATA_DIR, BASE_DIR, BASE_DIR.parent):
        for p in sorted(folder.glob(law["glob"])):
            if not any(x in p.name for x in law["exclude"]):
                return p
    raise FileNotFoundError(
        f"'{law['glob']}' 파일을 찾지 못했습니다. data 폴더에 원본 .doc 파일을 넣어주세요.\n"
        f"  찾아본 폴더: {DATA_DIR} / {BASE_DIR} / {BASE_DIR.parent}"
    )
