"""Runtime settings shared with the index lane."""

import os
from pathlib import Path

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
EMBEDDING_DIMS = int(os.environ.get("EMBEDDING_DIMS", "768"))
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

ES_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
ES_INDEX = os.environ.get("ES_INDEX", "filinglens-chunks")

CANDIDATE_TOP_K = int(os.environ.get("SEARCH_CANDIDATE_TOP_K", "50"))
FINAL_TOP_K = int(os.environ.get("SEARCH_TOP_K", "5"))


def data_dir() -> Path:
    if os.environ.get("DATA_DIR"):
        return Path(os.environ["DATA_DIR"])
    # search/src/config.py -> repository root
    return Path(__file__).resolve().parents[2] / "data"


def validate() -> None:
    if EMBEDDING_DIMS != 768:
        raise ValueError("BAAI/bge-base-en-v1.5 must use 768-dimensional embeddings")
    if CANDIDATE_TOP_K < FINAL_TOP_K:
        raise ValueError(
            "SEARCH_CANDIDATE_TOP_K must be greater than or equal to SEARCH_TOP_K"
        )
    if FINAL_TOP_K < 1:
        raise ValueError("SEARCH_TOP_K must be positive")
