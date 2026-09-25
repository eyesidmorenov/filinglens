"""
Explora el bucket de S3 sin descargar nada.

Objetivo: entender cómo está organizado el dataset antes de decidir
qué muestra bajar y cómo extraer la metadata de cada documento.

Uso:
    python explore_s3.py
"""

import os
import re
from collections import Counter, defaultdict

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from dotenv import load_dotenv
from pathlib import Path

# load_dotenv()
load_dotenv(Path(__file__).parent / ".env")

BUCKET = "anyoneai-datasets"
PREFIX = "nasdaq_annual_reports/"


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


def analizar(objetos):
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

    # --- Primer nivel despues del prefijo ---
    primer = Counter()
    for o in objetos:
        resto = o["key"][len(PREFIX):]
        primer[resto.split("/")[0] if "/" in resto else "(archivos sueltos)"] += 1
    print(f"\nPRIMER NIVEL ({len(primer):,} distintos)")
    for k, n in primer.most_common(15):
        print(f"  {k:<40} {n:>8,}")
    if len(primer) > 15:
        print(f"  ... y {len(primer) - 15:,} mas")

    # --- Muestra de nombres ---
    print("\nMUESTRA DE RUTAS")
    for o in objetos[:15]:
        print(f"  {o['key']}  ({o['size'] / 1024**2:.1f} MB)")

    # --- Años detectados en los nombres ---
    anios = Counter()
    for o in objetos:
        for a in re.findall(r"(19[89]\d|20[0-3]\d)", o["key"]):
            anios[a] += 1
    if anios:
        print("\nAÑOS QUE APARECEN EN LAS RUTAS")
        for a, n in sorted(anios.items()):
            print(f"  {a}   {n:>8,}")

    # --- Empresas conocidas ---
    objetivo = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "INTC", "GOOGL", "AMD", "NFLX"]
    print("\nEMPRESAS DE INTERES ENCONTRADAS")
    encontradas = defaultdict(list)
    for o in objetos:
        up = o["key"].upper()
        for t in objetivo:
            if re.search(rf"[/_\-]{t}[/_\-.]", up):
                encontradas[t].append(o["key"])
    if encontradas:
        for t in objetivo:
            if t in encontradas:
                print(f"  {t:<8} {len(encontradas[t]):>4} archivos   ej: {encontradas[t][0]}")
    else:
        print("  Ninguna por ticker. Puede que los nombres usen el nombre completo.")

    return {"total": total, "peso_gb": peso_total / 1024**3}


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
    analizar(objetos)
    print("\nListo. Nada se descargo, solo se listo.")


if __name__ == "__main__":
    main()
