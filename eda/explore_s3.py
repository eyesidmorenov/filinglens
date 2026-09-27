"""
Explora el bucket de S3 sin descargar nada.

Objetivo: entender cómo está organizado el dataset antes de decidir
qué muestra bajar y cómo extraer la metadata de cada documento.

Salidas (para que el notebook lea datos medidos, no números copiados):
    data/eda/bucket_inventory.csv   una fila por archivo, metadata parseada de la ruta
    data/eda/bucket_unparsed.csv    rutas que no siguen la convención de nombres

Uso:
    python eda/explore_s3.py
"""

import csv
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BUCKET = "anyoneai-datasets"
PREFIX = "nasdaq_annual_reports/"

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eda"

# nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf
# Variante en 48 archivos: NASDAQ_ICUI_2016_<hash de 32 hex>.pdf
KEY_PATTERN = re.compile(
    r"^nasdaq_annual_reports/"
    r"(?P<company>[^/]+)/"
    r"(?P<exchange>[A-Za-z]+)_(?P<ticker>[^_/]+)_(?P<fiscal_year>\d{4})"
    r"(?:_(?P<suffix>[0-9a-f]{32}))?\.pdf$",
    re.IGNORECASE,
)


def get_client():
    """Cliente de S3. Usa las llaves del .env si existen, si no prueba anonimo."""
    key = os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_REGION", "us-east-1")

    if key and secret:
        print("Conectando con credenciales del .env")
        return boto3.client(
            "s3",
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=region,
        )

    print("Sin credenciales en .env, intentando acceso anonimo")
    return boto3.client("s3", config=Config(signature_version=UNSIGNED), region_name=region)


def listar_todo(client, limite=None):
    """Lista los objetos del prefijo. limite=None trae todos."""
    paginator = client.get_paginator("list_objects_v2")
    objetos = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/"):
                continue
            objetos.append({"key": obj["Key"], "size": obj["Size"]})
            if limite and len(objetos) >= limite:
                return objetos
    return objetos


def parsear(objetos):
    """Separa las rutas que siguen la convención de las que no."""
    filas, sueltas = [], []
    for o in objetos:
        m = KEY_PATTERN.match(o["key"])
        if m:
            filas.append({
                "s3_key": o["key"],
                "company": m["company"],
                "exchange": m["exchange"].upper(),
                "ticker": m["ticker"].upper(),
                "fiscal_year": int(m["fiscal_year"]),
                "size_mb": round(o["size"] / 1024**2, 3),
                "has_hash_suffix": m["suffix"] is not None,
            })
        else:
            sueltas.append({"s3_key": o["key"], "size_mb": round(o["size"] / 1024**2, 3)})
    return filas, sueltas


def guardar(filas, sueltas):
    OUT.mkdir(parents=True, exist_ok=True)

    inv_path = OUT / "bucket_inventory.csv"
    with open(inv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["s3_key", "company", "exchange", "ticker", "fiscal_year", "size_mb", "has_hash_suffix"])
        w.writeheader()
        w.writerows(filas)

    sueltas_path = OUT / "bucket_unparsed.csv"
    with open(sueltas_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["s3_key", "size_mb"])
        w.writeheader()
        w.writerows(sueltas)

    print(f"\nGuardado: {inv_path.relative_to(ROOT)}  ({len(filas):,} filas)")
    print(f"Guardado: {sueltas_path.relative_to(ROOT)}  ({len(sueltas):,} filas)")


def analizar(objetos, filas, sueltas):
    total = len(objetos)
    peso_total = sum(o["size"] for o in objetos)

    print("\n" + "=" * 70)
    print(f"ARCHIVOS: {total:,}")
    print(f"PESO TOTAL: {peso_total / 1024**3:.2f} GB")
    if total:
        print(f"PESO PROMEDIO: {peso_total / total / 1024**2:.2f} MB por archivo")
    print("=" * 70)

    # --- Extensiones ---
    ext = Counter(os.path.splitext(o["key"])[1].lower() or "(sin extension)" for o in objetos)
    print("\nEXTENSIONES")
    for e, n in ext.most_common(10):
        print(f"  {e:<20} {n:>8,}")

    # --- Profundidad de carpetas ---
    prof = Counter(o["key"].count("/") for o in objetos)
    print("\nNIVELES DE CARPETA (incluye el prefijo base)")
    for p, n in sorted(prof.items()):
        print(f"  {p} niveles        {n:>8,}")

    # --- Convención de nombres ---
    print("\nCONVENCION DE NOMBRES")
    print(f"  La siguen       {len(filas):>8,}")
    print(f"  No la siguen    {len(sueltas):>8,}")
    for s in sueltas[:10]:
        print(f"    {s['s3_key']}")
    if len(sueltas) > 10:
        print(f"    ... y {len(sueltas) - 10:,} mas (ver bucket_unparsed.csv)")

    # --- Empresas ---
    empresas = {f["company"] for f in filas}
    print(f"\nEMPRESAS DISTINTAS: {len(empresas):,}")

    # --- Años: uno por archivo, tomado del nombre ---
    anios = Counter(f["fiscal_year"] for f in filas)
    print("\nAÑO FISCAL POR ARCHIVO")
    for a, n in sorted(anios.items()):
        print(f"  {a}   {n:>8,}")
    print(f"  suma  {sum(anios.values()):>8,}")

    # --- Sufijo hash ---
    con_hash = sum(f["has_hash_suffix"] for f in filas)
    print(f"\nCON SUFIJO HASH: {con_hash:,}")

    # --- Duplicados: mismo ticker y año mas de una vez ---
    pares = Counter((f["ticker"], f["fiscal_year"]) for f in filas)
    dups = {k: n for k, n in pares.items() if n > 1}
    print(f"\nDUPLICADOS ticker+año: {len(dups):,}")
    for (t, a), n in list(dups.items())[:10]:
        print(f"  {t} {a}  x{n}")

    # --- Empresas de interes ---
    objetivo = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "FB", "INTC", "GOOGL", "GOOG", "AMD", "NFLX"]
    por_ticker = defaultdict(list)
    for f in filas:
        por_ticker[f["ticker"]].append(f["fiscal_year"])
    print("\nEMPRESAS DE INTERES")
    for t in objetivo:
        if t in por_ticker:
            print(f"  {t:<8} {sorted(por_ticker[t])}")
        else:
            print(f"  {t:<8} no esta en el bucket")


def main():
    client = get_client()
    print(f"Listando s3://{BUCKET}/{PREFIX} ...")
    try:
        objetos = listar_todo(client)
    except Exception as e:
        print(f"\nERROR al listar: {type(e).__name__}: {e}")
        print("\nRevisa que el .env tenga AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY")
        return
    if not objetos:
        print("No se encontro ningun objeto. Revisa el nombre del bucket y el prefijo.")
        return

    filas, sueltas = parsear(objetos)
    analizar(objetos, filas, sueltas)
    guardar(filas, sueltas)
    print("\nListo. Nada se descargo, solo se listo.")


if __name__ == "__main__":
    main()
