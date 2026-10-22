# FilingLens AI

**Financial Advisor Chatbot for NASDAQ companies**

Un asistente que responde preguntas sobre empresas del NASDAQ leyendo sus reportes anuales 10-K (años fiscales 2019 a 2021) y, para los años siguientes, sus cifras anuales de Yahoo Finance, y que siempre dice de dónde sacó cada dato.

Proyecto final del programa **ML Developer Career** de [Anyone AI](https://anyoneai.com). Equipo 3.

[English](README.md) · [Español](README.es.md)

---

## El problema

Una empresa que cotiza en bolsa publica cada año un informe llamado **10-K**: entre cien y trescientas páginas donde declara su negocio, sus riesgos, su estrategia y sus estados financieros. Es el documento más confiable que existe sobre una empresa, y también uno de los más difíciles de leer.

Quien quiera comparar tres empresas tiene que abrir seiscientas páginas de PDF y buscar a mano.

**FilingLens lee eso y responde en segundos.**

## La regla del producto

> Toda respuesta viene con su fuente: empresa, año fiscal, sección y página.

En finanzas una cifra sin respaldo no sirve, y un dato inventado es peor que un "no sé". Esta regla define el prompt, define la interfaz y define cómo medimos si el sistema funciona.

**No es un asesor de inversiones.** No recomienda comprar ni vender. Reporta lo que las empresas declaran en sus documentos oficiales, nada más.

---

## Arquitectura

El sistema tiene dos momentos que corren por separado.

**Indexación, una sola vez.** Los documentos bajan de S3, se les extrae el texto, se limpian, se parten en fragmentos por sección, se les calcula un vector y se guardan en el índice.

```
S3 → PyMuPDF → limpieza → chunking → embeddings → Elasticsearch
```

**Consulta, en cada pregunta.** La pregunta entra por la interfaz, se detecta de qué empresa y año habla, se busca en el índice por palabras y por significado a la vez, se fusionan las dos listas y un modelo redacta la respuesta con sus citas.

```
Chainlit → FastAPI → Haystack (BM25 + vectores → RRF) → Claude → respuesta con fuentes
```

## Stack

| Pieza | Herramienta | Por qué |
| --- | --- | --- |
| Índice | Elasticsearch | Guarda texto y vectores en un solo servicio, gratis, corre en un contenedor |
| Orquestación | Haystack | Framework especialista en documentos, trae la fusión RRF hecha |
| Embeddings | BGE local | Sin llave, sin cuota, todos tenemos exactamente lo mismo |
| Generación | Claude (Anthropic) | Acceso ya disponible, sin riesgo de quedarnos sin créditos |
| API | FastAPI | |
| Interfaz | Chainlit | Python puro, sin JavaScript |
| Contenedores | Docker Compose | Entregable obligatorio |

**Elasticsearch y Haystack no son alternativas, son piezas distintas.** Elasticsearch *ejecuta* la búsqueda: recorre el índice y devuelve lo que coincide. Haystack la *dirige*: parte los documentos, genera los embeddings, pregunta dos veces, fusiona las listas y arma el prompt.

| Pregunta | Elasticsearch | Haystack |
| --- | --- | --- |
| ¿Quién parte los PDF en fragmentos? | No | Sí |
| ¿Quién genera los embeddings? | No | Sí |
| ¿Quién fusiona las dos búsquedas con RRF? | No | Sí |
| ¿Quién le pasa el contexto a Claude? | No | Sí |
| ¿Quién guarda los fragmentos y los devuelve? | Sí | No |

---

## El dataset

Reportes anuales y 10-K de empresas listadas en el NASDAQ, alojados en S3 por Anyone AI.

| Medida | Valor |
| --- | --- |
| Documentos | 9.855 PDF |
| Peso total | 29,8 GB |
| Peso promedio | 3,1 MB por documento |
| Empresas | 2.428 |
| Rango de años | 2003 a 2022, con casi el 80% entre 2018 y 2021 |

### Hallazgos que definieron el alcance

**La metadata está en el nombre del archivo.** La ruta `nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf` contiene empresa, bolsa, ticker y año. No hay que abrir el PDF para extraerlos. La convención se cumple en 9.852 de 9.855 archivos; 45 de ellos traen un sufijo hash de 32 caracteres, y la única excepción es Fox Corporation.

**La llave es el ticker, no la carpeta de la empresa.** 11 tickers aparecen dos veces para el mismo año, por errores de digitación en el nombre de la carpeta, cambios de nombre de la empresa o el mismo archivo subido con y sin hash. Los documentos se identifican por `ticker` + `fiscal_year` y se conserva un solo archivo por par.

**El dataset se corta en 2021.** No hay documentos de 2023 en adelante, y 2022 tiene apenas 160 archivos contra los 2.236 de 2019. Por eso el alcance de los 10-K son **2019, 2020 y 2021**; los años siguientes salen de las cifras anuales de Yahoo Finance.

**Hay dos tipos de documento, no uno.** Unos archivos son el formulario 10-K de la SEC, con secciones Item numeradas. Otros son el Annual Report para accionistas, que no tiene esa estructura. En la muestra de trabajo, el 79% son 10-K.

Si alguien pregunta por un año que no cubren ni los 10-K ni Yahoo Finance, el bot dice qué años puede responder en vez de callar o inventar.

---

## Alcance

**Dentro:** 50 empresas del NASDAQ, solo 10-K en inglés de tres años fiscales (2019 a 2021), cifras anuales de Yahoo Finance para los años siguientes (fotos guardadas, nunca consultas en vivo), búsqueda híbrida, respuesta con cita de empresa, año, sección y página (o la fecha de descarga de Yahoo Finance), interfaz de chat, API, todo contenerizado, y un set de evaluación para medir la calidad.

**Fuera:** las 2.428 empresas del dataset completo, búsqueda de noticias en internet, autenticación, gráficos, tablas financieras como datos estructurados, comparaciones entre varias empresas en una sola respuesta, cálculos aritméticos, y cualquier forma de recomendación de inversión.

### Qué tipo de preguntas responde

| Categoría | Ejemplo |
| --- | --- |
| Caso natural | ¿Cuáles son los principales factores de riesgo que identifica NVIDIA? |
| Con trabajo | ¿Cuáles fueron los ingresos de Apple en el año fiscal 2021? |
| Fuera de alcance | Compara NVIDIA con AMD en márgenes |

Las de la tercera fila se rechazan con elegancia. **Un bot que conoce sus límites impresiona más que uno que improvisa.**

---

## Estructura del repositorio

```
filinglens/
├── eda/            Exploración y análisis del dataset
├── etl/            Extracción de texto y chunking
├── index/          Elasticsearch, embeddings, carga
├── search/         Pipeline de recuperación y evaluación
├── search-index/   Estado, conteos y filtros del índice (solo lectura)
├── yahoo-finance/  Cobertura y fotos de Yahoo Finance (año fiscal 2022 en adelante; las lee la API)
├── answer-eval/    Evaluación RAGAS de las respuestas (preguntas escritas por RAGAS, cinco métricas)
├── generation/     Prompt y conexión con Claude
├── api/            FastAPI
├── ui/             Chainlit
└── data/           Documentos y resultados intermedios (no se sube)
```

Cada carpeta corresponde a un entregable y tiene un dueño. Se crean a medida que cada carril arranca.

---

## Cómo empezar

```bash
git clone https://github.com/eyesidmorenov/filinglens.git
cd filinglens
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r eda/requirements.txt
```

### Credenciales

```bash
cp eda/.env.example eda/.env
```

Abre `eda/.env` y pon las llaves de AWS que vienen en el brief del curso.

> **Las llaves nunca entran al repositorio.** Ni en el código, ni en un notebook, ni en el historial de commits. El `.gitignore` ya excluye el `.env`. Verifícalo antes del primer commit con `git check-ignore -v eda/.env`.

### Correr el EDA

```bash
python eda/explore_s3.py          # explora el bucket, no descarga nada, guarda el inventario
python eda/download_sample.py     # descarga la muestra de trabajo
python eda/characterize.py        # caracteriza los documentos
```

Después abre `eda/eda_filinglens.ipynb` y ejecuta todas las celdas. Los scripts miden y guardan en `data/eda/`; el notebook solo lee esos resultados, así que ninguna cifra está escrita a mano.

**Con Docker**, sin instalar nada más que Docker. Con el `eda/.env` ya creado, desde la raíz del proyecto:

```bash
docker compose --profile eda run --rm eda python eda/explore_s3.py   # igual para los otros dos scripts
docker compose --profile eda up eda                                  # notebook en http://localhost:8888
```

Los resultados quedan en tu carpeta `data/` y los cambios al notebook se guardan en `eda/`. El `.env` nunca entra a la imagen.

El script de descarga es **determinista**: baja siempre exactamente los mismos archivos, sin importar quién lo corra. Así todo el equipo trabaja con la misma muestra y los resultados son comparables.

### Levantar la app

Los datos nunca entran al repositorio (ni PDFs, ni chunks, ni embeddings, ni cachés). Se comparten como zips en Google Drive, abiertos a cualquiera con el enlace, y cada uno se descomprime en la raíz del repositorio (`data/...`):

| Paquete | Contenido | Tamaño | Para qué hace falta |
| --- | --- | --- | --- |
| [Chunks + embeddings, v5](https://drive.google.com/file/d/12WEIkrlJs1WZzmq1v5UCtFk5Z8RtmRZN/view?usp=sharing) | `data/chunks/` y `data/embeddings/`: 50 empresas, 150 informes (años fiscales 2019 a 2021), 50.785 chunks con sus vectores BGE | 165 MB | Cargar el índice (obligatorio) |
| [Fotos de Yahoo Finance](https://drive.google.com/file/d/1bac_pUpky9kiOvYQg-QBy0EDT4fku4Fz/view?usp=sharing) | `data/yahoo/`: cifras anuales desde el año fiscal 2022 de las 50 empresas | 33 KB | Respuestas de 2022 en adelante |
| [PDFs de los 10-K](https://drive.google.com/file/d/1auT4HDBQU9Z4S85be526bLjghp6Ui8Pm/view?usp=sharing) | `data/raw/`: los 150 PDFs, renombrados `TICKER_AÑO.pdf` | 589 MB | Solo para volver a correr el ETL |

Desde la raíz del repositorio, con Docker abierto:

1. Crea un archivo `.env` en la raíz con tu propia llave de Claude: `ANTHROPIC_API_KEY=...`. Nunca se sube, y cada llamada se cobra en esa llave (unos $0,012 por pregunta).
2. Descomprime en la raíz el paquete de chunks + embeddings y las fotos de Yahoo Finance.
3. Carga el índice. Todos los vectores vienen del paquete, así que no se recalcula nada (unos 10 minutos):
   ```bash
   docker compose up -d elasticsearch
   docker compose --profile index run --rm index
   ```
   Termina con `Index 'filinglens-chunks' now holds 50785 chunks`.
4. Levanta la API y el chat:
   ```bash
   docker compose up -d --build
   ```
   El chat queda en http://localhost:8001 (documentación de la API en http://localhost:8000/docs). La primera respuesta tarda unos 40 segundos mientras cargan los modelos.

### Regenerar los datos desde cero

Cada paquete de arriba sale de scripts de este repositorio:

1. **Elegir las empresas** (`eda/`). La regla: empresas del NASDAQ con los tres años fiscales del alcance (2019, 2020 y 2021) en el bucket del curso.
   - Las primeras 50 salen del Nasdaq-100 de 2019 a 2021, primero las más conocidas (`eda/select_companies.py` → `eda/companies.csv`, `eda/companies_batch2.csv`).
   - Las 50 siguientes (para la demo con 100) son las de mayor valor de mercado hoy, que cotizan en el NASDAQ y tienen sede en Estados Unidos (`eda/select_by_market_cap.py` → `eda/companies_batch3.csv`).
   - Cada lista tiene más candidatas de las necesarias a propósito: una empresa queda solo si el ETL acepta sus tres informes (un formulario 10-K, legible y de la empresa correcta; ver `etl/README.md`).
2. **Conseguir los PDFs.** Descomprime el paquete de [PDFs de los 10-K](https://drive.google.com/file/d/1auT4HDBQU9Z4S85be526bLjghp6Ui8Pm/view?usp=sharing), o bájalos del bucket con `eda/download_sample.py --companies <lista>` (llaves de AWS en `eda/.env`, ver [Credenciales](#credenciales)). Las listas de candidatas también tienen las empresas que quedaron afuera, así que el zip es el conjunto exacto.
3. **Correr el ETL** (texto, secciones y chunks): `docker compose --profile etl run --rm etl` → `data/chunks/`.
4. **Calcular los embeddings.** En la CPU de una notebook tarda horas (unos 1,5 chunks por segundo); en una GPU gratis de Google Colab, unos 20 minutos. La guía paso a paso de Colab está en [`index/README.md`](index/README.md). Después se carga el índice como en el paso 3 de arriba.
5. **Bajar las fotos de Yahoo Finance** (unos 2 minutos, con internet): `docker compose --profile yahoo run --rm yahoo` → `data/yahoo/`. Ver [`yahoo-finance/README.md`](yahoo-finance/README.md).

---

## Contratos de datos

Cada pieza del sistema entrega a la siguiente en un formato fijo. Eso permite que los seis carriles avancen en paralelo sin esperarse: quien necesita algo que otro está construyendo trabaja contra datos falsos con la forma correcta hasta que lleguen los reales.

**Documento**, entre descarga y extracción:

```json
{
  "doc_id": "AAPL_2019_10K",
  "company": "apple-inc",
  "ticker": "AAPL",
  "fiscal_year": 2019,
  "exchange": "NASDAQ",
  "s3_key": "nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf",
  "local_path": "data/raw/AAPL_2019.pdf",
  "n_pages": 96
}
```

**Fragmento**, entre chunking e indexación:

```json
{
  "chunk_id": "AAPL_2019_10K_p42_c3",
  "doc_id": "AAPL_2019_10K",
  "text": "...",
  "section": "Item 7",
  "page": 42,
  "company": "apple-inc",
  "ticker": "AAPL",
  "fiscal_year": 2019
}
```

**Respuesta de la API**, entre backend y frontend:

```json
{
  "answer": "...",
  "sources": [
    { "company": "apple-inc", "fiscal_year": 2019, "section": "Item 7", "page": 42, "excerpt": "..." }
  ],
  "latency_ms": 1840
}
```

Cambiar un contrato se anuncia en el equipo antes de hacerlo, porque del otro lado hay alguien construyendo contra esa forma.

---

## Cómo trabajamos

- **Todos contra `main`.** Los carriles no se tocan, así que los conflictos son mínimos
- **Cada quien en su carpeta**
- **Nada de datos al repositorio.** Los PDF se obtienen corriendo el script de descarga
- **`git pull` antes de empezar** evita la mayoría de los enredos
- **Commits con contexto:** `tipo(carril): qué hiciste`

### Configura tu identidad

Dentro de la carpeta del proyecto, para que tus commits aparezcan a tu nombre:

```bash
git config user.name "Tu Nombre"
git config user.email "tucorreo@ejemplo.com"
```

Sin `--global`, así solo aplica a este repositorio. El historial de commits es la evidencia de quién aportó qué.

---

## Entregables

| # | Entregable | Carpeta |
| --- | --- | --- |
| 1 | Análisis exploratorio del dataset | `eda/` |
| 2 | Scripts de preprocesamiento | `etl/` |
| 3 | Scripts de almacenamiento en la base | `index/` |
| 4 | Sistema de pregunta, búsqueda y respuesta | `search/` y `tenk-answer/` |
| 5 | API | `api/` |
| 6 | Interfaz tipo ChatGPT | `ui/` |
| 7 | Presentar resultados y demo | todos |
| 8 | Todo contenerizado con Docker | raíz |

---

## Equipo

Seis integrantes, cada uno responsable de un carril. Ver el documento de acuerdos y reparto para el detalle de quién lleva qué.

## Licencia

Proyecto académico. El dataset es propiedad de Anyone AI y los documentos originales son públicos, presentados ante la SEC por las empresas emisoras.
