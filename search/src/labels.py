"""Fill relevant_chunk_ids in the evaluation set from evidence in the ETL chunks.

Labels come from what the chunks say, never from a retriever's ranking:

  numeric_results    chunks where a reported figure (read from the filing's income
                     statement) sits in the same table row or sentence as its metric
  legal_proceedings  every chunk of Item 3 (the question asks what Item 3 says,
                     even when it only points to a note)
  market_risk        every chunk of Item 7A
  controls           Item 9A chunks that state the conclusion ("concluded",
                     "were effective")
  broader questions  chunks of the expected section that mention at least two of
                     the question's topics (one, for single-topic questions)

Chunk ids change whenever the ETL re-chunks a filing, so run this again after
every new chunk package:

    python -m src.labels            # rewrites evaluation/questions.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import config
from .evaluation import DEFAULT_QUESTIONS

REVENUE = r"revenue|sales"
INCOME = r"net (?:income|earnings|loss)|income \(loss\)"

# Reported figures per numeric question, checked against each filing's statements
FIGURES: dict[str, list[tuple[str, str]]] = {
    "Q02": [("274,515", REVENUE), ("57,411", INCOME)],
    "Q06": [("15,785", REVENUE), ("11,520", r"digital media")],
    "Q07": [("2,569.8", REVENUE), ("(80.8)", INCOME)],
    "Q11": [("24,240", REVENUE), ("7,264", INCOME)],
    "Q15": [("8,803", REVENUE), ("2,699", INCOME)],
    "Q16": [("108,942", REVENUE), ("13,057", INCOME), ("13,323", INCOME)],
    "Q20": [("16,652", REVENUE), ("1,392", INCOME)],
    "Q24": [("2,448.5", REVENUE), ("1,680.5", r"gross profit")],
    "Q25": [("4,950", REVENUE), ("1,019", INCOME)],
    "Q29": [("10,271", REVENUE), ("5,667", INCOME)],
    "Q33": [("117,929", REVENUE), ("39,370", INCOME)],
    "Q34": [("22,119", REVENUE), ("5,386", INCOME)],
    "Q38": [("2,706,655", REVENUE), ("694,524", r"income from operations|operating income")],
    "Q42": [("4,526", REVENUE), ("762", INCOME)],
    "Q43": [("4,568,904", REVENUE), ("1,175,617", INCOME)],
    "Q47": [("10,044,736", REVENUE), ("2,251,753", INCOME)],
    "Q51": [("13,857", REVENUE), ("1,099", INCOME)],
    "Q52": [("25,868", REVENUE), ("3,870", INCOME), ("3,929", INCOME)],
    "Q56": [("10,918", REVENUE), ("62.0", r"gross margin")],
    "Q60": [("13,327,563", REVENUE), ("2,164,685", INCOME)],
    "Q61": [("3,691.9", REVENUE), ("1,034.4", INCOME)],
    "Q65": [("23,531", REVENUE), ("5,198", INCOME)],
    "Q69": [("29,060.6", REVENUE), ("4,872.1", r"operating income")],
    "Q70": [("14,383", REVENUE), ("5,017", INCOME)],
    "Q74": [("6,202,783", REVENUE), ("2,711,647", INCOME)],
}

# Topics named by each broader question
TOPICS: dict[str, str] = {
    "Q01": r"iPhone|Mac\b|iPad|Wearables|Services|distribution|retail|resellers|direct and indirect",
    "Q05": r"competit|cloud|cyber|security (?:breach|incident)|hack|data center",
    "Q09": r"subscription",
    "Q10": r"principal products|marketed products|product candidates?|pipeline|ENBREL|Prolia|Repatha|Neulasta|Otezla",
    "Q14": r"game development|develop|consumer preferences|platform|online",
    "Q18": r"Cable Communications|NBCUniversal|Sky|revenue",
    "Q19": r"consult|digital|technology services|operations services|Digital Business|Digital Operations",
    "Q23": r"quality|recall|regulat|FDA|competit",
    "Q27": r"net bookings|live services",
    "Q28": r"marketplace|buyers|sellers",
    "Q32": r"privacy|data|regulat|engagement",
    "Q36": r"product sales",
    "Q37": r"diagnostic|instrument|services|Companion Animal|Water|Livestock",
    "Q41": r"sequenc|regulat|competit",
    "Q45": r"revenue|gross margin",
    "Q46": r"wafer|deposition|etch|clean|Customer Support|products",
    "Q50": r"lodging demand|demand|franchis|cyber",
    "Q54": r"net revenues|operating income",
    "Q55": r"platform|GPU|gaming|data center|automotive|professional visualization|markets?",
    "Q59": r"competit|inventory|distribution|team members|workforce|labor",
    "Q63": r"service revenue",
    "Q64": r"QCT|QTL|licens",
    "Q68": r"store|commodit|coffee|labor|partners|competit",
    "Q72": r"revenue|operating profit",
    "Q73": r"approved|medicines|pipeline|cystic fibrosis|TRIKAFTA|SYMDEKO|KALYDECO|ORKAMBI",
}
ONE_TOPIC = {"Q09", "Q27", "Q36", "Q63"}

# The ETL labels Illumina 2019's financial statements as Item 7A (its body has no
# Item 8 heading): only pages 40-41 are the real Item 7A. Remove once the ETL is fixed.
SECTION_PAGES = {"Q40": (40, 41)}

CONCLUSION = re.compile(r"(?:were|was|are|is)\s+(?:not\s+)?effective|conclu", re.IGNORECASE)
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def units(text: str) -> list[str]:
    """Table rows and prose sentences: a figure counts only next to its metric."""
    return [unit for line in text.split("\n") for unit in SENTENCE_BREAK.split(line)]


def has_figure(text: str, figures: list[tuple[str, str]]) -> bool:
    return any(
        figure in unit and re.search(metric, unit, re.IGNORECASE)
        for unit in units(text)
        for figure, metric in figures
    )


def relevant_chunk_ids(question: dict, chunks: list[dict]) -> list[str]:
    qid, category = question["id"], question["category"]
    sections = set(question["expected_sections"])
    if category == "numeric_results":
        hits = [c for c in chunks if has_figure(c["text"], FIGURES[qid])]
    elif category in ("legal_proceedings", "market_risk"):
        first, last = SECTION_PAGES.get(qid, (0, 10**6))
        hits = [c for c in chunks if c["section"] in sections and first <= c["page"] <= last]
    elif category == "controls":
        hits = [c for c in chunks if c["section"] in sections and CONCLUSION.search(c["text"])]
    else:
        topics = re.compile(TOPICS[qid], re.IGNORECASE)
        needed = 1 if qid in ONE_TOPIC else 2
        hits = [
            c
            for c in chunks
            if c["section"] in sections
            and len({m.group(0).lower() for m in topics.finditer(c["text"])}) >= needed
        ]
    return [c["chunk_id"] for c in hits]


def read_chunks(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fill relevant_chunk_ids from the ETL chunks")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--chunks", type=Path, default=config.data_dir() / "chunks")
    args = parser.parse_args(argv)

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    empty = []
    for question in questions:
        doc_id = f"{question['ticker']}_{question['fiscal_year']}_10K"
        ids = relevant_chunk_ids(question, read_chunks(args.chunks / f"{doc_id}.jsonl"))
        question["relevant_chunk_ids"] = ids
        print(f"{question['id']}  {doc_id:<16} {question['category']:<22} {len(ids):>3} relevant")
        if not ids:
            empty.append(question["id"])
    if empty:
        print(f"No evidence found for {empty}: check the figures or topics before writing")
        return 1
    args.questions.write_text(json.dumps(questions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {sum(len(q['relevant_chunk_ids']) for q in questions)} chunk ids to {args.questions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
