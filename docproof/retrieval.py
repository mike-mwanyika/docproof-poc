"""Hybrid retrieval for the PoC: keyword (BM25) plus embeddings, merged by rank (reciprocal rank fusion).

Two separate indexes are built from the same class: one per case (the package under review) and one for the
knowledge base (approved guidelines). They are never mixed, so a guideline cannot be cited as the applicant's
evidence or the reverse. Chunks follow the document's own sections and keep file, page and box for citation.
In-process and small on purpose; the target store is PostgreSQL with pgvector (decision D-M5).
No reranker yet: Ollama does not serve cross-encoder rerankers.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .case import LogicalDoc

MAX_CHARS = 700
_TOK = re.compile(r"\w+", re.UNICODE)


def tokens(s: str) -> list[str]:
    return [t.lower() for t in _TOK.findall(s)]


@dataclass
class Chunk:
    id: int
    text: str
    file: str
    page: int
    bbox: list | None
    heading: str
    doc_cls: str | None
    meta: dict = field(default_factory=dict)


def chunks_from_doc(doc: LogicalDoc, start_id: int = 0, meta: dict | None = None) -> list[Chunk]:
    """One chunk per section (a heading and what follows it), split if longer than MAX_CHARS."""
    out: list[Chunk] = []
    heading, buf, first = "", [], None

    def flush():
        nonlocal buf, first
        if buf:
            text = "\n".join(buf)
            out.append(Chunk(start_id + len(out), (heading + "\n" + text).strip() if heading else text, doc.file,
                             first["page"], first["bbox"], heading, doc.cls, dict(meta or {})))
        buf, first = [], None

    for line in doc.all_lines():
        if not line["text"]:
            continue
        if line["type"] == "heading":
            flush()
            heading = line["text"]
            continue
        if first is None:
            first = line
        buf.append(line["text"])
        if sum(len(b) for b in buf) > MAX_CHARS:
            flush()
    flush()
    if not out and doc.pages:  # a document of headings only still gets a chunk
        out.append(Chunk(start_id, heading or doc.file, doc.file, doc.pages[0], None, heading, doc.cls, dict(meta or {})))
    return out


class Index:
    def __init__(self, chunks: list[Chunk], llm=None):
        self.chunks = chunks
        self.llm = llm
        self.toks = [tokens(c.text) for c in chunks]
        self.df = Counter(t for ts in self.toks for t in set(ts))
        self.avgdl = sum(len(t) for t in self.toks) / max(len(self.toks), 1)
        self.vecs = llm.embed([c.text for c in chunks]) if llm and chunks else None

    def _bm25(self, q: list[str], i: int, k1=1.5, b=0.75) -> float:
        tf = Counter(self.toks[i])
        n = len(self.chunks)
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(self.toks[i]) / self.avgdl))
        return s

    def search(self, query: str, k: int = 5, where=None) -> list[tuple[Chunk, float]]:
        ids = [i for i, c in enumerate(self.chunks) if where is None or where(c)]
        if not ids:
            return []
        q = tokens(query)
        kw = sorted(ids, key=lambda i: -self._bm25(q, i))
        ranks = [kw]
        if self.vecs is not None:
            qv = self.llm.embed([query])[0]
            qn = math.sqrt(sum(x * x for x in qv)) or 1.0

            def cos(i):
                v = self.vecs[i]
                return sum(a * b for a, b in zip(qv, v)) / (qn * (math.sqrt(sum(x * x for x in v)) or 1.0))
            ranks.append(sorted(ids, key=lambda i: -cos(i)))
        fused = Counter()
        for r in ranks:
            for pos, i in enumerate(r):
                fused[i] += 1.0 / (60 + pos)
        return [(self.chunks[i], s) for i, s in fused.most_common(k)]
