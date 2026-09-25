"""
Caracteriza los documentos descargados. Paso 3 del EDA.

No limpia ni transforma nada. Solo mide y reporta, para que quien haga
la extracción sepa exactamente contra qué está trabajando.

Qué responde:
  1. Cuántas páginas tiene un 10-K de verdad
  2. Si el texto se extrae legible o hay escaneados
  3. Si traen las secciones Item numeradas, y en qué formato
  4. Cuántos caracteres salen, para estimar los fragmentos
  5. Si el nombre del archivo coincide con lo que dice adentro
  6. Si hay duplicados
  7. En qué idioma están
  8. Cuántas tablas tiene cada uno

Uso:
    python characterize.py
    python characterize.py --sample AAPL_2019    # solo uno, con detalle
"""

import argparse
import contextlib
import csv
import io
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:          # versiones anteriores de la librería
    import fitz

RAIZ = Path(__file__).parent.parent
ENTRADA = RAIZ / "data" / "raw"
SALIDA = RAIZ / "data" / "eda"

# Umbral: menos caracteres por página que esto sugiere escaneado o sin texto
MIN_CHARS_POR_PAGINA = 200

# Las secciones que nos interesan de un 10-K
ITEMS_CLAVE = ["1", "1A", "3", "5", "7", "7A", "8"]

# Palabras comunes en inglés, para una detección de idioma sencilla
MARCADORES_EN = {"the", "and", "of", "to", "in", "for", "that", "with", "our", "we"}


def patron_item(num):
    """
    Construye el patrón para encontrar 'Item 1A' en sus distintas formas.

    Los 10-K escriben la misma sección de maneras diferentes:
        Item 1A.  |  ITEM 1A  |  Item 1A —  |  Item 1A:
    Por eso el patrón es flexible en el separador que sigue al número.
    """
    return re.compile(rf"\bitem\s+{num}\b[\.\:\s\-—]", re.IGNORECASE)


def detectar_items(texto):
    """Devuelve qué items aparecen y cuántas veces cada uno."""
    hallados = {}
    for num in ITEMS_CLAVE:
        apariciones = patron_item(num).findall(texto)
        if apariciones:
            hallados[f"Item {num}"] = len(apariciones)
    return hallados


def formatos_item(texto):
    """
    Cómo están escritos los items. Sirve para saber si el patrón
    del chunking tiene que ser flexible o puede ser estricto.
    """
    crudos = re.findall(r"\b(item\s+\d+[A-Z]?)\s*([\.\:\-—])", texto, re.IGNORECASE)
    formas = Counter()
    for encabezado, sep in crudos[:200]:
        if encabezado.isupper():
            caja = "MAYUSCULAS"
        elif encabezado.istitle() or encabezado[0].isupper():
            caja = "Capitalizado"
        else:
            caja = "minusculas"
        formas[f"{caja} + '{sep}'"] += 1
    return dict(formas.most_common(5))


def parece_ingles(texto):
    """Detección sencilla: cuántos marcadores del inglés aparecen."""
    palabras = set(re.findall(r"[a-z]+", texto[:50000].lower()))
    return len(MARCADORES_EN & palabras)


def verificar_coherencia(texto, ticker, anio):
    """
    ¿El contenido coincide con el nombre del archivo?
    Un documento mal etiquetado haría que el bot cite la empresa equivocada.
    """
    cabeza = texto[:20000]
    return {
        "ticker_en_texto": bool(re.search(rf"\b{re.escape(ticker)}\b", cabeza, re.IGNORECASE)),
        "anio_en_texto": bool(re.search(rf"\b{anio}\b", cabeza)),
        "dice_10k": bool(re.search(r"\b(form\s+10-?k|annual\s+report)\b", cabeza, re.IGNORECASE)),
    }


def analizar(pdf_path):
    """Abre un PDF y devuelve todas sus métricas."""
    nombre = pdf_path.stem            # AAPL_2019
    ticker, anio = nombre.split("_")

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return {"archivo": nombre, "error": f"{type(e).__name__}: {e}"}

    paginas = doc.page_count
    textos = []
    paginas_vacias = 0
    tablas = 0

    for i, page in enumerate(doc):
        t = page.get_text()
        textos.append(t)
        if len(t.strip()) < MIN_CHARS_POR_PAGINA:
            paginas_vacias += 1
        # el detector de tablas es lento, lo corremos en una muestra
        if i < 40:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    tablas += len(page.find_tables().tables)
            except Exception:
                pass

    completo = "\n".join(textos)
    doc.close()

    n_chars = len(completo)
    n_palabras = len(completo.split())
    items = detectar_items(completo)

    return {
        "archivo": nombre,
        "ticker": ticker,
        "anio": int(anio),
        "peso_mb": round(pdf_path.stat().st_size / 1024**2, 2),
        "paginas": paginas,
        "caracteres": n_chars,
        "palabras": n_palabras,
        "chars_por_pagina": round(n_chars / paginas) if paginas else 0,
        "paginas_sin_texto": paginas_vacias,
        "pct_sin_texto": round(100 * paginas_vacias / paginas, 1) if paginas else 0,
        "tablas_en_40p": tablas,
        "items_encontrados": len(items),
        "items": items,
        "formatos_item": formatos_item(completo),
        "marcadores_ingles": parece_ingles(completo),
        "coherencia": verificar_coherencia(completo, ticker, anio),
        "hash": hashlib.md5(completo.encode("utf-8", "replace")).hexdigest()[:12],
        "fragmentos_est": round(n_chars / 1000),   # a 1000 chars por fragmento
    }


def imprimir_detalle(r):
    print(f"\n{'=' * 70}\n{r['archivo']}\n{'=' * 70}")
    if "error" in r:
        print(f"  ERROR: {r['error']}")
        return
    print(f"  Páginas:            {r['paginas']}")
    print(f"  Peso:               {r['peso_mb']} MB")
    print(f"  Caracteres:         {r['caracteres']:,}")
    print(f"  Palabras:           {r['palabras']:,}")
    print(f"  Chars por página:   {r['chars_por_pagina']:,}")
    print(f"  Páginas sin texto:  {r['paginas_sin_texto']} ({r['pct_sin_texto']}%)")
    print(f"  Tablas (40 pág):    {r['tablas_en_40p']}")
    print(f"  Fragmentos est.:    ~{r['fragmentos_est']}")
    print(f"  Marcadores inglés:  {r['marcadores_ingles']}/10")
    print(f"\n  Items encontrados ({r['items_encontrados']}/{len(ITEMS_CLAVE)}):")
    for k, v in r["items"].items():
        print(f"     {k:<10} aparece {v} veces")
    faltan = [f"Item {n}" for n in ITEMS_CLAVE if f"Item {n}" not in r["items"]]
    if faltan:
        print(f"     faltan: {', '.join(faltan)}")
    print(f"\n  Formatos de item:")
    for k, v in r["formatos_item"].items():
        print(f"     {k:<26} {v} veces")
    c = r["coherencia"]
    print(f"\n  Coherencia nombre vs contenido:")
    print(f"     ticker en el texto:  {'si' if c['ticker_en_texto'] else 'NO'}")
    print(f"     año en el texto:     {'si' if c['anio_en_texto'] else 'NO'}")
    print(f"     dice 10-K:           {'si' if c['dice_10k'] else 'NO'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="analizar un solo documento con detalle")
    args = ap.parse_args()

    pdfs = sorted(ENTRADA.glob("*.pdf"))
    if not pdfs:
        print(f"No hay PDF en {ENTRADA}. Corre primero download_sample.py")
        sys.exit(1)

    if args.sample:
        objetivo = ENTRADA / f"{args.sample}.pdf"
        if not objetivo.exists():
            print(f"No existe {objetivo}")
            sys.exit(1)
        imprimir_detalle(analizar(objetivo))
        return

    print(f"Analizando {len(pdfs)} documentos...\n")
    resultados = []
    for p in pdfs:
        print(f"  {p.stem}...", end=" ", flush=True)
        r = analizar(p)
        resultados.append(r)
        print("error" if "error" in r else f"{r['paginas']} pág, {r['caracteres']:,} chars")

    ok = [r for r in resultados if "error" not in r]
    if not ok:
        print("\nNingún documento se pudo abrir.")
        sys.exit(1)

    # ---------- Resumen ----------
    print(f"\n{'=' * 70}\nRESUMEN\n{'=' * 70}")

    pags = [r["paginas"] for r in ok]
    chars = [r["caracteres"] for r in ok]
    print(f"Documentos analizados: {len(ok)}")
    print(f"\nPáginas:     min {min(pags)}   max {max(pags)}   promedio {sum(pags)//len(pags)}")
    print(f"Caracteres:  min {min(chars):,}   max {max(chars):,}   promedio {sum(chars)//len(chars):,}")
    print(f"Total de fragmentos estimados: ~{sum(r['fragmentos_est'] for r in ok):,}")

    # ---------- Escaneados ----------
    print(f"\n{'-' * 70}\nTEXTO EXTRAÍBLE")
    sospechosos = [r for r in ok if r["pct_sin_texto"] > 20]
    if sospechosos:
        print("  Documentos con más del 20% de páginas sin texto:")
        for r in sospechosos:
            print(f"     {r['archivo']:<14} {r['pct_sin_texto']}% sin texto")
        print("  Revisar si son escaneados. Un escaneado no sirve sin OCR.")
    else:
        print("  Todos los documentos tienen texto extraíble. No hay escaneados.")

    # ---------- Items ----------
    print(f"\n{'-' * 70}\nSECCIONES ITEM")
    completos = [r for r in ok if r["items_encontrados"] == len(ITEMS_CLAVE)]
    print(f"  Con los {len(ITEMS_CLAVE)} items clave: {len(completos)}/{len(ok)}")
    for r in ok:
        faltan = [n for n in ITEMS_CLAVE if f"Item {n}" not in r["items"]]
        estado = "completo" if not faltan else f"faltan {faltan}"
        print(f"     {r['archivo']:<14} {r['items_encontrados']}/{len(ITEMS_CLAVE)}  {estado}")

    formatos = Counter()
    for r in ok:
        formatos.update(r["formatos_item"])
    print(f"\n  Formatos de escritura encontrados en todo el corpus:")
    for k, v in formatos.most_common(8):
        print(f"     {k:<26} {v}")
    if len(formatos) > 1:
        print("  Hay más de un formato. El patrón del chunking debe ser flexible.")

    # ---------- Coherencia ----------
    print(f"\n{'-' * 70}\nCOHERENCIA NOMBRE VS CONTENIDO")
    problemas = [r for r in ok if not all(r["coherencia"].values())]
    if problemas:
        for r in problemas:
            c = r["coherencia"]
            fallos = [k for k, v in c.items() if not v]
            print(f"     {r['archivo']:<14} no se confirmó: {', '.join(fallos)}")
        print("  Revisar a mano. Un documento mal etiquetado cita la empresa equivocada.")
    else:
        print("  Todos coinciden: ticker, año y tipo de documento confirmados en el texto.")

    # ---------- Idioma ----------
    print(f"\n{'-' * 70}\nIDIOMA")
    no_ingles = [r for r in ok if r["marcadores_ingles"] < 8]
    if no_ingles:
        for r in no_ingles:
            print(f"     {r['archivo']:<14} solo {r['marcadores_ingles']}/10 marcadores de inglés")
    else:
        print("  Todos en inglés.")

    # ---------- Duplicados ----------
    print(f"\n{'-' * 70}\nDUPLICADOS")
    hashes = Counter(r["hash"] for r in ok)
    repetidos = {h: c for h, c in hashes.items() if c > 1}
    if repetidos:
        for h in repetidos:
            iguales = [r["archivo"] for r in ok if r["hash"] == h]
            print(f"     contenido idéntico: {', '.join(iguales)}")
    else:
        print(f"  No hay duplicados. Los {len(ok)} documentos son distintos.")

    # ---------- Tablas ----------
    print(f"\n{'-' * 70}\nTABLAS")
    total_t = sum(r["tablas_en_40p"] for r in ok)
    print(f"  Detectadas en las primeras 40 páginas de cada documento: {total_t}")
    print(f"  Promedio por documento: {total_t // len(ok)}")
    print("  Los estados financieros vienen en tablas. Ver el spike del entregable 2.")

    # ---------- Guardar ----------
    SALIDA.mkdir(parents=True, exist_ok=True)

    with open(SALIDA / "caracterizacion.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)

    columnas = ["archivo", "ticker", "anio", "peso_mb", "paginas", "caracteres",
                "palabras", "chars_por_pagina", "paginas_sin_texto", "pct_sin_texto",
                "tablas_en_40p", "items_encontrados", "fragmentos_est", "hash"]
    with open(SALIDA / "caracterizacion.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        w.writerows(ok)

    print(f"\n{'=' * 70}")
    print(f"Guardado en {SALIDA}")
    print("  caracterizacion.csv    tabla para revisar y graficar")
    print("  caracterizacion.json   detalle completo, incluidos los items")


if __name__ == "__main__":
    main()
