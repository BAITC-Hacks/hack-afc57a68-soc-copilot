import pytest

from app.agent.similarity import Similarity


@pytest.mark.parametrize("backend", ["tfidf", "openai"])
@pytest.mark.parametrize("left, right", [([], []), (["audit"], []), ([], ["audit"])])
def test_empty_matrix_preserves_shape_without_embedding(backend, left, right, monkeypatch):
    sim = Similarity(backend)

    def unexpected_embed(texts):
        pytest.fail("An empty comparison must not fit TF-IDF or request embeddings")

    monkeypatch.setattr(sim, "embed", unexpected_embed)
    result = sim.matrix(left, right)
    assert result.shape == (len(left), len(right))
    assert result.size == 0


def test_embedding_failure_restarts_with_tfidf(monkeypatch):
    from app import config
    from app.agent.similarity import EmbeddingUnavailable
    from app.pipeline import analyze
    from tests.conftest import BEFORE, AFTER
    monkeypatch.setattr(config, 'USE_LLM', True)
    monkeypatch.setattr(config, 'SIMILARITY_BACKEND', 'openai')
    def unavailable(self, texts):
        raise EmbeddingUnavailable('offline')
    monkeypatch.setattr(Similarity, '_openai_embed', unavailable)
    result = analyze(BEFORE, AFTER, mode='llm')
    assert result.meta['mode'] == 'deterministic'
    assert result.meta['similarity_backend'] == 'tfidf'
    assert result.summary['functions']['lost'] == 3
    assert any('Эмбеддинги' in w for w in result.meta['warnings'])
