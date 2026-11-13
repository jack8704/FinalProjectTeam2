"""
STEP 1. 원본 법령 파일 → data/chunks.jsonl
실행:  python step1_parse.py                  (data/ 등에서 원본 자동 탐색)
       python step1_parse.py "C:\\경로\\도로교통법.doc"   (파일 직접 지정, 법령 1개일 때)
"""
import json
import sys
from collections import Counter

import config
from law_parser import load_law_text, make_chunks, parse_articles

sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 터미널 한글 깨짐 방지


def parse_one(law: dict, path) -> list:
    text = load_law_text(path)  # RTF 디코딩
    articles, base_date = parse_articles(text)  # 조문 구조화
    if law.get("include"):  # 지정 조문만 사용 (시행규칙 등)
        articles = [a for a in articles if a.label in law["include"]]
    chunks = make_chunks(articles, law, config.MAX_CHUNK_CHARS, base_date)

    # ── 품질 점검 출력 ──
    alive = [a for a in articles if not a.deleted]
    lens = [len(c["text"]) for c in chunks]
    print(f"\n[{law['name']}]  원본: {path}")
    print(f"  기준 시행일        : {base_date}")
    print(f"  조문 수(삭제 포함) : {len(articles)}  / 유효 조문 {len(alive)}")
    print(
        f"  청크 수            : {len(chunks)}  (평균 {sum(lens)//len(lens)}자, 최대 {max(lens)}자)"
    )
    print(f"  상태별 청크        : {dict(Counter(c['status'] for c in chunks))}")
    print(
        "  시행예정 조문      :",
        sorted(
            {
                f"{c['article']}({c['eff_from']})"
                for c in chunks
                if c["status"] == "future"
            }
        ),
    )
    print(
        "  기한 만료 조문     :",
        sorted(
            {
                f"{c['article']}(~{c['eff_to']})"
                for c in chunks
                if c["eff_to"] < 99991231 and c["eff_to"] <= base_date
            }
        ),
    )
    return chunks


def load_manual_chunks() -> list:
    """data/manual_chunks.jsonl: 국가법령정보센터 본문 저장에 빠지는 별표를 사람이 옮겨 적은 것.
    필수: id, law, namespace, article, article_num, title, body, eff_from, eff_to, source"""
    path = config.DATA_DIR / "manual_chunks.jsonl"
    if not path.exists():
        return []
    from categories import categorize

    out = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        m = json.loads(line)
        out.append(
            {
                "id": m["id"],
                "law": m["law"],
                "namespace": m["namespace"],
                "text": f"[{m['law']} {m['article']}({m['title']})]\n{m['body']}",
                "article": m["article"],
                "article_num": m["article_num"],
                "article_sub": m.get("article_sub", 0),
                "title": m["title"],
                "chapter": m.get("chapter", ""),
                "category": categorize(f"{m['title']} {m['body']}") or ["기타"],
                "refs": [],
                "eff_from": m["eff_from"],
                "eff_to": m["eff_to"],
                "status": "current",
                "part": 0,
                "n_parts": 1,
                "source": m.get("source", "수동 입력"),
            }
        )
    print(
        f"\n[수동 입력 별표]  {len(out)}개: "
        + ", ".join(f"{c['law']} {c['article']}" for c in out)
    )
    return out


def main():
    config.DATA_DIR.mkdir(exist_ok=True)
    manual = sys.argv[1] if len(sys.argv) > 1 else None
    all_chunks = []
    for law in config.LAWS:
        path = (
            manual if (manual and len(config.LAWS) == 1) else config.find_raw_doc(law)
        )
        all_chunks += parse_one(law, path)

    all_chunks += load_manual_chunks()  # 본문 파일에 없는 별표 발췌 (수동 입력)

    ids = [c["id"] for c in all_chunks]
    assert len(ids) == len(set(ids)), "청크 ID 중복 발생 — law_parser 확인 필요"

    with open(
        config.CHUNKS_PATH, "w", encoding="utf-8"
    ) as f:  # 한 줄 = 청크 1개 (JSON Lines)
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\n저장: {config.CHUNKS_PATH}  (총 {len(all_chunks)}개)")


if __name__ == "__main__":
    main()
