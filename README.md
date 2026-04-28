# City Event Crawler v2

Instagram-only deep discovery for European cities, with Claude-powered curation. Output isn't a flat list of events — it's an evening guide: a top pick, a 3–5 step itinerary, hidden gems, and a skip list, all curated for a 20–30 year old audience.

## Pipeline

```
DISCOVER  →  TRIAGE  →  SCRAPE  →  EXTRACT  →  SCORE  →  CURATE
   │           │          │          │          │         │
SerpAPI     Claude     Apify       Claude     Claude    Claude
+ seeds     filters    pulls IG    parses     rates     writes
+ city      bad-fit    posts/      captions   each      EveningGuide
hashtags    accounts   reels       → Events   event     (top pick,
                                              on 4      itinerary,
                                              axes      gems, skips)
```

| Stage    | What it does                                                              |
|----------|---------------------------------------------------------------------------|
| DISCOVER | Find candidate Instagram accounts via SerpAPI Google + curated city seeds |
| TRIAGE   | Claude prunes the list to ~25 accounts that fit the city + requested vibes |
| SCRAPE   | Apify `apify~instagram-scraper` pulls recent posts from each account       |
| EXTRACT  | Claude parses captions into structured `Event` records (title, date, venue, vibes) |
| SCORE    | Claude rates each event on quality, popularity, fun factor, demographic fit |
| CURATE   | Claude writes the `EveningGuide` and tags each event with a `curation_tier` |

Each event ends up labelled `top_pick`, `hidden_gem`, `standard`, or `skip`, and the response includes a single `EveningGuide` payload with a Claude-written summary, a numbered itinerary, hidden gems, and skip list.

## API

```
POST /api/search
GET  /api/cities
GET  /api/vibes
GET  /api/health
```

`POST /api/search` body:

```json
{
  "city": "Berlin",
  "date": "2026-04-26",
  "vibes": ["nightlife", "underground"],
  "radius_km": 15,
  "max_results": 60
}
```

Response highlights:

```json
{
  "events": [
    {
      "id": "instagram_…",
      "title": "Sub:Stance × Cellbrain",
      "date": "2026-04-26T23:00:00",
      "venue_name": "Sisyphos Berlin",
      "account_handle": "sisyphos_berlin",
      "scrape_source": "profile",
      "vibes": ["nightlife", "underground"],
      "curation_tier": "top_pick",
      "score_breakdown": {
        "quality": 0.82, "popularity": 0.74,
        "fun_factor": 0.91, "demographic_fit": 0.88
      },
      "suggested_itinerary_position": 0,
      "image_url": "…",
      "source_url": "https://www.instagram.com/p/…/"
    }
  ],
  "curated_guide": {
    "summary_text": "Tonight Berlin leans deep…",
    "demographic_note": "Best for techno-curious 20-somethings who don't sleep early",
    "top_pick_id": "instagram_…",
    "itinerary_ids": ["…", "…", "…"],
    "hidden_gem_ids": ["…", "…"],
    "skip_ids": []
  },
  "accounts_discovered": 73,
  "accounts_triaged": 24,
  "posts_scraped": 168,
  "events_extracted": 31,
  "search_duration_seconds": 47.21
}
```

## Setup

Three API keys are required:

| Key                      | Where to get it                | Notes                                          |
|--------------------------|--------------------------------|------------------------------------------------|
| `SERPAPI_KEY`            | https://www.searchapi.io/      | Used for Instagram account discovery           |
| `INSTAGRAM_APIFY_TOKEN`  | https://apify.com/             | Pays for `apify~instagram-scraper` actor runs  |
| `ANTHROPIC_API_KEY`      | https://console.anthropic.com/ | Powers TRIAGE / EXTRACT / SCORE / CURATE       |

```bash
cp .env.example .env
# fill in the three keys
```

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Streamlit (primary UI)

The Streamlit dashboard at `streamlit_app/` is the canonical interface — it
combines the search/curation view with admin tabs (Runs, Cost, Cache).

```bash
python -m venv streamlit_app/.venv
streamlit_app/.venv/bin/pip install -r streamlit_app/requirements.txt
streamlit_app/.venv/bin/streamlit run streamlit_app/app.py
# → http://localhost:8501
```

### React frontend (legacy, optional)

The earlier React UI at `frontend/` is still in the repo but is no longer
the primary interface. It only covers the user-facing search experience —
no Runs / Cost / Cache. Run it if you want a non-admin view:

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

### Docker

```bash
docker-compose up --build
```

## Project structure

```
backend/
  main.py              # FastAPI app + /api/search pipeline
  models.py            # Event, EveningGuide, SearchRequest/Response
  config.py            # 3 API keys + Claude model settings
  instagram/
    discover.py        # SerpAPI + curated city seeds → IG handles
    triage.py          # Claude filters bad-fit accounts
    scraper.py         # Apify pulls posts/reels
  extraction/
    extract.py         # Claude parses captions → Event
    score.py           # Claude rates each event on 4 axes
    curate.py          # Claude composes the EveningGuide
  utils/
    helpers.py         # haversine distance

frontend/
  src/
    App.jsx
    App.css            # includes curation badge / score bar / evening guide styles
    components/
      EveningGuide.jsx # hero panel rendering top pick + itinerary + gems + skips
      EventCard.jsx    # curation badges + score breakdown bars
      FilterPanel.jsx  # vibe chips + curation tier dropdown
      EventList.jsx, MapView.jsx, SearchBar.jsx, StatsBar.jsx
```

## Postgres caching + cost log

Set `DATABASE_URL` in `.env` to a Postgres URI (Neon works out of the box, including the `?sslmode=require&channel_binding=require` suffix). Initialise the schema once:

```bash
backend/.venv/bin/python -c "
import asyncio, asyncpg
from dotenv import dotenv_values
async def main():
    conn = await asyncpg.connect(dotenv_values('.env')['DATABASE_URL'])
    await conn.execute(open('backend/db/init.sql').read())
asyncio.run(main())
"
```

Two tables get created:
- `scrape_cache` — raw Apify items per `(account_handle, content_type)` pair, 24h TTL.
- `cost_log` — one row per `/api/search` run, used for the monthly budget cutoff and the Streamlit dashboard.

The pipeline degrades gracefully if `DATABASE_URL` is unset — caching becomes a no-op and runs aren't logged.

## Streamlit admin dashboard

`streamlit_app/` is an internal dashboard over the same Postgres. Four tabs:

- **Search** — fires `/api/search` against the FastAPI backend (`BACKEND_URL`)
- **Runs** — paginated `cost_log` browser
- **Cost** — month-to-date spend, daily chart, runway, cache hit rate
- **Cache** — browse + purge `scrape_cache`

Local:
```bash
python3 -m venv streamlit_app/.venv
streamlit_app/.venv/bin/pip install -r streamlit_app/requirements.txt
streamlit_app/.venv/bin/streamlit run streamlit_app/app.py
```

Deploy to **Streamlit Community Cloud** (free):
1. Push the repo to GitHub.
2. At [share.streamlit.io](https://share.streamlit.io) → New app → point at `streamlit_app/app.py`.
3. In Streamlit Cloud secrets, add:
   ```toml
   DATABASE_URL = "postgresql://..."
   BACKEND_URL  = "https://your-fastapi-host"   # optional; Search tab requires it
   ```
4. Cost / Runs / Cache tabs work immediately. The Search tab needs a public FastAPI host.

## Apify cost control

Defaults in `backend/config.py` are tuned for the Apify Starter plan ($30/mo):

| Setting                  | Default | Notes                                    |
|--------------------------|---------|------------------------------------------|
| `MAX_ACCOUNTS_PER_SEARCH`| 60      | After TRIAGE                             |
| `MAX_POSTS_PER_ACCOUNT`  | 2       | wider, shallower                         |
| `MAX_STORIES_PER_ACCOUNT`| 5       | most accounts have 0–3 active stories    |
| `SCRAPE_INCLUDE_STORIES` | true    | stories often carry "tonight" announcements |
| `SCRAPE_INCLUDE_HASHTAGS`| false   | extra cost, marginal value               |
| `POSTS_CACHE_TTL_HOURS`  | 24      | per-account                              |
| `STORIES_CACHE_TTL_HOURS`| 24      |                                          |
| `MONTHLY_BUDGET_USD`     | 25.0    | cuts off SCRAPE; cache-only fallback     |
| `APIFY_POSTS_USD_PER_1K` | 2.30    | check actor's pricing page               |
| `APIFY_STORIES_USD_PER_1K`| 2.30   | check stories actor's pricing page       |

At defaults, a fresh search bills ~300 results ≈ $0.69. With 24h cache, repeated city searches in the same day are free.

## Tuning

The demographic targeting (20–30 year olds) lives in the system prompts inside `extraction/score.py` and `extraction/curate.py` — edit those strings to retarget.

## License

Private project.
