"""
Integration checks against the real sample PDFs in data/raw/.

Skipped when the sample is not on disk (the PDFs never go to the repository).
"""

import os
from pathlib import Path

import pytest

from src.extract import OutOfScopeError, extract_document
from src.metadata import load_inventory, metadata_for

DATA = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
RAW = DATA / "raw"

EXPECTED_TYPES = {
    "AAPL_2019.pdf": "10-K",
    "TSLA_2020.pdf": "10-K",
    "NVDA_2020.pdf": "10-K_wrapped",
    "INTC_2020.pdf": "10-K_wrapped",
    "MSFT_2020.pdf": "annual_report",
}

pytestmark = pytest.mark.skipif(not RAW.exists(), reason="sample PDFs not available")


@pytest.mark.parametrize("name,expected", EXPECTED_TYPES.items())
def test_sample_document_types(name: str, expected: str):
    pdf = RAW / name
    if not pdf.exists():
        pytest.skip(f"{name} not in the sample")
    doc = extract_document(pdf, metadata_for(pdf, load_inventory(RAW / "inventario.csv")), scope="all")
    assert doc.doc_type == expected


def test_investor_only_report_is_skipped_in_10k_scope():
    pdf = RAW / "MSFT_2020.pdf"
    if not pdf.exists():
        pytest.skip("MSFT_2020 not in the sample")
    with pytest.raises(OutOfScopeError):
        extract_document(pdf, metadata_for(pdf, {}), scope="10k")


def test_tesla_exhibits_are_dropped():
    pdf = RAW / "TSLA_2020.pdf"
    if not pdf.exists():
        pytest.skip("TSLA_2020 not in the sample")
    doc = extract_document(pdf, metadata_for(pdf, {}))
    assert doc.form_10k_pages is not None
    assert doc.form_10k_pages[1] < doc.n_pages / 2  # the 10-K is less than half the PDF
    assert max(p.page for p in doc.pages) <= doc.form_10k_pages[1]
