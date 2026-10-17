from src.company import looks_like_name, official_name

HEADER = "\n".join([
    "UNITED STATES",
    "SECURITIES AND EXCHANGE COMMISSION",
    "FORM 10-K",
    "For the fiscal year ended September 28, 2019",
    "Commission File Number: 001-36743",
])


def test_standard_cover_takes_the_line_above_the_caption():
    cover = HEADER + "\nApple Inc.\n(Exact name of Registrant as specified in its charter)\nCalifornia | 94-2404110"
    assert official_name(cover, cover, "apple-inc") == "Apple Inc."


def test_a_name_in_capitals_takes_the_spelling_of_the_filing_text():
    cover = HEADER + "\nIDEXX LABORATORIES, INC.\n(Exact name of registrant as specified in its charter)"
    text = cover + "\nIDEXX Laboratories, Inc. develops diagnostics. IDEXX Laboratories, Inc. sells them."
    assert official_name(cover, text, "idexx-laboratories-inc") == "IDEXX Laboratories, Inc."


def test_the_spelling_ignores_punctuation_and_needs_a_capital_first_letter():
    cover = HEADER + "\nCADENCE DESIGN SYSTEMS INC\n(Exact name of registrant as specified in its charter)"
    text = cover + "\nsee cadence design systems, inc. Cadence Design Systems, Inc. Cadence Design Systems, Inc."
    assert official_name(cover, text, "cadence-design-systems-inc") == "Cadence Design Systems, Inc."


def test_capitals_stay_when_the_text_never_spells_the_name_otherwise():
    cover = HEADER + "\nKLA CORPORATION\n(Exact name of registrant as specified in its charter)"
    assert official_name(cover, cover, "kla-tencor-corporation") == "KLA CORPORATION"


def test_a_table_cover_takes_the_first_registrant():
    cover = HEADER + "\n" + "\n".join([
        "Commission | Exact Name of Registrant as Specified in its Charter, | State of | I.R.S. Employer",
        "File Number | Principal Executive Office Address and Telephone Number | Incorporation | Identification No.",
        "001-06033 | United Airlines Holdings, Inc. | Delaware | 36-2675207",
        "001-10323 | United Airlines, Inc. | Delaware | 74-2099724",
    ])
    assert official_name(cover, cover, "united-airlines-holdings-inc") == "United Airlines Holdings, Inc."


def test_a_cover_without_the_caption_takes_the_first_company_shaped_line():
    cover = HEADER + "\nPaychex, Inc.\n911 Panorama Trail South\nA Delaware Corporation"
    assert official_name(cover, cover, "paychex-inc") == "Paychex, Inc."


def test_an_unreadable_cover_falls_back_to_the_text_by_the_s3_folder_name():
    text = "Activision Blizzard, Inc. is a leader. Activision Blizzard, Inc. reported revenue."
    assert official_name("", text, "activision-blizzard-inc") == "Activision Blizzard, Inc."


def test_the_apostrophe_is_the_one_people_type():
    cover = HEADER + "\nO’REILLY AUTOMOTIVE, INC.\n(Exact name of registrant as specified in its charter)"
    text = cover + "\nO’Reilly Automotive, Inc. and subsidiaries"
    assert official_name(cover, text, "oreilly-automotive-inc") == "O'Reilly Automotive, Inc."


def test_no_name_found_returns_none():
    assert official_name("UNITED STATES\nFORM 10-K", "nothing here", "inc") is None


def test_what_looks_like_a_company_name():
    assert looks_like_name("The Kraft Heinz Company")
    assert looks_like_name("Logitech International S.A.")
    assert not looks_like_name("Commission File Number 001-36743")
    assert not looks_like_name("A Delaware Corporation organized under the laws of the State of Delaware in 1979")
