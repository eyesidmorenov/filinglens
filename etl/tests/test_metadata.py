from pathlib import Path

from src.metadata import load_inventory, make_doc_id, metadata_for, parse_local_name, parse_s3_key


def test_parse_local_name():
    assert parse_local_name("AAPL_2019.pdf") == {"ticker": "AAPL", "fiscal_year": 2019}
    assert parse_local_name("data/raw/brk.b_2020.pdf") == {"ticker": "BRK.B", "fiscal_year": 2020}
    assert parse_local_name("notes.txt") is None


def test_parse_s3_key():
    meta = parse_s3_key("nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf")
    assert meta == {"company": "apple-inc", "exchange": "NASDAQ", "ticker": "AAPL", "fiscal_year": 2019}


def test_doc_id_keeps_team_convention():
    assert make_doc_id("msft", 2020) == "MSFT_2020_10K"


def test_inventory_row_wins_over_file_name(tmp_path: Path):
    inv = tmp_path / "inventario.csv"
    inv.write_text(
        "doc_id,company,ticker,fiscal_year,exchange,s3_key,local_path,size_mb\n"
        "AAPL_2019_10K,apple-inc,AAPL,2019,NASDAQ,"
        "nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf,data/raw/AAPL_2019.pdf,5.25\n",
        encoding="utf-8",
    )
    pdf = tmp_path / "AAPL_2019.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    meta = metadata_for(pdf, load_inventory(inv))
    assert meta["company"] == "apple-inc"
    assert meta["fiscal_year"] == 2019
    assert meta["size_mb"] == 5.25
    assert meta["doc_id"] == "AAPL_2019_10K"


def test_file_name_fallback(tmp_path: Path):
    pdf = tmp_path / "TSLA_2020.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    meta = metadata_for(pdf, {})
    assert meta["ticker"] == "TSLA" and meta["fiscal_year"] == 2020
