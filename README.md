# Austral Headlines

Resumen de *breaking news* en inglés para **Austral Research (@AustralRes_En)**. Corre 5 veces por día hábil (08:00, 10:00, 12:00, 15:00 y 18:00, hora de Montevideo). Busca noticias recién publicadas **solo** en las fuentes permitidas, aplica una ventana horaria estricta y devuelve hasta 15 headlines.

No publica en X ni escribe a terceros. Imprime el resultado, lo guarda en `output/` y, si se configura, te lo envía **a vos** por Telegram o email.

## Cómo funciona

```
ventana (window.py)
  → RSS + news-sitemaps (fetchers/rss.py, fetchers/sitemap.py)        timestamp del feed
  → búsqueda web de Claude con allowed_domains (fetchers/websearch.py) solo descubre URLs
      → verificación de cada página (fetchers/page_meta.py)            timestamp de metadatos
  → filtros por código: dominio permitido, banco en Investing, ventana, dedup
  → Claude (summarizer.py): materialidad, traducción al inglés, ranking → JSON validado
  → render.py arma cada línea con URL, hora y tag tomados de los metadatos, nunca del modelo
  → consola + output/YYYY-MM-DD_HHMM.md (+ Telegram/email opcional)
```

Garantías:

- **Dominios:** un URL se acepta solo si su host es exactamente un dominio permitido o un subdominio suyo (`www1.folha.uol.com.br` sí, `g1.globo.com` no, `notmining.com` no).
- **Timestamps:** se toman del `pubDate` del feed, de `news:publication_date` del sitemap o de los metadatos de la página (`article:published_time`, JSON-LD `datePublished`, `<time datetime>`). Si no hay timestamp con zona horaria, la nota se descarta. Las fuentes LatAm declaran `naive_tz` para fechas sin offset.
- **Sin relleno:** si no queda nada, la salida es exactamente `No material news.`.
- **Si fallan todas las fuentes** (red caída, API key inválida), la corrida termina con código 3 y no informa "No material news.", que sería falso. Si falla solo una fuente, se registra un warning y la corrida sigue.
- **Paywalls:** solo se lee el HTML público (título, resumen y metadatos). No se usan cookies ni se intenta saltear paywalls o CAPTCHAs.

## Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completar ANTHROPIC_API_KEY
```

Requiere Python 3.11+.

## Variables de entorno (`.env`)

| Variable | Uso |
|---|---|
| `ANTHROPIC_API_KEY` | **Obligatoria.** |
| `ANTHROPIC_MODEL` | Modelo (default `claude-sonnet-5-5`). |
| `ANTHROPIC_FALLBACKS` | `default` (default): si el modelo rechaza una solicitud, el API la reintenta en otro modelo. `off` lo desactiva. |
| `DELIVERY` | `telegram`, `email` o `telegram,email`. Vacío = solo consola y archivo. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Tu bot y **tu** chat (un único chat). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` | Email a **una** sola dirección (la tuya). |
| `OUTPUT_DIR` | Carpeta de salida (default `./output`). |

## Uso

```bash
python main.py --now --dry-run      # correr ya, con la corrida más cercana, sin enviar nada
python main.py                      # modo programado: corre solo si es día hábil y está a ≤60 min de una corrida
python main.py --slot 08:00 --now   # forzar la ventana de las 08:00 (5 h)
python main.py --now --no-search    # solo RSS/sitemaps (más barato)
python main.py --now --no-llm       # debug: lista los candidatos verificados, sin Claude
python main.py --at 2026-11-20T13:05:00+00:00 --now --dry-run   # simular otra hora
pytest -q
```

Ventanas: 08:00 → 5 h · 10:00 → 2 h · 12:00 → 2 h · 15:00 → 3 h · 18:00 → 3 h. La ventana termina en el momento real de la corrida y empieza N horas antes del horario programado: si GitHub arranca tarde, no quedan huecos entre corridas. Todo se configura en `config.yaml` (`runs`).

Formato de cada línea:

```
**FCX** – Cuts 2027 copper guidance after Grasberg outage – 12:40 UTC – RTRS – [Freeport cuts guidance](https://www.reuters.com/...)
```

## Cómo correrlo (GitHub Actions, manual)

1. En el repo: *Actions → Austral headlines → Run workflow*.
2. Elegir **hours** (cuántas horas hacia atrás: 2, 3, 5, 8, 12 o 24) y si usar **web_search**.
   - Con búsqueda web: ~US$0,80 por corrida.
   - Sin búsqueda web (solo RSS): ~US$0,05 por corrida.
3. Al terminar (~1–2 min), los headlines aparecen en la página del run (*Summary*) y quedan como artefacto descargable durante 90 días.

No se envía nada a ningún lado. Requiere el secreto `ANTHROPIC_API_KEY` en *Settings → Secrets and variables → Actions*.

Desde la terminal, el equivalente es `python main.py --hours 3 --dry-run` (agregar `--no-search` para solo RSS).

**Volver a programarlo:** el workflow trae comentado el bloque `schedule` (lunes a viernes 08, 10, 12, 15 y 18 h de Montevideo, en UTC); basta con descomentarlo. Para un servidor propio hay un ejemplo de cron en `deploy/crontab.example`.

## Agregar o quitar tickers, temas y fuentes

Todo está en `config.yaml`:

- **Ticker:** agregar `- {ticker: XYZ, name: "Company Name"}` en `watchlist`. Para quitarlo, borrar la línea. El prompt y las búsquedas se arman a partir de esta lista.
- **Tema:** agregar un ítem en `topics` con `name` y `query`. Cada tema es una búsqueda web por corrida.
- **Fuente:** agregar un bloque en `sources`:
  ```yaml
  - tag: NEWTAG            # el tag que aparece en la salida
    name: New Outlet
    domains: [newoutlet.com]
    priority: 12           # menor = fuente más primaria al deduplicar
    language: es           # en | es | pt
    naive_tz: America/Argentina/Buenos_Aires   # solo si publica fechas sin offset
    feeds: [https://newoutlet.com/feed/]
  ```
  Cada dominio de `sources` pasa automáticamente al `allowed_domains` de la búsqueda y al filtro por código. Al quitar el bloque, la fuente queda excluida de todo.
- **Investing.com:** solo pasan las notas que mencionan algún banco de `investing_banks`. El modelo además tiene que identificar el banco, que aparece como `INVESTING/GOLDMAN SACHS`.

## Feeds por fuente

| Tag | Endpoint |
|---|---|
| RTRS | news-sitemap `reuters.com/arc/outboundfeeds/news-sitemap/` (Reuters no tiene RSS público) + búsqueda web |
| BBG | `feeds.bloomberg.com/{markets,economics,politics}/news.rss` |
| WSJ | `feeds.a.dj.com/rss/RSSMarketsMain.xml`, `RSSWorldNews.xml`, `WSJcomUSBusiness.xml` |
| FT | `ft.com/{markets,commodities,world}?format=rss` |
| CNBC | `search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=…` (top, economy, finance, energy) |
| CNN | `rss.cnn.com/rss/money_latest.rss` |
| FOXBIZ | `moxie.foxbusiness.com/google-publisher/{latest,markets,economy}.xml` |
| AXIOS | `api.axios.com/feed/` |
| SEMAFOR | `semafor.com/rss.xml` |
| ZH | `feeds.feedburner.com/zerohedge/feed` (se usa `origLink` → zerohedge.com) |
| TE | `tradingeconomics.com/rss/news.aspx` |
| MINING | `mining.com/feed/` |
| OILPRICE | `oilprice.com/rss/main` |
| INVESTING | `investing.com/rss/news_{11,95,25}.rss` |
| VALOR | `valor.globo.com/rss/valor` |
| FOLHA | `feeds.folha.uol.com.br/{mercado,mundo}/rss091.xml` |
| INVESTOR | `theinvestor.com.br/feed/` |
| INFOBAE | `infobae.com/arc/outboundfeeds/rss/category/economia/` |
| AMBITO | `ambito.com/rss/pages/{economia,finanzas,negocios}.xml` |
| ECONOJOURNAL | `econojournal.com.ar/feed/` |
| SHALE24 | `shale24.com.ar/feed/` |
| LMNEUQUEN | `lmneuquen.com/rss/ultimas-noticias.xml` |
| AP | sin RSS público → solo búsqueda web |
| MARKETWATCH | `feeds.content.dowjones.io/public/rss/mw_{topstories,realtimeheadlines,marketpulse}` |
| BBGLINEA | `bloomberglinea.com` y `bloomberglinea.com.br` `/arc/outboundfeeds/rss/` |
| KITCO | sin RSS verificado → solo búsqueda web |
| NORTHERNMINER | `northernminer.com/feed/` |
| MININGWEEKLY | sin RSS verificado → solo búsqueda web |
| RIGZONE | `rigzone.com/news/rss/rigzone_latest.aspx` |
| CRONISTA | `cronista.com/arc/outboundfeeds/rss/` |
| LANACION | `lanacion.com.ar/arc/outboundfeeds/rss/category/economia/` |
| CLARIN | `clarin.com/rss/economia/` |
| RIONEGRO | `rionegro.com.ar/feed/` |
| INFOMONEY | `infomoney.com.br/feed/` |
| BRAZILJOURNAL | `braziljournal.com/feed/` |
| ESTADAO | `estadao.com.br/arc/outboundfeeds/feeds/rss/sections/economia/` |

Los medios cambian o cierran sus feeds sin aviso. Si un feed falla, aparece como `WARNING feed TAG …` en el log, la búsqueda web sigue cubriendo esa fuente y alcanza con corregir el URL en `config.yaml`.

## Costo

Cada corrida hace unas 7 búsquedas web (5 temas + 2 grupos de tickers, hasta 5 búsquedas cada una) y una llamada de clasificación. Para abaratar se puede usar `--no-search` en algunas corridas o bajar `search.max_uses_per_query`.
