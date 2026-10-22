# Evaluación de las respuestas con RAGAS

> 🇬🇧 English version: [README.md](README.md)

La evaluación de la búsqueda (`search/`) mide si se encuentra el chunk correcto: en el 95% de las
150 preguntas etiquetadas aparece en el top 5. Esta carpeta mide el paso siguiente: **lo que Claude
escribe con esos chunks**.

RAGAS también puede escribir las preguntas de prueba, a partir de nuestros propios chunks, cada una
con una respuesta de referencia (pedido de Mariano, mentoría del 21/10). Con respuesta de referencia
hay cinco métricas, las de su `eval_ragas.py`; las preguntas etiquetadas no la tienen, así que se
miden con las tres que no la necesitan.

| Métrica | Qué pregunta responde | Necesita respuesta de referencia | Rango |
| --- | --- | --- | --- |
| `context_recall` (cobertura del contexto) | ¿Los chunks que recibió Claude tienen todo lo que necesita la respuesta de referencia? | Sí | 0 a 1 |
| `context_precision` (precisión del contexto) | ¿Los chunks que recibió Claude sirven para la respuesta, los mejores primero? | No (la usa si existe) | 0 a 1 |
| `faithfulness` (fidelidad) | ¿Cada afirmación de la respuesta está respaldada por los chunks que recibió Claude? | No | 0 a 1 |
| `answer_relevancy` (relevancia) | ¿La respuesta contesta la pregunta que se hizo? | No | 0 a 1 |
| `factual_correctness` (corrección) | ¿La respuesta coincide con la respuesta de referencia? | Sí | 0 a 1 |

El juez es Claude (`claude-sonnet-5`, salvo que `--model` o `RAGAS_MODEL` digan otro) y los
embeddings de `answer_relevancy` son los de BGE que ya usa el índice, así que no hace falta llave de
OpenAI. RAGAS siempre manda una `temperature` y `claude-sonnet-5` la rechaza (error 400), así que el
juez la saca del pedido (`common.ragas_models`).

`claude-haiku-5-5` alcanza para RAGAS (preguntas y juez) y cuesta 20 veces menos, como el script de
Mariano, que usa un modelo chico (`gpt-4o-mini`). Las respuestas que se evalúan siguen siendo las
del chat, escritas por `claude-sonnet-5`.

## Tres pasos

0. **Preguntas** (`ragas_eval/testset.py`, servicio `ragas`). RAGAS lee 8 chunks de cada uno de 10
   informes de empresas distintas (Items 1, 1A, 3, 7, 7A, 8 y 9A), arma su grafo de conocimiento con
   Claude (resúmenes, temas, entidades) y escribe preguntas de un solo chunk, cada una con su
   respuesta de referencia. Como cada pregunta sale de un chunk, sabemos su empresa y su año: el
   chat filtra por los dos y no compara informes. Las preguntas se escriben como las escribe
   nuestro usuario (un analista de inversiones, con buena redacción, medianas o largas); por defecto
   RAGAS también mezcla preguntas con errores. Solo se usan las empresas del set de evaluación (las
   50 del paquete v5).
1. **Respuestas** (`ragas_eval/answers.py`, servicio `ragas-answers`). Corre en la imagen de la API,
   con su mismo pipeline: detección de empresa y año, búsqueda híbrida (o la foto de Yahoo) y
   tenk-answer, igual que el chat. Guarda el texto completo de los chunks que vio Claude; la
   respuesta de la API solo trae fragmentos cortos. Las preguntas de RAGAS no siempre nombran la
   empresa o el año, así que entran con los del informe del que salieron.
2. **Puntajes** (`ragas_eval/score.py`, servicio `ragas`). Corre en su propia imagen, como el paso 0:
   RAGAS necesita otras versiones de las librerías de Anthropic y LangChain que tenk-answer, así que
   los pasos que usan RAGAS nunca comparten entorno con la API.

Solo se califican las respuestas con estado `answered`. Un rechazo (`out_of_scope`) o un "no lo sé"
(`insufficient_context`) no tiene afirmaciones que revisar; el resumen cuenta cada estado aparte.

## Cómo correrlo

Desde la raíz del repositorio, con Elasticsearch arriba, el índice cargado y `ANTHROPIC_API_KEY`
en el `.env` de la raíz. Cada persona lo corre con la llave de su propio `.env` (nunca se sube), y
las llamadas se cobran en esa llave.

```bash
docker compose --profile ragas build ragas-answers ragas
```

**Con las preguntas que escribe RAGAS** (20 por defecto):

```bash
docker compose --profile ragas run --rm ragas python -m ragas_eval.testset --model claude-haiku-5-5        # paso 0
docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --testset <carpeta>      # paso 1
docker compose --profile ragas run --rm ragas python -m ragas_eval.score --model claude-haiku-5-5          # paso 2
```

El paso 0 muestra la carpeta de la corrida (por ejemplo `2026-10-21_2300`). Lee su `testset.csv`
antes del paso 1: una pregunta que no tiene sentido es más barato sacarla ahí (borrando su línea en
`testset.jsonl`). Primero una prueba corta: `--n 3 --filings 1`.

**Con las preguntas etiquetadas:**

```bash
docker compose --profile ragas run --rm ragas-answers      # paso 1: 30 preguntas
docker compose --profile ragas run --rm ragas              # paso 2: califica la última corrida
```

Primero una prueba corta y después el set completo:

```bash
docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --limit 5
docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --limit 0   # las 150
```

Las 30 preguntas son siempre las mismas: una por categoría, por turnos, en el orden del archivo.
Así están todas las categorías y dos corridas se pueden comparar.

## Resultados

`data/eval/ragas/<fecha y hora>/` (nunca se sube al repositorio):

| Archivo | Contenido |
| --- | --- |
| `testset.jsonl` | Paso 0, una línea por pregunta: pregunta, respuesta y chunks de referencia, empresa, año, sección y chunk de origen |
| `testset.csv` | Las mismas preguntas y respuestas de referencia, para revisar a mano |
| `testset_info.json` | Informes y chunks usados, modelo y tokens de la generación |
| `answers.jsonl` | Una línea por pregunta: pregunta, respuesta, estado, ids y texto de los chunks, tokens, latencia (y la respuesta de referencia, si hay) |
| `scores.csv` | Una fila por respuesta calificada, con sus puntajes (cinco, o tres sin respuesta de referencia) |
| `summary.json` | Promedios, por categoría, conteo de estados, detección de empresa y año, tokens, modelo juez y sus tokens |

En las preguntas de RAGAS, la categoría es la sección del chunk del que salió cada una.

## Costo

El paso 1 cuesta lo mismo que el chat (unos $0,012 por pregunta). Los pasos 0 y 2 llaman a Claude
muchas veces: el paso 0 por chunk (resúmenes, temas, entidades) y por pregunta; el paso 2 por
respuesta (afirmaciones, veredictos, preguntas generadas, una llamada por chunk para la precisión
del contexto).

Medido con 3 preguntas del 10-K 2020 de Apple (21/10): el juez costó $0,34 con `claude-sonnet-5` y
$0,02 con `claude-haiku-5-5`, con puntajes parecidos. Para 20 preguntas, los tres pasos cuestan unos
$2,90 con `claude-sonnet-5` para RAGAS y unos $0,40 con `claude-haiku-5-5`, casi todo por las
respuestas del propio chat. Primero corre 3.

## Tests

```bash
docker compose --profile ragas run --rm ragas python -m pytest -q
```

Sin Elasticsearch, Claude ni RAGAS: el muestreo, la elección de informes y chunks, el rastreo de cada
pregunta de RAGAS hasta su informe, el registro de cada respuesta, los nombres de las métricas, el
resumen y los archivos.
