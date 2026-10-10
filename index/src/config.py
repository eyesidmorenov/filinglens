"""
Settings shared by indexing and search. The search lane and the API container
must use exactly the same model, prefix and index, or retrieval fails silently.
"""

import os
from pathlib import Path

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
EMBEDDING_DIMS = int(os.environ.get("EMBEDDING_DIMS", "768"))
# BGE English v1.5 models expect this instruction on queries only, never on chunks
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MAX_TOKENS = 512  # BGE truncates longer inputs without warning
# Chunks per batch when embedding. On a laptop CPU, small batches waste less time on
# padding: 4 measured about 10% faster than 16 (i5-8265U, same vectors). On a GPU,
# a larger batch is faster: set EMBED_BATCH_SIZE=64.
EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "4"))

ES_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
ES_INDEX = os.environ.get("ES_INDEX", "filinglens-chunks")


def data_dir() -> Path:
    if os.environ.get("DATA_DIR"):
        return Path(os.environ["DATA_DIR"])
    # index/src/config.py -> repository root
    return Path(__file__).resolve().parents[2] / "data"
