# Cobertura de Yahoo Finance

> 🇬🇧 English version: [README.md](README.md)

**Investigación, todavía no es parte del chatbot.** Los 10-K del dataset del curso llegan
hasta el año fiscal 2021. Esta carpeta mide qué podría agregar Yahoo Finance después de esa
fecha para cada una de nuestras 25 empresas, para que el equipo decida con datos si lo usamos
y cómo.

## La idea

| Pregunta sobre | Fuente | Cita |
| --- | --- | --- |
| Años fiscales 2019 a 2021 | 10-K (índice de Elasticsearch) | Empresa, año fiscal, sección, página |
| Año fiscal 2022 en adelante | Yahoo Finance (propuesta) | "Yahoo Finance, consultado el <fecha>" |

Las reglas no cambian: siempre citar, nunca recomendar una inversión y decir "no lo sé" si no
hay datos. Por eso esta prueba nunca lee recomendaciones de analistas ni precios objetivo.

## Qué hace

Para cada empresa de [`tickers.csv`](tickers.csv) lee, con la librería `yfinance`:

- el **estado de resultados** anual: Total Revenue, Gross Profit, Operating Income, Net Income
- el **balance general** anual: Total Assets, Total Debt, Stockholders Equity
- el **flujo de caja** anual: Operating Cash Flow, Free Cash Flow

y escribe en `data/` (nunca se sube al repositorio):

| Archivo | Contenido |
| --- | --- |
| `data/yahoo/coverage.csv` | Una fila por empresa: estado, años fiscales encontrados, años después de 2021, cifras que faltan |
| `data/yahoo/snapshots/<TICKER>.json` | Las cifras clave por año fiscal, con la fuente y la fecha de consulta |

Los snapshots permiten hacer la demo sin llamar a Yahoo en vivo. Cada uno guarda también la
moneda de las cifras (`currency`, tomada del `financialCurrency` de Yahoo): los montos vienen sin
formato, así que los ingresos de Apple `416161000000` son 416.200 millones de dólares.

**Año fiscal.** El año fiscal de una cifra es el año calendario en que termina su período, la
misma regla de los nombres de los 10-K: el año fiscal 2023 de NVIDIA termina en enero de 2023.
Yahoo corre la fecha de cierre al fin de mes (Apple muestra 2025-09-30 por el 27 de septiembre),
así que las fechas de `fiscal_year_end` son aproximadas; el año no.

## Cómo correrlo

Desde la raíz del repositorio:

```bash
docker compose --profile yahoo build yahoo
docker compose --profile yahoo run --rm yahoo                                  # las 25 empresas, ~1 minuto
docker compose --profile yahoo run --rm yahoo python -m src.coverage --limit 3  # prueba rápida
docker compose --profile yahoo run --rm yahoo pytest -q                         # tests, sin internet
```

Necesita internet. Si Yahoo no devuelve nada para ninguna empresa, termina con una
advertencia: `yfinance` convierte una consulta bloqueada o sin conexión en tablas vacías, no
en un error.

## Casos conocidos

| Ticker en el 10-K | Ticker en Yahoo | Por qué |
| --- | --- | --- |
| FB | META | El ticker cambió de FB a META en 2022 |
| ATVI | ATVI | Microsoft la compró en 2023: probablemente sin datos recientes (`no_data`) |

## Límites a tener en cuenta

- `yfinance` **no es una API oficial de Yahoo**: puede fallar o ser bloqueada sin aviso. Para
  la demo, usar los snapshots guardados, no una consulta en vivo.
- Yahoo suele mostrar **unos cuatro** años fiscales de estados anuales. La tabla de cobertura
  dice exactamente cuáles tiene cada empresa.
- Los nombres de Yahoo **no siempre son los del 10-K**: Apple reporta "net sales" y Yahoo
  muestra "Total Revenue". Cada respuesta debe decir de qué fuente sale la cifra.
- No hay página para citar: la cita pasa a ser fuente + fecha de consulta.

## Decisiones para el equipo (después de la primera corrida)

1. ¿La cobertura es suficiente para las 25 empresas?
2. ¿Qué cifras usamos: solo el estado de resultados, o los tres estados?
3. ¿Cómo elige el chatbot la fuente: por el año fiscal de la pregunta?
4. ¿Consulta en vivo o snapshots guardados para la demo?
