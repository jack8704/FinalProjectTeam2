"""
국가법령정보센터 '.doc' 저장본 → 조문 단위 구조화 → 검색용 청크

핵심 처리
1) .doc 파일은 실제로 RTF 형식 → 한글이 \\uNNNN 형태로 들어 있어 직접 디코딩
2) 본문(제1장~)과 부칙을 분리하고 본문만 사용
3) 같은 조문이 2번 나오면 = [현행본 + 시행예정본] → eff_from / eff_to(유효기간) 부여
   + "~까지 유효함" 한시 규정은 기한 다음날부터 제외 (예: 제53조의5)
4) 긴 조문은 항(①②…) → 호(1. 2. …) → 문장 경계에서 잘라 500자 이내 청크로 만듦
   호 단위로 잘린 청크에는 소속 항의 머리문장을 붙여 "무엇이 금지인지" 문맥 유지
"""
import re
from dataclasses import dataclass, field

from categories import categorize

# ─────────────────────────────────────────────────────
# 1. RTF → 텍스트
# ─────────────────────────────────────────────────────
_CTRL = re.compile(rb"\\([a-zA-Z]+)(-?\d+)? ?")  # RTF 제어어: \단어[숫자][공백]
_SKIP_DEST = {
    b"fonttbl",
    b"colortbl",
    b"stylesheet",
    b"info",
    b"pict",
    b"footer",
    b"header",
    b"fldinst",
    b"listtable",
    b"listoverridetable",
    b"generator",
}  # 본문이 아닌 그룹(글꼴표, 그림, 머리말 등)


def rtf_to_text(raw: bytes) -> str:
    out, stack, skip, uc = [], [], False, 1
    i, n = 0, len(raw)
    while i < n:
        c = raw[i : i + 1]
        if c == b"{":  # 그룹 시작 → 현재 skip 상태 저장
            stack.append(skip)
            i += 1
            continue
        if c == b"}":  # 그룹 끝 → skip 상태 복원
            skip = stack.pop() if stack else False
            i += 1
            continue
        if c == b"\\":
            m = _CTRL.match(raw, i)
            if m:
                word, arg = m.group(1), m.group(2)
                i = m.end()
                if word == b"bin":  # 이미지 바이너리 → 길이만큼 건너뜀
                    i += int(arg or 0)
                    continue
                if word in _SKIP_DEST:
                    skip = True
                    continue
                if skip:
                    continue
                if word == b"u":  # \u-17259? → 유니코드 한 글자
                    v = int(arg)
                    out.append(chr(v + 65536 if v < 0 else v))
                    for _ in range(uc):  # 뒤따르는 대체문자('?') 건너뜀
                        i += 4 if raw[i : i + 2] == b"\\'" else 1
                    continue
                if word == b"uc":
                    uc = int(arg)
                elif word in (b"par", b"line", b"row"):
                    out.append("\n")  # 문단 끝 → 줄바꿈
                elif word in (b"cell", b"tab"):
                    out.append("\t")
                continue
            nxt = raw[i + 1 : i + 2]
            if nxt == b"*":  # \* = 무시해도 되는 그룹
                skip = True
                i += 2
                continue
            if nxt == b"'":  # \'hh = 1바이트 문자
                if not skip:
                    out.append(
                        bytes([int(raw[i + 2 : i + 4], 16)]).decode("cp1252", "replace")
                    )
                i += 4
                continue
            if nxt in (b"\\", b"{", b"}"):  # 이스케이프된 특수문자
                if not skip:
                    out.append(nxt.decode())
                i += 2
                continue
            i += 2
            continue
        if c not in (b"\r", b"\n") and not skip:
            out.append(c.decode("latin1"))
        i += 1
    text = "".join(out)
    text = re.sub(r"[ \t]+\n", "\n", text)  # 줄 끝 공백 제거
    return re.sub(r"\n{3,}", "\n\n", text)  # 빈 줄 3개 이상 → 2개


def load_law_text(path) -> str:
    raw = open(path, "rb").read()
    if raw.lstrip().startswith(b"{\\rtf"):  # RTF 형식이면 직접 디코딩
        return rtf_to_text(raw)
    for enc in ("utf-8-sig", "cp949"):  # txt로 저장한 경우 (윈도우 기본 cp949도 허용)
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ValueError(f"인코딩을 알 수 없는 파일: {path}")


# ─────────────────────────────────────────────────────
# 2. 조문 파싱
# ─────────────────────────────────────────────────────
RE_CHAPTER = re.compile(r"^(제\d+장(?:의\d+)?)\s+(.+?)(?:\s*<.*)?$")  # 제4장의2 자율주행...
RE_ARTICLE = re.compile(
    r"^제(\d+)조(?:의(\d+))?(?:\(([^)]*)\)|\s+(삭제))\s*(.*)$"
)  # 제27조(보행자의 보호) ...
RE_EFFECTIVE = re.compile(
    r"^\[시행일:\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\]"
)  # [시행일: 2027. 6. 3.] 제44조
RE_BASE_DATE = re.compile(
    r"\[시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\]"
)  # 문서 머리의 [시행 2026. 10. 13.]
RE_EXPIRE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일까지 유효함")  # 한시 규정 기한
RE_ANNOT = re.compile(r"\s*<(?:개정|신설|전문개정|단서신설|본문개정)[^>]*>")  # <개정 2018. 3. 27.> 이력표시
RE_BRACKET = re.compile(r"^\[(?:전문개정|제목개정|본조신설|종전|시행일|법률 제)[^\]]*\].*$", re.M)  # 안내문 줄
RE_PARA = re.compile(r"^[①-⑳]")  # 항 시작 기호
RE_ITEM = re.compile(r"^\d+(?:의\d+)?\.\s")  # 호 시작 (1. / 21의3.)


@dataclass
class Article:
    num: int  # 조 번호 (27)
    sub: int  # 가지번호 (제13조의2 → 2, 없으면 0)
    title: str  # 조문 제목
    chapter: str  # 소속 장
    lines: list = field(default_factory=list)  # 원문 줄들
    deleted: bool = False
    eff_from: int = 0  # 유효 시작일 (yyyymmdd, 0 = 이미 시행 중)
    eff_to: int = 99991231  # 유효 종료일 ('미만' 조건으로 사용)

    @property
    def label(self) -> str:  # "제13조의2"
        return f"제{self.num}조" + (f"의{self.sub}" if self.sub else "")

    @property
    def raw_text(self) -> str:
        return "\n".join(self.lines)


def _ymd(m) -> int:
    return int(f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}")


def _next_day(ymd: int) -> int:
    from datetime import date, timedelta

    d = date(ymd // 10000, ymd // 100 % 100, ymd % 100) + timedelta(days=1)
    return int(d.strftime("%Y%m%d"))


def parse_articles(text: str):
    lines = [l.strip() for l in text.splitlines()]

    # (1) 본문 시작: 목차가 아닌 실제 "제1조(목적) ..." 줄 → 그 위의 첫 장 제목부터
    start = next(i for i, l in enumerate(lines) if l.startswith("제1조(목적) "))
    s = start
    while s > 0 and not lines[s].startswith("제1장"):
        s -= 1
    if lines[s].startswith("제1장"):
        start = s
    # (2) 본문 끝: 첫 '부칙' (개정 이력이라 운전 안내용 검색에서 제외)
    end = next(
        (i for i, l in enumerate(lines) if i > start and l.startswith("부칙")), len(lines)
    )

    base = RE_BASE_DATE.search(text)
    base_date = _ymd(base) if base else 0

    articles, chapter, cur = [], "", None
    for line in lines[start:end]:
        if not line:
            continue
        if m := RE_CHAPTER.match(line):  # 장 제목 줄 → 이후 조문의 소속 장으로 기록
            chapter = f"{m.group(1)} {m.group(2)}".strip()
            continue
        if line.startswith("제") and "절" in line.split()[0]:  # 절 제목은 건너뜀
            continue
        if m := RE_ARTICLE.match(line):
            cur = Article(
                num=int(m.group(1)),
                sub=int(m.group(2) or 0),
                title=(m.group(3) or "삭제").strip(),
                chapter=chapter,
                deleted=bool(m.group(4)),
            )
            cur.lines.append(line)
            articles.append(cur)
            continue
        if cur:
            cur.lines.append(line)

    # (3) 시행일·유효기한 처리
    for a in articles:
        for l in a.lines:
            if m := RE_EFFECTIVE.match(l):  # [시행일: ...] → 그 날부터 유효 (시행예정본)
                a.eff_from = _ymd(m)
            if m := RE_EXPIRE.search(l):  # "~까지 유효함" → 기한 다음날부터 제외
                a.eff_to = _next_day(_ymd(m))

    #     안전장치: 같은 조문·같은 시행일이 2번 → 목차 등이 섞인 것. 마지막(본문) 것만 남김
    last = {(a.num, a.sub, a.eff_from): a for a in articles}
    if len(last) < len(articles):
        dup = sorted(
            {a.label for a in articles if last[(a.num, a.sub, a.eff_from)] is not a}
        )
        print(f"  ⚠ 중복 조문 {dup} → 마지막 것만 사용 (원본 형식 확인 권장)")
        articles = [a for a in articles if last[(a.num, a.sub, a.eff_from)] is a]
    #     같은 조문이 현행본/예정본 두 개면 → 현행본은 예정본 시행일 전날까지만 유효
    by_key = {}
    for a in articles:
        by_key.setdefault((a.num, a.sub), []).append(a)
    for versions in by_key.values():
        future = [v for v in versions if v.eff_from > base_date]
        current = [v for v in versions if v.eff_from <= base_date]
        if future and current:
            for c in current:
                c.eff_to = min(c.eff_to, min(f.eff_from for f in future))
    return articles, base_date


# ─────────────────────────────────────────────────────
# 3. 청킹
# ─────────────────────────────────────────────────────
def tabs_to_markdown(text: str) -> str:
    """RTF 표(셀=탭)를 Markdown 표 행으로 변환 (수업 ch9_11). 시행령 별표(과태료 표) 추가 시 효과가 큼"""
    out = []
    for line in text.split("\n"):
        cells = [c.strip() for c in line.split("\t")]
        out.append(
            "| " + " | ".join(cells) + " |"
            if len([c for c in cells if c]) >= 2
            else line.replace("\t", " ")
        )
    return "\n".join(out)


def clean_body(article: Article) -> str:
    """임베딩/LLM에 넣을 깨끗한 본문: 개정이력·안내문 제거, 표 → Markdown"""
    t = RE_BRACKET.sub("", article.raw_text)
    t = RE_ANNOT.sub("", t)
    t = tabs_to_markdown(t)
    return re.sub(r"\n{2,}", "\n", t).strip()


RE_REF = re.compile(r"제(\d{1,3})조(?:의(\d+))?")  # 본문이 참조하는 다른 조문 (수업 ch9_12의 article 추출)


def extract_refs(text: str, self_label: str) -> list:
    refs = {
        f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        for m in RE_REF.finditer(text)
        if "」" not in text[max(0, m.start() - 12) : m.start()]
    }  # 「소방기본법」 제10조 같은 타법 인용 제외
    refs.discard(self_label)
    return sorted(refs, key=lambda x: [int(n) for n in re.findall(r"\d+", x)])


def _split_units(body: str, max_chars: int):
    """조문 → 항 → 호 → 문장 순으로 쪼갬. 반환: [(텍스트, 소속 항 머리문장)]"""
    paras, buf = [], []
    for line in body.split("\n"):
        if RE_PARA.match(line) and buf:  # 새 항 시작 → 이전 항 저장
            paras.append("\n".join(buf))
            buf = []
        buf.append(line)
    if buf:
        paras.append("\n".join(buf))

    units = []
    for p in paras:
        if len(p) <= max_chars:
            units.append((p, ""))
            continue
        ls = p.split("\n")
        head, items = ls[0], ls[1:]  # 항 본문(머리) + 호 목록
        units.append((head, ""))
        cur = []
        for l in items:
            if RE_ITEM.match(l) and cur:
                units.append(("\n".join(cur), head))
                cur = []
            cur.append(l)  # 목(가. 나.)은 소속 호에 붙임
        if cur:
            units.append(("\n".join(cur), head))

    final = []  # 그래도 길면 문장 끝("다.") 기준으로 한 번 더
    for u, head in units:
        if len(u) <= max_chars:
            final.append((u, head))
            continue
        buf = ""
        for s in re.split(r"(?<=다\.)\s+", u):
            if buf and len(buf) + len(s) > max_chars - 50:
                final.append((buf, head))
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            final.append((buf, head))
    return final


def _short(head: str, n: int = 110) -> str:
    return head if len(head) <= n else head[:n] + "…"


def make_chunks(articles, law: dict, max_chars: int = 500, base_date: int = 0):
    chunks = []
    for a in articles:
        if a.deleted:  # '삭제' 조문은 검색 대상 제외
            continue
        header = f"[{law['name']} {a.label}({a.title})]"  # 모든 청크 앞에 조문 표제 (문맥 유지)
        groups, cur = [], ""
        for u, head in _split_units(clean_body(a), max_chars):  # greedy packing
            if cur and len(cur) + len(u) + 1 > max_chars:
                groups.append(cur)
                cur = f"(…{_short(head)}) {u}" if head else u  # 호로 시작하면 항 머리문장 붙임
            else:
                cur = f"{cur}\n{u}" if cur else u
        if cur:
            groups.append(cur)

        ver = "f" if a.eff_from else "c"  # c = 현행, f = 시행예정
        art_cats = categorize(f"{a.title} {clean_body(a)}")  # 조문 전체 기준 카테고리 (청크 공통)
        for i, g in enumerate(groups):
            body_only = g.split("\n", 1)[-1] if g.startswith("[") else g
            chunks.append(
                {
                    "id": f"{law['key']}-a{a.num:03d}-{a.sub}-{ver}{a.eff_from or ''}-{i:02d}",  # Pinecone ID (ASCII)
                    "text": f"{header} {a.chapter}\n{g}",  # 임베딩·LLM에 들어가는 텍스트
                    "law": law["name"],
                    "namespace": law["namespace"],
                    "article": a.label,  # "제27조"
                    "article_num": a.num,
                    "article_sub": a.sub,
                    "title": a.title,
                    "chapter": a.chapter,
                    "category": categorize(f"{a.title} {g}")
                    or art_cats
                    or ["기타"],  # 청크 카테고리 (없으면 조문 기준)
                    "refs": extract_refs(
                        body_only, a.label
                    ),  # 이 청크가 언급하는 다른 조문 (참고 조항 표시용)
                    "eff_from": a.eff_from,  # 유효기간 필터용 (정수 yyyymmdd)
                    "eff_to": a.eff_to,
                    "status": "future"
                    if a.eff_from > base_date
                    else "current",  # 문서 기준일 대비
                    "part": i,
                    "n_parts": len(groups),
                }
            )
    return chunks
