"""
Descarga una muestra determinista de documentos desde S3.

Determinista significa que siempre baja exactamente los mismos archivos,
sin importar quién lo corra ni cuándo. Así todo el equipo trabaja con la
misma muestra y los resultados son comparables.

No vuelve a descargar lo que ya está en disco, así que se puede correr
las veces que haga falta sin gastar transferencia.

Uso:
    python download_sample.py              # muestra base, 5 empresas
    python download_sample.py --check      # solo verifica, no descarga
"""

import argparse
import csv
import os
import re
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BUCKET = "anyoneai-datasets"
PREFIX = "nasdaq_annual_reports/"

# Carpeta de salida, relativa a la raíz del proyecto
DESTINO = Path(__file__).parent.parent / "data" / "raw"
INVENTARIO = DESTINO / "inventario.csv"

# --- La muestra. Fija a propósito. ---
# El alcance del proyecto son estos tres años: el dataset se corta en 2021.
ANIOS = [2019, 2020, 2021]

# carpeta en S3 -> ticker esperado
EMPRESAS = {
    "apple-inc": "AAPL",
    "nvidia-corporation": "NVDA",
    "microsoft-corporation": "MSFT",
    "tesla-inc": "TSLA",
    "intel-corporation": "INTC",
}

# Archivos que hay que ignorar siempre
IGNORAR = {".DS_Store"}


def get_client():
    key = os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    if not key or not secret:
        print("ERROR: faltan credenciales. Revisa que exista eda/.env con las llaves.")
        sys.exit(1)
    return boto3.client(
        "s3",
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


def listar_empresa(client, carpeta):
    """Lista los archivos de una empresa. Devuelve {año: (key, size)}."""
    encontrados = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=f"{PREFIX}{carpeta}/"):
        for obj in page.get("Contents", []):
            nombre = obj["Key"].split("/")[-1]
            if nombre in IGNORAR or not nombre.lower().endswith(".pdf"):
                continue
            # NASDAQ_AAPL_2019.pdf -> 2019
            m = re.search(r"_(\d{4})\.pdf$", nombre, re.IGNORECASE)
            if not m:
                continue
            anio = int(m.group(1))
            if 1990 <= anio <= 2025:
                encontrados[anio] = (obj["Key"], obj["Size"])
    return encontrados


def parsear_metadata(key):
    """Saca empresa, exchange, ticker y año de la ruta. Sin abrir el PDF."""
    partes = key.split("/")
    empresa = partes[-2]
    nombre = partes[-1]
    m = re.match(r"([A-Z]+)_([A-Z0-9.\-]+)_(\d{4})\.pdf$", nombre, re.IGNORECASE)
    if not m:
        return None
    return {
        "empresa": empresa,
        "exchange": m.group(1).upper(),
        "ticker": m.group(2).upper(),
        "anio": int(m.group(3)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="solo verifica cobertura, no descarga nada")
    args = ap.parse_args()

    client = get_client()
    DESTINO.mkdir(parents=True, exist_ok=True)

    print(f"Muestra: {len(EMPRESAS)} empresas x {len(ANIOS)} años = "
          f"{len(EMPRESAS) * len(ANIOS)} documentos esperados")
    print(f"Destino: {DESTINO}\n")

    plan = []      # lo que sí vamos a bajar
    faltantes = [] # lo que no existe en el bucket

    # --- 1. Verificar cobertura antes de bajar nada ---
    print("Verificando cobertura...")
    for carpeta, ticker_esperado in EMPRESAS.items():
        disponibles = listar_empresa(client, carpeta)
        if not disponibles:
            print(f"  {carpeta:<28} NO ENCONTRADA en el bucket")
            faltantes.extend((carpeta, a, "empresa no existe") for a in ANIOS)
            continue

        presentes = [a for a in ANIOS if a in disponibles]
        ausentes = [a for a in ANIOS if a not in disponibles]

        estado = "completa" if not ausentes else f"faltan {ausentes}"
        otros = sorted(set(disponibles) - set(ANIOS))
        extra = f"  (también tiene {otros})" if otros else ""
        print(f"  {carpeta:<28} {len(presentes)}/{len(ANIOS)} {estado}{extra}")

        for anio in presentes:
            key, size = disponibles[anio]
            meta = parsear_metadata(key)
            if not meta:
                print(f"      nombre no parseable: {key}")
                continue
            if meta["ticker"] != ticker_esperado:
                print(f"      ojo: ticker {meta['ticker']} != {ticker_esperado} esperado")
            plan.append({**meta, "key": key, "size": size})
        for anio in ausentes:
            faltantes.append((carpeta, anio, "año no disponible"))

    print(f"\nDisponibles para descargar: {len(plan)}")
    if faltantes:
        print(f"Faltantes: {len(faltantes)}")
        for c, a, motivo in faltantes:
            print(f"  {c} {a}: {motivo}")

    if args.check:
        print("\nModo --check: no se descargó nada.")
        return

    # --- 2. Descargar lo que falte en disco ---
    print("\nDescargando...")
    filas, bajados, saltados = [], 0, 0
    for item in plan:
        local = DESTINO / f"{item['ticker']}_{item['anio']}.pdf"
        if local.exists() and local.stat().st_size == item["size"]:
            saltados += 1
        else:
            client.download_file(BUCKET, item["key"], str(local))
            bajados += 1
            print(f"  {local.name:<20} {item['size'] / 1024**2:6.1f} MB")

        filas.append({
            "doc_id": f"{item['ticker']}_{item['anio']}_10K",
            "company": item["empresa"],
            "ticker": item["ticker"],
            "fiscal_year": item["anio"],
            "exchange": item["exchange"],
            "s3_key": item["key"],
            "local_path": f"data/raw/{local.name}",
            "size_mb": round(item["size"] / 1024**2, 2),
        })

    # --- 3. Inventario ---
    filas.sort(key=lambda r: (r["ticker"], r["fiscal_year"]))
    with open(INVENTARIO, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)

    peso = sum(r["size_mb"] for r in filas)
    print(f"\nDescargados ahora: {bajados}   ya estaban: {saltados}")
    print(f"Total en disco: {len(filas)} documentos, {peso:.1f} MB")
    print(f"Inventario: {INVENTARIO}")
    print("\nListo. La extracción de texto puede arrancar desde data/raw/")


if __name__ == "__main__":
    main()
