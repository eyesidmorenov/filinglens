# Evaluación de las respuestas con RAGAS

> 🇬🇧 English version: [README.md](README.md)

La evaluación de la búsqueda (`search/`) mide si se encuentra el chunk correcto: en el 95% de las
150 preguntas etiquetadas aparece en el top 5. Esta carpeta mide el paso siguiente: **lo que Claude
escribe con esos chunks**.

| Métrica | Qué pregunta responde | Rango |
| --- | --- | --- |
| `faithfulness` (fidelidad) | ¿Cada afirmación de la respuesta está respaldada por los chunks que recibió Claude? | 0 a 1 |
| `answer_relevancy` (relevancia) | ¿La respuesta contesta la pregunta que se hizo? | 0 a 1 |
| `context_precision` (precisión del contexto) | ¿Los chunks que recibió Claude sirven para la respuesta, los mejores primero? | 0 a 1 |

El juez es Claude (`claude-sonnet-5`, el mismo modelo que responde) y los embeddings de
`answer_relevancy` son los de BGE que ya usa el índice, así que no hace falta llave de OpenAI.

## Dos pasos

1. **Respuestas** (`ragas_eval/answers.py`, servicio `ragas-answers`). Corre en la imagen de la API,
   con su mismo pipeline: detección de empresa y año, búsqueda híbrida (o la foto de Yahoo) y
   tenk-answer, igual que el chat. Guarda el texto completo de los chunks que vio Claude; la
   respuesta de la API solo trae fragmentos cortos.
2. **Puntajes** (`ragas_eval/score.py`, servicio `ragas`). Corre en su propia imagen: RAGAS necesita
   otras versiones de las librerías de Anthropic y LangChain que tenk-answer, así que los dos pasos
   nunca comparten entorno.

Solo se califican las respuestas con estado `answered`. Un rechazo (`out_of_scope`) o un "no lo sé"
(`insufficient_context`) no tiene afirmaciones que revisar; el resumen cuenta cada estado aparte.

## Cómo correrlo

Desde la raíz del repositorio, con Elasticsearch arriba, el índice cargado y `ANTHROPIC_API_KEY`
en el `.env` de la raíz:

```bash
docker compose --profile ragas build ragas-answers ragas
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
| `answers.jsonl` | Una línea por pregunta: pregunta, respuesta, estado, ids y texto de los chunks, tokens, latencia |
| `scores.csv` | Una fila por respuesta calificada, con sus tres puntajes |
| `summary.json` | Promedios, por categoría, conteo de estados, detección de empresa y año, tokens, modelo juez |

## Costo

El paso 1 cuesta lo mismo que el chat (unos $0,012 por pregunta). El paso 2 llama a Claude varias
veces por respuesta (afirmaciones, veredictos, preguntas generadas, una llamada por chunk para la
precisión del contexto), así que 30 preguntas cuestan unos pocos dólares. Primero corre 5.

## Tests

```bash
docker compose --profile ragas run --rm ragas python -m pytest -q
```

Sin Elasticsearch, Claude ni RAGAS: el muestreo, el registro de cada respuesta, el resumen y los archivos.
