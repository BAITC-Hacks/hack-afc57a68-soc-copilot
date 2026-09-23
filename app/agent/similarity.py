"""Семантическое сходство пунктов.

* tfidf  — символьные n-граммы (3–5), работает офлайн и детерминированно;
* openai — эмбеддинги OpenAI с дисковым кэшем.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3

import numpy as np

from app import config
from app.runtime import similarity_backend

_STOP = re.compile(r"\b(в|и|по|на|с|к|о|об|для|за|из|от|до|а|также|том|числе|т\.ч\.)\b", re.I)


class EmbeddingUnavailable(RuntimeError):
    pass


def normalize(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[«»\"'()\[\];:,.\-–—/]", " ", t)
    t = _STOP.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


class Similarity:
    def __init__(self, backend: str | None = None):
        self.backend = backend or similarity_backend()
        self._vectorizer = None

    # ---------- tfidf ----------
    def fit(self, corpus: list[str]) -> "Similarity":
        if self.backend == "tfidf":
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                               sublinear_tf=True, min_df=1)
            normalized = list(dict.fromkeys(normalize(t) for t in corpus if normalize(t)))
            self._vectorizer.fit(normalized or ['пустой документ'])
        return self

    def embed(self, texts: list[str]) -> np.ndarray:
        if self.backend == "openai":
            return self._openai_embed(texts)
        if self._vectorizer is None:
            self.fit(texts)
        m = self._vectorizer.transform([normalize(t) for t in texts])
        return m.toarray()

    def matrix(self, a: list[str], b: list[str]) -> np.ndarray:
        if not a or not b:
            return np.zeros((len(a), len(b)), dtype=float)
        ea, eb = self.embed(a), self.embed(b)
        na = np.linalg.norm(ea, axis=1, keepdims=True) + 1e-9
        nb = np.linalg.norm(eb, axis=1, keepdims=True) + 1e-9
        return (ea / na) @ (eb / nb).T

    # ---------- openai ----------
    def _openai_embed(self, texts: list[str]) -> np.ndarray:
        from openai import OpenAI

        os.makedirs(config.CACHE_DIR, exist_ok=True)
        path = os.path.join(config.CACHE_DIR, 'embeddings.sqlite3')
        inputs = [normalize(t)[:8000] or ' ' for t in texts]
        keys = [hashlib.sha256((config.EMBEDDING_MODEL + '\0' + t).encode()).hexdigest() for t in inputs]
        db = sqlite3.connect(path, timeout=120)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector TEXT NOT NULL)')
            db.commit()
            db.execute('BEGIN IMMEDIATE')
            cache = {}
            for key in dict.fromkeys(keys):
                row = db.execute('SELECT vector FROM embeddings WHERE key=?', (key,)).fetchone()
                if row:
                    cache[key] = json.loads(row[0])
            missing = list({k: t for k, t in zip(keys, inputs) if k not in cache}.items())
            if missing:
                client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=45, max_retries=1)
                for i in range(0, len(missing), 100):
                    chunk = missing[i:i + 100]
                    response = client.embeddings.create(model=config.EMBEDDING_MODEL, input=[t for _, t in chunk])
                    data = sorted(response.data, key=lambda item: item.index)
                    if [item.index for item in data] != list(range(len(chunk))):
                        raise ValueError('Incomplete embedding response')
                    for (key, _), item in zip(chunk, data):
                        cache[key] = item.embedding
                        db.execute('INSERT OR REPLACE INTO embeddings VALUES (?, ?)', (key, json.dumps(item.embedding)))
            matrix = np.asarray([cache[k] for k in keys], dtype=float)
            if matrix.ndim != 2 or matrix.shape[1] == 0 or not np.isfinite(matrix).all():
                raise ValueError('Invalid embeddings')
            db.commit()
            return matrix
        except Exception as exc:
            db.rollback()
            raise EmbeddingUnavailable('Сервис эмбеддингов недоступен') from exc
        finally:
            db.close()
