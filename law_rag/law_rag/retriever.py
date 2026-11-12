"""
하이브리드 검색기 (Hybrid Retriever)

  질문 ─┬─ ① 조문번호 직접조회   ("제27조" 같은 표현이 있으면 바로 가져옴)
        ├─ ② 질의 표준화         (rule: 사전 덧붙임 / llm: LLM 재작성)          ← 수업 ch9_11
        ├─ ③ 카테고리 필터(선택)  (질문 카테고리와 겹치는 청크만)                 ← 수업 ch9_12
        ├─ ④ BM25 키워드 검색    (Kiwi 형태소 분석, 로컬)
        ├─ ⑤ Dense 벡터 검색     (Pinecone, 임베딩 공급자 선택 가능)
        ├─ ⑥ RRF 융합            (④⑤ 순위 합치기)
        ├─ ⑦ 2단계 리랭크(선택)  (tfidf: 문자 n-gram / pinecone: Cross-Encoder)  ← 수업 ch9_13·14
        └─ ⑧ 유효기간 필터 + 조문 중복 제거
"""
import json
import re
from datetime import date
from typing import Optional

from kiwipiepy import Kiwi
from rank_bm25 import BM25Okapi

import config
from categories import categorize
from query_normalizer import normalize

RE_JO = re.compile(r"제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?")  # "27조", "제13조의2"
KEEP_TAGS = (
    "NNG",
    "NNP",
    "NNB",
    "VV",
    "VA",
    "XR",
    "SL",
    "SN",
    "MAG",
)  # BM25에 쓸 품사(명사·동사·형용사 등)


def today_int() -> int:
    return int(date.today().strftime("%Y%m%d"))


def is_valid(c: dict, on: int) -> bool:
    return c["eff_from"] <= on < c["eff_to"]  # on 날짜에 시행 중인 조문인가?


class HybridRetriever:
    def __init__(
        self,
        use_dense: bool = True,
        rerank: Optional[str] = None,
        norm: str = "rule",
        category_filter: Optional[bool] = None,
    ):
        """
        use_dense       : Pinecone 벡터 검색 사용 여부 (False면 키 없이 BM25만)
        rerank          : "none" / "tfidf" / "pinecone"  (None이면 .env의 RERANK_MODE)
        norm            : 질의 표준화 "none" / "rule" / "llm"
        category_filter : 카테고리 필터 (None이면 .env의 USE_CATEGORY_FILTER)
        """
        if not config.CHUNKS_PATH.exists():
            raise FileNotFoundError(
                "data/chunks.jsonl이 없습니다. 먼저 python step1_parse.py 를 실행하세요."
            )
        self.chunks = [
            json.loads(l) for l in open(config.CHUNKS_PATH, encoding="utf-8")
        ]
        self.by_id = {c["id"]: c for c in self.chunks}

        self.kiwi = Kiwi()
        self.bm25 = BM25Okapi(
            [self._tokens(c["text"]) for c in self.chunks]
        )  # 본문 색인 (청크 앞에 조문 제목 포함)
        # ※ 제목 전용 BM25도 실험했으나 홀드아웃 Hit@1이 73%→47%로 하락해 제외함

        self.use_dense = use_dense
        self.rerank = rerank or config.RERANK_MODE
        self.norm = norm
        self.category_filter = (
            config.USE_CATEGORY_FILTER if category_filter is None else category_filter
        )
        self.use_bm25 = True  # 평가(ablation)에서 Dense 단독 측정용
        self.namespaces = sorted({c["namespace"] for c in self.chunks})
        if (
            self.use_dense or self.rerank == "pinecone"
        ) and not config.PINECONE_API_KEY:
            raise RuntimeError(
                ".env에 PINECONE_API_KEY가 없습니다. 키 없이 쓰려면 --no-dense 옵션을 붙이세요."
            )
        self._index = None

    @property
    def index(self):
        if self._index is None:
            from pinecone import Pinecone

            self._pc = Pinecone(api_key=config.PINECONE_API_KEY)
            self._index = self._pc.Index(config.INDEX_NAME)
        return self._index

    # ── 형태소 토큰화 (품사태깅 후 내용어만 사용) ──
    def _tokens(self, text: str):
        out = []
        for t in self.kiwi.tokenize(text):
            if not t.tag.startswith(KEEP_TAGS):
                continue
            out.append(t.form)
            if (
                t.tag.startswith("NN") and len(t.form) >= 3
            ):  # 복합명사 보정: "난폭운전" → 난폭/폭운/운전
                out += [t.form[i : i + 2] for i in range(len(t.form) - 1)]
        return out

    # ① 조문번호 직접조회
    def article_chunks(
        self,
        num: int,
        sub: int = 0,
        on: Optional[int] = None,
        law: Optional[str] = None,
    ):
        on = on or today_int()
        return [
            c
            for c in self.chunks
            if c["article_num"] == num
            and c["article_sub"] == sub
            and is_valid(c, on)
            and (law is None or c["law"] == law)
        ]

    def _direct(self, q, on):
        ids = []
        for m in RE_JO.finditer(q):
            ids += [
                c["id"]
                for c in self.article_chunks(int(m.group(1)), int(m.group(2) or 0), on)
            ]
        return ids

    # ④ BM25
    def _bm25(self, q, on, k, cats):
        scores = self.bm25.get_scores(self._tokens(q))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        out = []
        for i in order:
            c = self.chunks[i]
            if scores[i] <= 0:
                break
            if is_valid(c, on) and (not cats or set(cats) & set(c.get("category", []))):
                out.append(c["id"])
                if len(out) >= k:
                    break
        return out

    # ⑤ Dense (Pinecone) — 법령별 namespace를 모두 조회 후 점수순 병합
    def _dense(self, q, on, k, cats):
        from embedder import embed

        vec = embed([q], "query")[0]
        flt = {"eff_from": {"$lte": on}, "eff_to": {"$gt": on}}  # 유효기간 필터를 DB에서 바로 적용
        if cats:
            flt["category"] = {"$in": cats}  # 수업 ch9_12의 $in 필터
        matches = []
        for ns in self.namespaces:
            res = self.index.query(
                vector=vec, top_k=k, namespace=ns, filter=flt, include_metadata=False
            )
            matches += [(m["score"], m["id"]) for m in res["matches"]]
        matches.sort(reverse=True)
        # 로컬 chunks.jsonl에 없는 ID = Pinecone에 옛날 데이터 → 무시 (step2_index.py --reset 권장)
        return [i for _, i in matches if i in self.by_id][:k]

    # ⑥ RRF: 여러 순위표를 "1/(k+순위)" 점수로 합산 → 점수 스케일이 달라도 공정하게 합칠 수 있음
    @staticmethod
    def _rrf(rank_lists, k=config.RRF_K):
        score = {}
        for ranks in rank_lists:
            for r, doc_id in enumerate(ranks):
                score[doc_id] = score.get(doc_id, 0) + 1 / (k + r + 1)
        return sorted(score, key=lambda d: -score[d])

    # ⑦-a TF-IDF 리랭크 (수업 ch9_14): 문자 2~3gram → 띄어쓰기·조사 차이에 강함, 무료
    def _rerank_tfidf(self, q, ids):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        docs = [f"{self.by_id[i]['title']} {self.by_id[i]['text']}" for i in ids]
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3))
        m = vec.fit_transform([q] + docs)
        sims = cosine_similarity(m[0:1], m[1:])[0]
        return sorted(zip(ids, sims), key=lambda x: -x[1])

    # ⑦-b Pinecone 리랭크 (수업 ch9_13의 Cohere와 같은 Cross-Encoder 방식)
    def _rerank_pinecone(self, q, ids):
        self.index  # Pinecone 클라이언트 준비
        docs = [{"id": i, "text": self.by_id[i]["text"]} for i in ids]
        res = self._pc.inference.rerank(
            model=config.PINECONE_RERANK_MODEL,
            query=q,
            documents=docs,
            top_n=len(docs),
            return_documents=False,
        )
        return [(ids[r.index], float(r.score)) for r in res.data]

    def search(
        self,
        question: str,
        top_k: int = config.FINAL_TOP_K,
        on: Optional[int] = None,
        detail: bool = False,
    ):
        """
        반환: 청크 목록 (detail=True면 {"chunks", "confident", "top_score", "query", "categories", "used"})
        - 같은 조문의 여러 청크는 가장 높은 1개만 (LLM에 다양한 조문을 넘기기 위함)
        """
        on = on or today_int()
        q = normalize(question, self.norm)  # ② 질의 표준화
        cats = categorize(q) if self.category_filter else []  # ③ 질문 카테고리 (없으면 필터 안 함)
        direct = self._direct(question, on)

        lists = []
        if self.use_bm25:
            lists.append(self._bm25(q, on, config.BM25_TOP_K, cats))
        if self.use_dense:
            lists.append(self._dense(q, on, config.DENSE_TOP_K, cats))
        fused = self._rrf(lists)

        top_score = None
        if self.rerank != "none" and fused:
            cand = fused[: config.RERANK_CANDIDATES]
            ranked = (
                self._rerank_tfidf(q, cand)
                if self.rerank == "tfidf"
                else self._rerank_pinecone(question, cand)
            )  # Cross-Encoder엔 원 질문 그대로
            fused = [i for i, _ in ranked] + fused[len(cand) :]
            top_score = ranked[0][1] if (ranked and self.rerank == "pinecone") else None

        # 법률 우선: 하위 법령(시행규칙·별표)은 질문이 그쪽을 가리킬 때만 제 순위 유지
        if not any(t in q.replace(" ", "") for t in config.SUBLAW_TRIGGERS):
            fused = [i for i in fused if self.by_id[i]["law"] == "도로교통법"] + [
                i for i in fused if self.by_id[i]["law"] != "도로교통법"
            ]

        result, seen = [], set()
        for i in dict.fromkeys(direct + fused):  # 직접조회 결과를 맨 앞에
            c = self.by_id[i]
            key = (c["law"], c["article"])
            if key in seen and i not in direct:
                continue
            seen.add(key)
            result.append(c)
            if len(result) >= max(top_k, len(direct)):
                break

        if not detail:
            return result
        confident = bool(result) and (
            top_score is None or top_score >= config.MIN_RERANK_SCORE or bool(direct)
        )
        return {
            "chunks": result,
            "confident": confident,
            "top_score": top_score,
            "query": q,
            "categories": cats,
            "used": {
                "dense": self.use_dense,
                "rerank": self.rerank,
                "norm": self.norm,
                "category_filter": self.category_filter,
                "embed": config.EMBED_PROVIDER,
            },
        }


def references(chunks) -> str:
    """'참고 조항' 문자열 (수업 ch9_12 extract_articles_from_docs): 근거 조문 + 그 조문이 인용한 조문"""
    main = list(dict.fromkeys(c["article"] for c in chunks))
    refs = [r for c in chunks for r in c.get("refs", []) if r not in main]
    law = chunks[0]["law"] if chunks else "도로교통법"
    s = f"{law} " + ", ".join(main) if main else ""
    if refs:
        s += f" (관련: {', '.join(dict.fromkeys(refs))})"
    return s
