from functools import lru_cache
from pathlib import Path

import faiss
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


class PolicyRAGPipeline:
    def __init__(self, doc_dir: str = "knowledge_base/policies"):
        self.doc_dir = Path(doc_dir)
        self.chunks: list[dict[str, str]] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.index: faiss.IndexFlatIP | None = None
        self.ingest()

    def ingest(self) -> int:
        if not self.doc_dir.exists():
            return 0

        chunks = []
        for file in sorted(self.doc_dir.glob("*.md")):
            content = file.read_text(encoding="utf-8")
            sections = content.split("\n## ")

            title = sections[0].replace("# ", "").strip()
            for sec in sections[1:]:
                lines = sec.strip().split("\n", 1)
                heading = lines[0].strip()
                body = lines[1].strip() if len(lines) > 1 else ""
                full_text = f"Policy: {title} | Topic: {heading}\n{body}"
                chunks.append({
                    "doc": file.name,
                    "title": title,
                    "topic": heading,
                    "text": full_text,
                })

        if not chunks:
            return 0

        self.chunks = chunks
        corpus = [c["text"] for c in chunks]
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
        tfidf_matrix = self.vectorizer.fit_transform(corpus).toarray().astype("float32")

        faiss.normalize_L2(tfidf_matrix)
        self.index = faiss.IndexFlatIP(tfidf_matrix.shape[1])
        self.index.add(tfidf_matrix)

        return len(chunks)

    def search(self, query: str, top_k: int = 2, min_score: float = 0.15) -> list[dict]:
        return [dict(item) for item in self._search_cached(query.strip().lower(), top_k, min_score)]

    @lru_cache(maxsize=512)
    def _search_cached(self, query: str, top_k: int, min_score: float) -> tuple:
        return tuple(self._search(query, top_k, min_score))

    def _search(self, query: str, top_k: int, min_score: float) -> list[dict]:
        if not self.index or not self.vectorizer:
            return []

        q_vec = self.vectorizer.transform([query]).toarray().astype("float32")
        faiss.normalize_L2(q_vec)

        scores, indices = self.index.search(q_vec, min(top_k, len(self.chunks)))
        results = []

        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and score >= min_score:
                item = dict(self.chunks[idx])
                item["score"] = float(score)
                results.append(item)

        return results


policy_rag = PolicyRAGPipeline()


if __name__ == "__main__":
    count = policy_rag.ingest()
    print(f"Ingested {count} policy chunks into FAISS vector index.")

    test_queries = [
        "What is the minimum balance required in metro branches?",
        "What is the zero liability timeframe for reporting fraud?",
        "How is statement password calculated?",
    ]
    for q in test_queries:
        print(f"\nQuery: {q}")
        matches = policy_rag.search(q, top_k=1)
        for m in matches:
            print(f"[{m['topic']}] (score: {m['score']:.3f}):\n{m['text']}\n")
