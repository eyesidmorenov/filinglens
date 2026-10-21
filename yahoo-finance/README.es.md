# Cobertura y fotos de Yahoo Finance

> 🇬🇧 English version: [README.md](README.md)

Los 10-K del dataset del curso llegan hasta el año fiscal 2021. Esta carpeta lee lo que Yahoo
Finance tiene después de esa fecha para las 50 empresas del índice y lo guarda como **fotos**
(*snapshots*): un archivo JSON por empresa, que la API lee cuando una pregunta es sobre el año
fiscal 2022 o posterior.

## La idea (acordada el 20/10/2026)

| Pregunta sobre | Fuente | Cita |
| --- | --- | --- |
| Años fiscales 2019 a 2021 | 10-K (índice de Elasticsearch) | Empresa, año fiscal, sección, página |
| Año fiscal 2022 en adelante | La foto de Yahoo Finance, que llega a Claude como un chunk más | "Yahoo Finance · fetched on <fecha>" (`page: 0`) |
| Un año sin foto | ninguna | "No tengo ese año" |

- **El chat nunca llama a Yahoo en vivo.** Las fotos son la caché: preguntar cien veces por
  Apple 2023 consulta a Yahoo cero veces, y la demo funciona aunque Yahoo falle.
- **Yahoo no entra a Elasticsearch.** Un 10-K tiene cientos de páginas y hay que buscar; una
  foto tiene unas pocas cifras por empresa y año, así que la API abre directo el archivo.
- Las reglas no cambian: siempre citar, nunca recomendar una inversión y decir "no lo sé" si no
  hay datos. Por eso esta prueba nunca lee recomendaciones de analistas ni precios objetivo.

## Qué hace

Para cada empresa **del índice** lee, con la librería `yfinance`:

- el **estado de resultados** anual: Total Revenue, Gross Profit, Operating Income, Net Income
- el **balance general** anual: Total Assets, Total Debt, Stockholders Equity
- el **flujo de caja** anual: Operating Cash Flow, Free Cash Flow

**La lista de empresas escala sola.** Sale de lo que deja el ETL en `data/chunks/`: `_stats.csv`
(una fila por 10-K, con su año fiscal y la fecha en que cerró) y el primer chunk de cada informe
(carpeta de S3 y nombre oficial). Sumar empresas al índice las suma acá, sin editar ningún
archivo. [`overrides.csv`](overrides.csv) guarda solo las excepciones: un ticker distinto en
Yahoo (FB es META) y notas sobre las empresas compradas.

y escribe en `data/` (nunca se sube al repositorio):

| Archivo | Contenido |
| --- | --- |
| `data/yahoo/coverage.csv` | Una fila por empresa: estado, años fiscales encontrados, años después de 2021, cifras que faltan |
| `data/yahoo/snapshots/<TICKER>.json` | Las cifras clave por año fiscal, su moneda (`currency`), la fecha en que cerró cada año, la fuente y la fecha de consulta |

Una empresa sin datos (`no_data`) no tiene foto, así que la API responde "no tengo ese año".

Los montos vienen sin formato, en la moneda de la foto (`currency`, el `financialCurrency` de
Yahoo): los ingresos de Apple `416161000000` son 416.200 millones de dólares.

## Los años fiscales son los del 10-K

Yahoo identifica cada año por la fecha en que cerró, y cada empresa nombra su año fiscal a su
manera. La foto usa el mismo año fiscal que el 10-K de la empresa, así "Dollar Tree 2023"
significa lo mismo en Yahoo y en el índice:

| Regla (`fiscal_year_rule`) | El año fiscal es | Ejemplo |
| --- | --- | --- |
| `end_year` (47 empresas) | el año calendario de la fecha de cierre | NVIDIA: cerró el 31/01/2021 → año fiscal 2021 |
| `most_months` (Cadence, Dollar Tree, Illumina) | el año calendario donde cae la mayor parte del año | Dollar Tree: cerró el 01/02/2020 → año fiscal 2019 |

**La regla de cada empresa se elige con sus propios 10-K**: la regla simple (`end_year`) si da
el año fiscal de todos sus informes; si no, `most_months`. Una empresa cuyos 10-K no encajan
con ninguna queda afuera y se informa, así la API responde "no tengo ese año" en vez de
mostrar cifras de otro año. `--check-fiscal-years` lista las reglas elegidas, sin llamar a
Yahoo: hoy 47 empresas usan `end_year` y 3 usan `most_months`.

Yahoo corre la fecha de cierre al fin de mes (Apple muestra 2025-09-30 por el 27 de septiembre),
así que las fechas de `fiscal_year_end` son aproximadas. El año fiscal no: las dos reglas dan el
mismo año para la fecha real y para el fin de su mes.

## Cómo correrlo

Desde la raíz del repositorio:

```bash
docker compose --profile yahoo build yahoo
docker compose --profile yahoo run --rm yahoo python -m src.coverage --check-fiscal-years  # sin internet
docker compose --profile yahoo run --rm yahoo                                              # las 50 empresas, ~2 minutos
docker compose --profile yahoo run --rm yahoo python -m src.coverage --limit 3              # prueba rápida
docker compose --profile yahoo run --rm yahoo pytest -q                                     # tests, sin internet
```

El chequeo de cobertura necesita internet. Si Yahoo no devuelve nada para ninguna empresa,
termina con una advertencia: `yfinance` convierte una consulta bloqueada o sin conexión en
tablas vacías, no en un error.

## Primera corrida con las 50 empresas (20/10/2026)

- **46 de 50 empresas tienen datos**: cuatro años fiscales cada una, 2022-2025, o 2023-2026 en
  las empresas cuyo año fiscal cierra en la primera mitad del año calendario (NVIDIA, Lam
  Research, Autodesk, KLA, Electronic Arts, Paychex, Cintas, Logitech, NetApp, Okta, Seagate,
  Western Digital).
- **4 no tienen datos**, como se esperaba: fueron compradas y ya no cotizan.

| Ticker en el 10-K | Ticker en Yahoo | Por qué |
| --- | --- | --- |
| FB | META | El ticker cambió de FB a META en 2022 |
| ATVI | ATVI | Microsoft la compró en 2023: `no_data` |
| CERN | CERN | Oracle la compró en 2022: `no_data` |
| SPLK | SPLK | Cisco la compró en 2024: `no_data` |
| ANSS | ANSS | Synopsys la compró en 2025: `no_data` |

## Límites a tener en cuenta

- `yfinance` **no es una API oficial de Yahoo**: puede fallar o ser bloqueada sin aviso. Por
  eso el chat lee las fotos guardadas y nunca llama a Yahoo.
- Yahoo muestra **unos cuatro** años fiscales de estados anuales. La tabla de cobertura dice
  exactamente cuáles tiene cada empresa.
- Las cifras de Yahoo pueden estar **reexpresadas**: después de que Dollar Tree vendió Family
  Dollar (2025), Yahoo muestra sus ingresos pasados sin ese negocio (año fiscal 2022: unos
  US$ 15.400 millones, contra unos US$ 28.000 millones en su 10-K). Una respuesta con datos de
  Yahoo tiene que decir de dónde sale la cifra.
- Los nombres de Yahoo **no siempre son los del 10-K**: Apple reporta "net sales" y Yahoo
  muestra "Total Revenue".
- No hay página para citar: la cita pasa a ser fuente + fecha de consulta.
