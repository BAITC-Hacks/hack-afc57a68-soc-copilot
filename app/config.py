"""Настройки OrgTrace. Все значения читаются из переменных окружения (.env)."""
import os

try:  # .env необязателен
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# tfidf — офлайн, без API-ключа (воспроизводимо); openai — эмбеддинги OpenAI
SIMILARITY_BACKEND = os.getenv("SIMILARITY_BACKEND", "tfidf")
# LLM используется только если есть ключ и USE_LLM=1
USE_LLM = os.getenv("USE_LLM", "1") == "1" and bool(OPENAI_API_KEY)
USE_CACHE = os.getenv("USE_CACHE", "0") == "1"

# Пороги сходства (откалиброваны для tfidf на контрольном комплекте)
if SIMILARITY_BACKEND == "openai":
    SIM_KEPT, SIM_LOST, SIM_DUP = 0.88, 0.70, 0.90
else:
    SIM_KEPT, SIM_LOST, SIM_DUP = 0.80, 0.50, 0.80

QUOTE_MIN_SCORE = 90          # порог rapidfuzz для верификатора цитат
MAX_VERIFY_RETRIES = 2
CACHE_DIR = os.getenv("CACHE_DIR", ".cache")
DEMO_CACHE_FILE = os.getenv("DEMO_CACHE_FILE", "demo_cache/report_08_09.json")
