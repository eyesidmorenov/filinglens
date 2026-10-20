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

### De la muestra a 25 empresas

| Comando | Qué hace |
| --- | --- |
| `python eda/select_companies.py` | Lee `bucket_inventory.csv` (sin consultar S3) y se queda con 35 empresas conocidas que tienen los años fiscales 2019, 2020 y 2021. Escribe `eda/companies.csv` |
| `python eda/download_sample.py --companies eda/companies.csv` | Descarga esas empresas en lugar de la muestra de 5 |

Saca 35 a propósito: el ETL descarta los reportes que no traen 10-K, y el proyecto se queda con las primeras 25 que pasen.

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
