"""
임베딩 공급자 전환 (수업 ch9_01: 모델별 한국어 성능 비교를 우리 데이터로 직접 재현하기 위함)

  embed(texts, kind)  kind = "passage"(문서 저장용) / "query"(질문용)
  - e5·Upstage는 문서/질문 모델(또는 모드)이 구분됨 → 반드시 맞춰 써야 성능이 나옴
"""
import os

import config

_pc = None
_oa = None


def _pinecone():
    global _pc
    if _pc is None:
        from pinecone import Pinecone

        _pc = Pinecone(api_key=config.PINECONE_API_KEY)
    return _pc


def _openai_compat():
    """Upstage도 OpenAI SDK로 호출 가능 (base_url만 변경) — 수업 ch9_03"""
    global _oa
    if _oa is None:
        from openai import OpenAI

        if config.EMBED_PROVIDER == "upstage":
            key = os.getenv("UPSTAGE_API_KEY")
            _oa = OpenAI(
                api_key=key,
                base_url="https://api.upstage.ai/v1",
                default_headers={"Accept-Encoding": "identity"},
            )
        else:
            key = os.getenv("OPENAI_API_KEY")
            _oa = OpenAI(api_key=key, default_headers={"Accept-Encoding": "identity"})
        if not key:
            raise RuntimeError(f".env에 {config.EMBED_PROVIDER.upper()}_API_KEY가 없습니다.")
    return _oa


def embed(texts: list, kind: str) -> list:
    """texts → 벡터 목록 (입력 순서 유지)"""
    spec = config.EMBED_SPECS[config.EMBED_PROVIDER]
    if config.EMBED_PROVIDER == "pinecone":
        res = _pinecone().inference.embed(
            model=spec[kind],
            inputs=texts,
            parameters={
                "input_type": kind,
                "truncate": "END",
            },  # e5: query / passage 구분 필수
        )
        return [d["values"] for d in res.data]
    res = _openai_compat().embeddings.create(model=spec[kind], input=texts)
    return [d.embedding for d in sorted(res.data, key=lambda d: d.index)]
