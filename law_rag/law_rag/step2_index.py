"""
STEP 2. data/chunks.jsonl → 임베딩 → Pinecone 적재
실행:  python step2_index.py          (처음 1회, 법 개정·파서 수정 시 다시 실행)
       python step2_index.py --reset  (인덱스 삭제 후 새로 만들기 — 청크 ID 체계가 바뀌었을 때 필수)
"""
import json
import sys
import time

from pinecone import Pinecone, ServerlessSpec

import config
from embedder import embed

sys.stdout.reconfigure(encoding="utf-8")
BATCH = 90  # multilingual-e5-large 최대 배치 96개 → 여유 있게 90
META_KEYS = (
    "law",
    "article",
    "article_num",
    "article_sub",
    "title",
    "chapter",
    "category",
    "eff_from",
    "eff_to",
    "status",
    "text",
)  # 필터·표시용 메타데이터


def main(reset=False):
    if not config.PINECONE_API_KEY:
        sys.exit(".env 파일에 PINECONE_API_KEY를 넣어주세요.")
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    print(
        f"임베딩: {config.EMBED_PROVIDER} ({config.EMBED_DIM}차원) → 인덱스 {config.INDEX_NAME}"
    )

    if reset and pc.has_index(config.INDEX_NAME):
        print(f"인덱스 삭제: {config.INDEX_NAME}")
        pc.delete_index(config.INDEX_NAME)
    if pc.has_index(config.INDEX_NAME):  # 기존 인덱스 차원 확인 (공급자 바꿨는데 같은 인덱스면 에러)
        dim = pc.describe_index(config.INDEX_NAME).dimension
        if dim != config.EMBED_DIM:
            sys.exit(
                f"인덱스 차원({dim}) ≠ 임베딩 차원({config.EMBED_DIM}). --reset 하거나 PINECONE_INDEX를 바꾸세요."
            )
    if not pc.has_index(config.INDEX_NAME):  # 인덱스가 없으면 생성
        pc.create_index(
            name=config.INDEX_NAME,
            dimension=config.EMBED_DIM,  # 임베딩 모델 차원과 반드시 일치 (생성 후 변경 불가)
            metric="cosine",
            spec=ServerlessSpec(cloud=config.CLOUD, region=config.REGION),
        )
        while not pc.describe_index(config.INDEX_NAME).status["ready"]:
            time.sleep(1)  # 생성 완료까지 대기
    index = pc.Index(config.INDEX_NAME)

    chunks = [json.loads(l) for l in open(config.CHUNKS_PATH, encoding="utf-8")]
    for s in range(0, len(chunks), BATCH):
        batch = chunks[s : s + BATCH]
        vecs = embed([c["text"] for c in batch], "passage")  # 문서 쪽은 passage 모델/모드
        by_ns = {}
        for c, v in zip(batch, vecs):
            by_ns.setdefault(c["namespace"], []).append(
                {"id": c["id"], "values": v, "metadata": {k: c[k] for k in META_KEYS}}
            )
        for ns, vectors in by_ns.items():
            index.upsert(vectors=vectors, namespace=ns)
        print(f"  업로드 {s + len(batch)}/{len(chunks)}")
        time.sleep(0.5)  # 무료 플랜 요청 한도 여유

    time.sleep(3)
    print(index.describe_index_stats())


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
