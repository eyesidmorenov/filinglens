# Test fixtures: EVERYTHING IS SYNTHETIC

`chunks_dummy.jsonl` holds 13 **invented** chunks (9 `doc_id`s), using real company names only so
the tests are readable. They are not data from real 10-K filings and have no relation to the
official corpus. They are never used in the demo or in the evaluation.

The tests index them into a `test_*` index with the team loader's mapping, adding `chunk_type`
(`table` for "Item 8", `text` for the rest) and `doc_type` (`10-K`).
