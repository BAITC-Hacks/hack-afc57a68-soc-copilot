"""Семантическое сходство пунктов.

* tfidf  — символьные n-граммы (3–5), работает офлайн и детерминированно;
* openai — эмбеддинги OpenAI с дисковым кэшем.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import numpy as np

from app import config

_STOP = re.compile(r"\b(в|и|по|на|с|к|о|об|для|за|из|от|до|а|также|том|числе|т\.ч\.)\b", re.I)


def normalize(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[«»\"'()\[\];:,.\-–—/]", " ", t)
    t = _STOP.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


class Similarity:
    def __init__(self, backend: str | None = None):
        self.backend = backend or config.SIMILARITY_BACKEND
        self._vectorizer = None

    # ---------- tfidf ----------
    def fit(self, corpus: list[str]) -> "Similarity":
        if self.backend == "tfidf":
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                               sublinear_tf=True, min_df=1)
            self._vectorizer.fit([normalize(t) for t in corpus])
        return self

    def embed(self, texts: list[str]) -> np.ndarray:
        if self.backend == "openai":
            return self._openai_embed(texts)
        if self._vectorizer is None:
            self.fit(texts)
        m = self._vectorizer.transform([normalize(t) for t in texts])
        return m.toarray()

    def matrix(self, a: list[str], b: list[str]) -> np.ndarray:
        ea, eb = self.embed(a), self.embed(b)
        na = np.linalg.norm(ea, axis=1, keepdims=True) + 1e-9
        nb = np.linalg.norm(eb, axis=1, keepdims=True) + 1e-9
        return (ea / na) @ (eb / nb).T

    # ---------- openai ----------
    def _openai_embed(self, texts: list[str]) -> np.ndarray:
        from openai import OpenAI

        os.makedirs(config.CACHE_DIR, exist_ok=True)
        path = os.path.join(config.CACHE_DIR, "embeddings.json")
        cache = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        keys = [hashlib.sha1((config.EMBEDDING_MODEL + t).encode()).hexdigest() for t in texts]
        missing = [(k, t) for k, t in zip(keys, texts) if k not in cache]
        if missing:
            client = OpenAI(api_key=config.OPENAI_API_KEY)
            for i in range(0, len(missing), 100):
                chunk = missing[i:i + 100]
                resp = client.embeddings.create(model=config.EMBEDDING_MODEL,
                                                input=[t[:8000] for _, t in chunk])
                for (k, _), item in zip(chunk, resp.data):
                    cache[k] = item.embedding
            json.dump(cache, open(path, "w", encoding="utf-8"))
        return np.array([cache[k] for k in keys])
