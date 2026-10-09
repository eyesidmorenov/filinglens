from pathlib import Path

import pytest

from src import run_pipeline
from src.extract import OutOfScopeError
from src.models import Document
from src.run_pipeline import fingerprint, is_up_to_date, orphan_outputs, remove_outputs, write_atomic

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


def test_outputs_whose_pdf_is_gone_are_found(tmp_path):
    clean_dir, chunk_dir = tmp_path / "clean", tmp_path / "chunks"
    clean_dir.mkdir(), chunk_dir.mkdir()
    for doc_id in ("AAPL_2019_10K", "CSX_2020_10K"):
        write_atomic(clean_dir / f"{doc_id}.json", "{}")
        write_atomic(chunk_dir / f"{doc_id}.jsonl", "{}\n")
    write_atomic(chunk_dir / "_stats.csv", "doc_id\n")
    write_atomic(clean_dir / "_skipped.csv", "file,reason\n")
    assert orphan_outputs(clean_dir, chunk_dir, {"AAPL_2019_10K"}) == [
        chunk_dir / "CSX_2020_10K.jsonl",
        clean_dir / "CSX_2020_10K.json",
    ]


def test_atomic_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "x.jsonl"
    write_atomic(path, "a\n")
    assert path.read_text(encoding="utf-8") == "a\n"
    assert list(tmp_path.iterdir()) == [path]


def leftover_outputs(data_dir: Path) -> tuple[Path, Path]:
    """data/raw holds only AAPL_2019.pdf, and CSX_2020 outputs remain from an earlier selection."""
    (data_dir / "raw").mkdir(parents=True)
    (data_dir / "raw" / "AAPL_2019.pdf").write_bytes(b"%PDF")
    (data_dir / "clean").mkdir()
    (data_dir / "chunks").mkdir()
    old_doc, old_chunks = data_dir / "clean" / "CSX_2020_10K.json", data_dir / "chunks" / "CSX_2020_10K.jsonl"
    write_atomic(old_doc, "{}")
    write_atomic(old_chunks, "{}\n")
    return old_doc, old_chunks


@pytest.fixture
def no_extraction(monkeypatch):
    def skip(pdf, meta, **kwargs):
        raise OutOfScopeError(f"{pdf.name}: not a real PDF")

    monkeypatch.setattr(run_pipeline, "extract_document", skip)


def test_outputs_without_pdf_are_listed_and_kept_by_default(tmp_path, no_extraction, capsys):
    # They may come from a shared chunks package and can't be rebuilt without their PDFs
    old_doc, old_chunks = leftover_outputs(tmp_path)
    assert run_pipeline.main(["--data-dir", str(tmp_path)]) == 0
    assert old_doc.exists() and old_chunks.exists()
    assert "CSX_2020_10K" in capsys.readouterr().out


def test_prune_deletes_outputs_without_pdf(tmp_path, no_extraction):
    old_doc, old_chunks = leftover_outputs(tmp_path)
    assert run_pipeline.main(["--data-dir", str(tmp_path), "--prune"]) == 0
    assert not old_doc.exists() and not old_chunks.exists()


def test_prune_needs_a_full_run():
    with pytest.raises(SystemExit):
        run_pipeline.main(["--limit", "3", "--prune"])


def test_a_file_that_cant_be_deleted_does_not_stop_the_run(tmp_path, no_extraction, capsys):
    leftover_outputs(tmp_path)
    # A directory can't be unlinked, like a file locked by another program on Windows
    (tmp_path / "chunks" / "MSFT_2020_10K.jsonl").mkdir()
    assert run_pipeline.main(["--data-dir", str(tmp_path), "--prune"]) == 0
    assert (tmp_path / "clean" / "_skipped.csv").exists()
    assert "could not remove MSFT_2020_10K.jsonl" in capsys.readouterr().err
