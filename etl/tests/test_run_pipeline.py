from pathlib import Path

from src.models import Document
from src.run_pipeline import fingerprint, is_up_to_date, remove_outputs, write_atomic

META = dict(
    doc_id="AAPL_2019_10K", company="apple-inc", ticker="AAPL", fiscal_year=2019,
    exchange="NASDAQ", s3_key="k", local_path="data/raw/AAPL_2019.pdf", size_mb=1.0, n_pages=10,
)


def outputs(tmp_path: Path, fp: str | None) -> tuple[Path, Path]:
    doc_path, chunk_path = tmp_path / "AAPL_2019_10K.json", tmp_path / "AAPL_2019_10K.jsonl"
    write_atomic(chunk_path, "{}\n")
    write_atomic(doc_path, Document(**META, etl_fingerprint=fp).model_dump_json())
    return doc_path, chunk_path


def test_fingerprint_depends_on_scope_and_is_stable():
    assert fingerprint("10k") == fingerprint("10k")
    assert fingerprint("10k") != fingerprint("all")


def test_outputs_from_the_same_code_are_reused(tmp_path):
    current = fingerprint("10k")
    assert is_up_to_date(*outputs(tmp_path, current), current)


def test_outputs_from_older_code_or_another_scope_are_redone(tmp_path):
    current = fingerprint("10k")
    assert not is_up_to_date(*outputs(tmp_path, "old-version"), current)
    assert not is_up_to_date(*outputs(tmp_path, None), current)  # made before fingerprints existed
    assert not is_up_to_date(*outputs(tmp_path, fingerprint("all")), current)


def test_missing_or_broken_outputs_are_redone(tmp_path):
    current = fingerprint("10k")
    doc_path, chunk_path = outputs(tmp_path, current)
    chunk_path.unlink()
    assert not is_up_to_date(doc_path, chunk_path, current)
    doc_path.write_text("not json", encoding="utf-8")
    chunk_path.write_text("{}\n", encoding="utf-8")
    assert not is_up_to_date(doc_path, chunk_path, current)


def test_out_of_scope_outputs_are_removed(tmp_path):
    doc_path, chunk_path = outputs(tmp_path, "any")
    remove_outputs(doc_path, chunk_path)
    assert not doc_path.exists() and not chunk_path.exists()
    remove_outputs(doc_path, chunk_path)  # already gone: no error


def test_atomic_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "x.jsonl"
    write_atomic(path, "a\n")
    assert path.read_text(encoding="utf-8") == "a\n"
    assert list(tmp_path.iterdir()) == [path]
