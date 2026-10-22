# Entregable 1: EDA del dataset

*[English](README.md) · Español*

Mide el dataset antes de construir nada encima. No limpia ni transforma: eso es del entregable 2.

## Instalación

Desde la raíz del proyecto:

```bash
python3 -m venv .venv
source .venv/bin/activate      # en Windows: .venv\Scripts\activate
pip install -r eda/requirements.txt
cp eda/.env.example eda/.env
```

Abre `eda/.env` y pega las llaves de solo lectura que vienen en el brief.

## Cómo se corre

Los scripts miden y guardan a disco. El notebook solo lee lo que ellos guardaron.

| Orden | Comando | Qué hace | Qué deja |
| --- | --- | --- | --- |
| 1 | `python eda/explore_s3.py` | Lista el bucket completo, no descarga nada. Parsea cada ruta, detecta sufijos hash y duplicados | `data/eda/bucket_inventory.csv`, `data/eda/bucket_unparsed.csv` |
| 2 | `python eda/download_sample.py` | Descarga la muestra de trabajo: 5 empresas, 2019 a 2021. Determinista | PDF en `data/raw/`, `data/raw/inventario.csv` |
| 3 | `python eda/characterize.py` | Abre cada PDF y mide páginas, texto, secciones Item, tablas | `data/eda/caracterizacion.csv`, `data/eda/caracterizacion.json` |
| 4 | Abrir `eda/eda_filinglens.ipynb` y ejecutar todo | Grafica y documenta los hallazgos | |

`download_sample.py --check` verifica qué hay en el bucket sin descargar.

### De la muestra a 100 empresas: tres tandas

Las empresas se agregaron en tres tandas. Cada tanda sigue los mismos dos pasos: el EDA elige
**candidatas con reglas**, a partir del inventario del bucket, y los chequeos del ETL tienen **la
última palabra**, porque solo abriendo cada PDF se sabe si sirve.

**Las reglas**

| Regla | Por qué |
| --- | --- |
| Años fiscales 2019, 2020 y 2021 en el bucket | El alcance del proyecto: el dataset se corta en 2021 |
| Empresa de Estados Unidos listada en NASDAQ | Las extranjeras suelen presentar 20-F, y el ETL solo toma el formulario 10-K |
| Tandas 1 y 2: nombres conocidos del Nasdaq-100, en orden de prioridad | Empresas reconocibles hacen el producto fácil de probar y de explicar |
| Tanda 3: las más grandes por valor de mercado hoy (Yahoo Finance) | La lista del Nasdaq-100 se agotó: de sus nombres con los tres años solo quedaba Atlassian, que presenta 20-F |
| Que no se haya probado en otra tanda ni esté ya en el índice | Cada tanda suma solo empresas nuevas |
| Más candidatas de las necesarias (35 para 25, 70 para 50) | Cerca del 70% pasa los chequeos del ETL |

**Las tandas**

| Tanda | Candidatas | Quedaron | Lista | Estado |
| --- | --- | --- | --- | --- |
| 1 | 35 | 25 | `eda/companies.csv` | En el índice |
| 2 | 35 | 25 | `eda/companies_batch2.csv` | En el índice |
| 3 | 70 | 50 | `eda/companies_batch3.csv` | Elegidas; entran al índice para la demo final (100 empresas) |

Hoy el índice tiene 50 empresas, 150 reportes y 50.785 chunks.

**Por qué quedó afuera una candidata.** En la tanda 3, cada candidata tiene su resultado en la columna `result`:

| Motivo | Empresas |
| --- | --- |
| El ETL descartó al menos un año: texto ilegible, PDF escaneado o sin 10-K | 14 |
| Los estados financieros no están en el texto del 10-K | 4 |
| El archivo de un año trae el 10-K de otro año fiscal (Axon 2019 es el año fiscal 2018; Freedom Holding 2021 es el 2022) | 2 |

En las tandas 1 y 2, 10 candidatas de cada una no están en el índice: no pasaron un chequeo del ETL,
o ya habían pasado 25. Ejemplos documentados: Microsoft (reportes para inversionistas sin 10-K),
AMD 2019 (texto ilegible), CSX 2020 (el archivo trae el 10-K de CSW Industrials) y Fortinet (el
mismo archivo en 2019 y 2020). Cada corrida del ETL deja los documentos descartados y su motivo en
`data/clean/_skipped.csv`.

**Lo que nos enseñaron las tandas.** Cada tanda trajo un formato que las anteriores no tenían:
tablas sin líneas, páginas a dos columnas, estados financieros en páginas F después de las firmas, y
empresas que nombran su año fiscal distinto. Por eso el EDA propone y el ETL decide. Agregar las
empresas en sí no requiere tocar código: la API y las fotos de Yahoo Finance leen la lista de
empresas desde el índice.

| Comando | Qué hace |
| --- | --- |
| `python eda/select_companies.py` | Tandas 1 y 2. Lee `bucket_inventory.csv` (sin consultar S3) y se queda con 35 empresas conocidas que tienen los años fiscales 2019, 2020 y 2021. Escribe `eda/companies.csv` |
| `docker compose --profile yahoo run --rm -v ./eda:/app/eda yahoo python eda/select_by_market_cap.py` | Tanda 3. Entre las empresas del bucket con los tres años, las más grandes por valor de mercado. Escribe `eda/companies_batch3.csv` |
| `python eda/download_sample.py --companies eda/companies.csv` | Descarga los PDF de una tanda en lugar de la muestra de 5 empresas |

Los nombres de los archivos de salida (`inventario.csv`, `caracterizacion.*`) y sus columnas se mantienen así: el ETL y el notebook los leen.

## Lo que encontramos

| Hallazgo | Dato |
| --- | --- |
| La metadata está en el nombre del archivo | 9.852 de 9.855 PDF siguen `BOLSA_TICKER_AÑO.pdf`, 45 con un sufijo hash |
| El dataset se corta en 2021 | Va de 2003 a 2022, casi el 80% entre 2018 y 2021 |
| Hay dos tipos de documento | 10-K con secciones Item y Annual Report sin ellas |
| El ticker es la llave, no el nombre de la carpeta | 11 tickers con documentos duplicados por errores o cambios de nombre |

El detalle y las gráficas están en el notebook.

## Importante

El `.env` está en el `.gitignore`. Las llaves no pueden entrar al repositorio, ni en el código, ni en un notebook, ni en el historial.
