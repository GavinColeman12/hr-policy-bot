-- backend/db/init.sql
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS scrape_cache (
    account_handle  TEXT NOT NULL,
    content_type    TEXT NOT NULL CHECK (content_type IN ('posts', 'stories')),
    items           JSONB NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    results_billed  INTEGER NOT NULL,
    PRIMARY KEY (account_handle, content_type)
);
CREATE INDEX IF NOT EXISTS scrape_cache_expires_idx
    ON scrape_cache (expires_at);

CREATE TABLE IF NOT EXISTS cost_log (
    id                    BIGSERIAL PRIMARY KEY,
    run_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    city                  TEXT NOT NULL,
    search_date           DATE NOT NULL,
    vibes                 TEXT[] NOT NULL DEFAULT '{}',
    accounts_discovered   INTEGER NOT NULL DEFAULT 0,
    accounts_triaged      INTEGER NOT NULL DEFAULT 0,
    accounts_cache_hit    INTEGER NOT NULL DEFAULT 0,
    accounts_scraped      INTEGER NOT NULL DEFAULT 0,
    posts_scraped         INTEGER NOT NULL DEFAULT 0,
    stories_scraped       INTEGER NOT NULL DEFAULT 0,
    events_extracted      INTEGER NOT NULL DEFAULT 0,
    apify_results_billed  INTEGER NOT NULL DEFAULT 0,
    apify_cost_usd        NUMERIC(10,4) NOT NULL DEFAULT 0,
    claude_input_tokens   INTEGER NOT NULL DEFAULT 0,
    claude_output_tokens  INTEGER NOT NULL DEFAULT 0,
    duration_seconds      NUMERIC(10,3) NOT NULL DEFAULT 0,
    budget_blocked        BOOLEAN NOT NULL DEFAULT FALSE,
    errors                JSONB NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS cost_log_run_at_idx ON cost_log (run_at DESC);
CREATE INDEX IF NOT EXISTS cost_log_city_idx   ON cost_log (city);
