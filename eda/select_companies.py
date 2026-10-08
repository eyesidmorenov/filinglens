"""
Elige las empresas candidatas para pasar de la muestra a 25 empresas.

Lee el inventario que ya midió explore_s3.py (no consulta S3) y se queda con las
empresas que tienen los tres años del alcance, 2019, 2020 y 2021, priorizando las
más conocidas del NASDAQ. Saca más de 25 a propósito: el ETL descarta las que no
traen 10-K (como pasó con Microsoft), y nos quedamos con las primeras 25 que pasen.

Entrada:  data/eda/bucket_inventory.csv
Salida:   eda/companies.csv   (versionado en Git: la lista es una decisión del proyecto)

Uso:
    python eda/select_companies.py              # 35 candidatas
    python eda/select_companies.py --n 30
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTARIO = ROOT / "data" / "eda" / "bucket_inventory.csv"
SALIDA = Path(__file__).parent / "companies.csv"

ANIOS = {2019, 2020, 2021}

# Empresas conocidas del NASDAQ, en orden de prioridad (las del Nasdaq-100 de esos años).
# Solo empresas de EE. UU.: las extranjeras (ASML, JD, Baidu...) presentan 20-F, no 10-K.
CONOCIDAS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "FB", "META", "TSLA", "NVDA", "INTC",
    "PYPL", "ADBE", "NFLX", "CSCO", "CMCSA", "PEP", "COST", "AVGO", "QCOM", "TXN",
    "AMD", "AMGN", "SBUX", "INTU", "TMUS", "ISRG", "BKNG", "GILD", "MDLZ", "MU",
    "AMAT", "ADP", "CHTR", "LRCX", "FISV", "CSX", "ATVI", "ADSK", "ILMN", "VRTX",
    "REGN", "MRNA", "ZM", "EBAY", "KLAC", "MAR", "IDXX", "CTSH", "EA", "ROST",
    "ORLY", "LULU", "PAYX", "MNST", "DXCM", "ALGN", "WBA", "EXC", "XEL", "CTAS",
    "BIIB", "SNPS", "CDNS", "MRVL", "FAST", "VRSK", "PCAR", "ANSS", "CPRT", "DLTR",
    "SWKS", "INCY", "MCHP", "KHC", "AEP", "DOCU", "OKTA", "CRWD", "WDAY", "TEAM",
    "ZS", "DDOG", "FTNT", "PTON", "SIRI", "CERN", "MELI",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=35, help="cuántas candidatas sacar")
    args = ap.parse_args()

    if not INVENTARIO.exists():
        raise SystemExit(f"No encuentro {INVENTARIO.relative_to(ROOT)}. Corre primero: python eda/explore_s3.py")

    anios = defaultdict(set)
    tickers = defaultdict(set)
    peso = defaultdict(float)
    with open(INVENTARIO, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            anio = int(fila["fiscal_year"])
            if anio in ANIOS:
                anios[fila["company"]].add(anio)
                tickers[fila["company"]].add(fila["ticker"].upper())
                peso[fila["company"]] += float(fila["size_mb"])

    completas = [c for c in anios if ANIOS <= anios[c]]
    prioridad = {t: i for i, t in enumerate(CONOCIDAS)}

    def rango(empresa):
        return min((prioridad[t] for t in tickers[empresa] if t in prioridad), default=None)

    conocidas = sorted((c for c in completas if rango(c) is not None), key=lambda c: (rango(c), c))
    elegidas = conocidas[: args.n]

    with open(SALIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["rank", "company", "ticker", "size_mb_2019_2021"])
        for i, c in enumerate(elegidas, 1):
            ticker = next(t for t in sorted(tickers[c]) if t in prioridad)
            w.writerow([i, c, ticker, round(peso[c], 1)])

    print(f"Empresas en el inventario:              {len(anios):,}")
    print(f"Con los tres años 2019, 2020 y 2021:    {len(completas):,}")
    print(f"De esas, conocidas del NASDAQ:          {len(conocidas):,}")
    print(f"Candidatas guardadas en {SALIDA.relative_to(ROOT)}: {len(elegidas)}")
    for i, c in enumerate(elegidas, 1):
        print(f"  {i:>2}. {c:<36} {', '.join(sorted(tickers[c]))}")
    if len(elegidas) < args.n:
        print(f"\nOjo: solo hay {len(elegidas)} candidatas conocidas con los tres años.")


if __name__ == "__main__":
    main()
