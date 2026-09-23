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
