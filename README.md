# FilingLens AI

**Financial Advisor Chatbot for NASDAQ companies**

Un asistente que responde preguntas sobre empresas del NASDAQ leyendo sus reportes anuales, y que siempre dice de dónde sacó cada dato.

Proyecto final del programa **ML Developer Career** de [Anyone AI](https://anyoneai.com). Equipo 3.

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

**Elasticsearch y Haystack no son alternativas, son piezas distintas.** Elasticsearch ejecuta la búsqueda: recorre el índice y devuelve lo que coincide. Haystack la dirige: parte los documentos, genera los embeddings, pregunta dos veces, fusiona las listas y arma el prompt.

---

## El dataset

Reportes anuales y 10-K de empresas listadas en el NASDAQ, alojados en S3 por Anyone AI.

| Medida | Valor |
| --- | --- |
| Documentos | 9.855 PDF |
| Peso total | 29,8 GB |
| Peso promedio | 3,1 MB por documento |
| Empresas | 2.429 |
| Rango de años | 2015 a 2022, con densidad entre 2018 y 2021 |

### Dos hallazgos que definieron el alcance

**La metadata está en el nombre del archivo.** La ruta `nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf` contiene empresa, bolsa, ticker y año. No hay que abrir el PDF para extraerlos.

**El dataset se corta en 2021.** No hay documentos de 2023 en adelante, y 2022 tiene apenas 160 archivos contra los 2.237 de 2019. Por eso el alcance del proyecto son **2019, 2020 y 2021**.

Si alguien pregunta por un año fuera de rango, el bot lo dice en vez de callar o inventar.

---

## Alcance

**Dentro:** 25 empresas reconocibles del NASDAQ, tres años fiscales, solo 10-K en inglés, búsqueda híbrida, respuesta con cita de empresa, año, sección y página, interfaz de chat, API, todo contenerizado, y un set de evaluación para medir la calidad.

**Fuera:** las 2.429 empresas del dataset completo, búsqueda de noticias en internet, autenticación, gráficos, tablas financieras como datos estructurados, comparaciones entre varias empresas en una sola respuesta, cálculos aritméticos, y cualquier forma de recomendación de inversión.

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
python eda/explore_s3.py          # explora el bucket, no descarga nada
python eda/download_sample.py     # descarga la muestra de trabajo
python eda/characterize.py        # caracteriza los documentos
```

El script de descarga es **determinista**: baja siempre exactamente los mismos archivos, sin importar quién lo corra. Así todo el equipo trabaja con la misma muestra y los resultados son comparables.

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
| 4 | Sistema de pregunta, búsqueda y respuesta | `search/` y `generation/` |
| 5 | API | `api/` |
| 6 | Interfaz tipo ChatGPT | `ui/` |
| 7 | Presentar resultados y demo | todos |
| 8 | Todo contenerizado con Docker | raíz |

---

## Equipo

Seis integrantes, cada uno responsable de un carril. Ver el documento de acuerdos y reparto para el detalle de quién lleva qué.

## Licencia

Proyecto académico. El dataset es propiedad de Anyone AI y los documentos originales son públicos, presentados ante la SEC por las empresas emisoras.
