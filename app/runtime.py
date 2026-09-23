"""Request-local settings; concurrent users never change process-wide config."""
from contextlib import contextmanager
from contextvars import ContextVar

from app import config

_mode: ContextVar[str | None] = ContextVar('analysis_mode', default=None)


def llm_enabled() -> bool:
    return config.USE_LLM and _mode.get() != 'deterministic'


def similarity_backend() -> str:
    return 'tfidf' if _mode.get() == 'deterministic' else config.SIMILARITY_BACKEND


@contextmanager
def analysis_mode(mode: str):
    if mode not in ('deterministic', 'llm'):
        raise ValueError('Неизвестный режим анализа')
    if mode == 'llm' and not config.USE_LLM:
        raise ValueError('Для AI-анализа настройте OPENAI_API_KEY и USE_LLM=1')
    token = _mode.set(mode)
    try:
        yield
    finally:
        _mode.reset(token)
