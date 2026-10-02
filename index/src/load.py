"""
Load ETL chunks into Elasticsearch with their BGE embeddings.

    python -m src.load                              # every data/chunks/*.jsonl
    python -m src.load --doc AAPL_2019_10K          # one document
    python -m src.load --recreate                   # drop and rebuild the index
    python -m src.load --doc AAPL_2019_10K --check "What are Apple's main risk factors?"

What the loader guarantees:
  - A document's chunks in the index are exactly the ones in its .jsonl: after
    writing them, any older chunk of that document is deleted, so re-chunking
    leaves no orphans (and the document is never missing from the index).
  - A full load (no --doc) also removes documents that no longer have a .jsonl
    (for example a filing the ETL now skips as out of scope).
  - Embeddings are cached in data/embeddings/<model>/<doc_id>.npz, keyed by a
    hash of the exact text embedded, so only new or changed chunks are embedded.
  - An existing index with a different mapping is never reused silently.
"""

import argparse
import hashlib
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np
from haystack import Document
from haystack.document_stores.types import DuplicatePolicy
from haystack_integrations.components.embedders.sentence_transformers import (
    SentenceTransformersDocumentEmbedder,
)
from haystack_integrations.document_stores.elasticsearch import ElasticsearchDocumentStore

from . import config
from .documents import chunk_to_document, embedding_text, index_mapping, mapping_problems, read_chunks


class MappingMismatchError(Exception):
    pass


def make_store(recreate: bool = False) -> ElasticsearchDocumentStore:
    expected = index_mapping(config.EMBEDDING_DIMS)
    store = ElasticsearchDocumentStore(
        hosts=config.ES_URL,
        index=config.ES_INDEX,
        custom_mapping=expected,
        embedding_similarity_function="cosine",
    )
    client = store.client  # connects, and creates the index with our mapping if missing
    if recreate:
        client.indices.delete(index=config.ES_INDEX)
        return make_store()
    actual = client.indices.get_mapping(index=config.ES_INDEX)[config.ES_INDEX]["mappings"]
    problems = mapping_problems(actual, expected)
    if problems:
        raise MappingMismatchError(
            f"Index '{config.ES_INDEX}' exists with a different mapping:\n  - "
            + "\n  - ".join(problems)
            + "\nRebuild it with --recreate (its chunks are reloaded from data/chunks)."
        )
    return store


def indexed_doc_ids(store: ElasticsearchDocumentStore) -> set[str]:
    res = store.client.search(
        index=config.ES_INDEX, size=0, aggs={"ids": {"terms": {"field": "doc_id", "size": 10_000}}}
    )
    return {b["key"] for b in res["aggregations"]["ids"]["buckets"]}


def delete_doc(store: ElasticsearchDocumentStore, doc_id: str, keep: list[str] | None = None) -> int:
    """Delete a document's chunks from the index, except the chunk ids in `keep`."""
    query = {"bool": {"filter": [{"term": {"doc_id": doc_id}}]}}
    if keep:
        query["bool"]["must_not"] = [{"ids": {"values": keep}}]
    res = store.client.delete_by_query(index=config.ES_INDEX, query=query, refresh=True)
    return res["deleted"]


def text_key(text: str) -> str:
    return hashlib.sha256(f"{config.EMBEDDING_MODEL}\n{text}".encode()).hexdigest()


def cache_path(doc_id: str) -> Path:
    folder = config.data_dir() / "embeddings" / config.EMBEDDING_MODEL.replace("/", "__")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{doc_id}.npz"


def load_cache(path: Path) -> dict[str, np.ndarray]:
    if not path.exists():
        return {}
    try:
        data = np.load(path)
        keys, vectors = data["keys"], data["vectors"]
    except (OSError, ValueError, KeyError):
        return {}  # unreadable cache: recompute
    if vectors.ndim != 2 or vectors.shape[1] != config.EMBEDDING_DIMS or not np.isfinite(vectors).all():
        return {}
    return dict(zip(keys.tolist(), vectors))


@lru_cache(maxsize=1)
def embedder() -> SentenceTransformersDocumentEmbedder:
    """Loaded on first use only: a reload served entirely from cache never loads the model."""
    e = SentenceTransformersDocumentEmbedder(
        model=config.EMBEDDING_MODEL, normalize_embeddings=True, batch_size=16, progress_bar=False
    )
    e.warm_up()
    return e


def embed(documents: list[Document], doc_id: str) -> tuple[list[Document], int]:
    """Attach embeddings, reusing cached vectors for unchanged texts. Returns (documents, computed)."""
    texts = [embedding_text(d) for d in documents]
    keys = [text_key(t) for t in texts]
    path = cache_path(doc_id)
    cached = load_cache(path)

    missing = [i for i, k in enumerate(keys) if k not in cached]
    if missing:
        to_embed = [Document(id=documents[i].id, content=texts[i]) for i in missing]
        for i, d in zip(missing, embedder().run(documents=to_embed)["documents"]):
            cached[keys[i]] = np.asarray(d.embedding, dtype=np.float32)

    vectors = np.stack([cached[k] for k in keys]) if keys else np.zeros((0, config.EMBEDDING_DIMS), np.float32)
    if vectors.shape[1] != config.EMBEDDING_DIMS:
        raise ValueError(
            f"{config.EMBEDDING_MODEL} returns {vectors.shape[1]} dims, "
            f"the index expects {config.EMBEDDING_DIMS}. Set EMBEDDING_DIMS."
        )
    # Keep only this document's current chunks in its cache file
    np.savez(path, keys=np.array(keys), vectors=vectors)
    return [replace(d, embedding=v.tolist()) for d, v in zip(documents, vectors)], len(missing)


@lru_cache(maxsize=1)
def tokenizer():
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(config.EMBEDDING_MODEL)


def count_over_limit(documents: list[Document]) -> int:
    """Texts that BGE would truncate, measured on exactly what is embedded (header included)."""
    if not documents:
        return 0
    ids = tokenizer()([embedding_text(d) for d in documents], add_special_tokens=True)["input_ids"]
    return sum(1 for x in ids if len(x) > config.MAX_TOKENS)


def check(store: ElasticsearchDocumentStore, question: str, doc_ids: list[str]) -> None:
    """Smoke test: the same question through BM25 and through vectors."""
    from haystack_integrations.components.embedders.sentence_transformers import (
        SentenceTransformersTextEmbedder,
    )
    from haystack_integrations.components.retrievers.elasticsearch import (
        ElasticsearchBM25Retriever,
        ElasticsearchEmbeddingRetriever,
    )

    filters = {"field": "doc_id", "operator": "in", "value": doc_ids} if doc_ids else None
    text_embedder = SentenceTransformersTextEmbedder(
        model=config.EMBEDDING_MODEL, prefix=config.QUERY_PREFIX, normalize_embeddings=True, progress_bar=False
    )
    text_embedder.warm_up()
    query_vector = text_embedder.run(text=question)["embedding"]

    for name, docs in (
        ("BM25", ElasticsearchBM25Retriever(document_store=store, top_k=3).run(query=question, filters=filters)),
        ("Vector", ElasticsearchEmbeddingRetriever(document_store=store, top_k=3).run(
            query_embedding=query_vector, filters=filters)),
    ):
        print(f"\n--- {name}: {question}")
        for d in docs["documents"]:
            m = d.meta
            print(f"  {d.score:.3f}  {d.id}  [{m['section']} {m.get('section_title', '')}, p.{m['page']}, "
                  f"{m['chunk_type']}]  {d.content[:90].replace(chr(10), ' ')}...")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load ETL chunks into Elasticsearch with BGE embeddings")
    ap.add_argument("--doc", action="append", default=[], help="doc_id to load (repeatable); default: all")
    ap.add_argument("--recreate", action="store_true", help="delete and recreate the index first")
    ap.add_argument("--check", metavar="QUESTION", help="run a test question after loading")
    args = ap.parse_args(argv)

    chunk_dir = config.data_dir() / "chunks"
    files = sorted(chunk_dir.glob("*.jsonl"))
    if args.doc:
        files = [f for f in files if f.stem in args.doc]
    if not files:
        print(f"No chunk files found in {chunk_dir} for {args.doc or 'any document'}", file=sys.stderr)
        return 1

    try:
        store = make_store(recreate=args.recreate)
    except MappingMismatchError as e:
        print(e, file=sys.stderr)
        return 2
    print(f"Model {config.EMBEDDING_MODEL} -> index '{config.ES_INDEX}' at {config.ES_URL}")

    if not args.doc:
        # Full load: documents without a .jsonl any more must leave the index too
        for doc_id in sorted(indexed_doc_ids(store) - {f.stem for f in files}):
            print(f"  {doc_id:<16} removed from the index ({delete_doc(store, doc_id)} chunks): no chunk file")

    for path in files:
        documents = [chunk_to_document(c) for c in read_chunks(path)]
        documents, computed = embed(documents, path.stem)
        # Write first, then drop the chunks that no longer exist: search never sees the document empty
        written = store.write_documents(documents, policy=DuplicatePolicy.OVERWRITE)
        removed = delete_doc(store, path.stem, keep=[d.id for d in documents])
        over = count_over_limit(documents)
        print(f"  {path.stem:<16} {written:>4} chunks written, {removed:>4} old removed  "
              f"({computed} embedded now, {len(documents) - computed} from cache)  "
              f"over {config.MAX_TOKENS} tokens: {over}")

    print(f"\nIndex '{config.ES_INDEX}' now holds {store.count_documents()} chunks")
    if args.check:
        check(store, args.check, args.doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
