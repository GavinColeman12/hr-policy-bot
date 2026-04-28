"""City Event Crawler — admin/ops dashboard."""

from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # local-dev only; harmless on Streamlit Cloud

import db  # noqa: E402  (db.py is in the same directory as this script)

MONTHLY_BUDGET_DEFAULT = float(os.environ.get("MONTHLY_BUDGET_USD", "25.0"))


def _resolve_backend_url() -> str:
    url = os.environ.get("BACKEND_URL", "")
    if url:
        return url
    try:
        return st.secrets["BACKEND_URL"]
    except (FileNotFoundError, KeyError, AttributeError):
        return "http://localhost:8000"


st.set_page_config(
    page_title="City Event Crawler — Admin",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _sidebar_budget():
    """Always-visible spend gauge."""
    spent = db.fetchval(
        """
        SELECT COALESCE(SUM(apify_cost_usd), 0)::float
        FROM cost_log
        WHERE run_at >= date_trunc('month', now() at time zone 'utc')
        """
    ) or 0.0
    budget = MONTHLY_BUDGET_DEFAULT
    pct = min(1.0, spent / budget) if budget else 0.0

    st.sidebar.title("Spend")
    st.sidebar.metric("Month-to-date", f"${spent:.2f}", f"of ${budget:.2f}")
    st.sidebar.progress(pct)
    if pct >= 1.0:
        st.sidebar.error("Budget exceeded — searches now cache-only")
    elif pct >= 0.8:
        st.sidebar.warning(f"{pct*100:.0f}% of budget used")


def _format_when(date_str: str | None) -> str:
    """Vivid time description: 'Tonight 11 PM', 'In 3h', 'Sat 23:00'."""
    if not date_str:
        return ""
    from datetime import datetime, timezone
    try:
        d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return str(date_str)[:16]
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta_hours = (d - now).total_seconds() / 3600.0
    time_str = d.strftime("%I:%M %p").lstrip("0")
    if 0 < delta_hours <= 6 and d.date() == now.date():
        return f"In {int(round(delta_hours))}h · {time_str}"
    if d.date() == now.date():
        return f"Tonight · {time_str}"
    if (d.date() - now.date()).days == 1:
        return f"Tomorrow · {time_str}"
    if 0 <= (d.date() - now.date()).days <= 6:
        return f"{d.strftime('%A')} · {time_str}"
    return d.strftime("%a %b %-d · ") + time_str


def _format_end_time(start_str: str | None, end_str: str | None) -> str | None:
    if not end_str:
        return None
    from datetime import datetime
    try:
        e = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        s = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if start_str else None
    except (ValueError, TypeError):
        return None
    if s and s.date() == e.date():
        return "→ " + e.strftime("%I:%M %p").lstrip("0")
    return "→ " + e.strftime("%a %I:%M %p").lstrip("0")


def _curation_reason(score_breakdown: dict | None) -> str | None:
    if not score_breakdown:
        return None
    items = [(k, v) for k, v in score_breakdown.items() if isinstance(v, (int, float))]
    if not items:
        return None
    top_key, top_val = max(items, key=lambda kv: kv[1])
    if top_val < 0.7:
        return None
    return {
        "quality": "Trustworthy event with solid lineup info",
        "popularity": "One of the biggest things happening",
        "fun_factor": "Going to be a great time",
        "demographic_fit": "Squarely in your scene",
    }.get(top_key)


def _render_event_card(ev: dict) -> None:
    """Render one event with all the context the React card has."""
    tier = ev.get("curation_tier", "standard")
    badge = {
        "top_pick": "🌟 TOP PICK",
        "hidden_gem": "💎 HIDDEN GEM",
        "skip": "✖ SKIP",
    }.get(tier, "")
    is_story = ev.get("scrape_source") == "story"

    with st.container(border=True):
        # Header row
        header_cols = st.columns([3, 1])
        with header_cols[0]:
            badges_md = ""
            if badge:
                badges_md += f":violet-background[**{badge}**] "
            if is_story:
                badges_md += ":orange-background[**⚡ JUST DROPPED**] "
            if badges_md:
                st.markdown(badges_md)
            st.markdown(f"### {ev.get('title', '(untitled)')}")
            handle = ev.get("account_handle")
            venue = ev.get("venue_name") or ""
            meta_bits = []
            if handle:
                meta_bits.append(f"`@{handle}`")
            if venue:
                meta_bits.append(f"📍 {venue}")
            if meta_bits:
                st.markdown(" · ".join(meta_bits))

        with header_cols[1]:
            img = ev.get("image_url")
            if img:
                st.image(img, use_container_width=True)

        # When / end-time
        when_bits = []
        when = _format_when(ev.get("date"))
        if when:
            when_bits.append(f"🕒 **{when}**")
        end_str = _format_end_time(ev.get("date"), ev.get("end_date"))
        if end_str:
            when_bits.append(end_str)
        if when_bits:
            st.markdown(" ".join(when_bits))

        # Blurb
        desc = (ev.get("description") or "").strip()
        if desc:
            blurb = desc[:280] + ("…" if len(desc) > 280 else "")
            st.markdown(f"> {blurb}")

        # Lineup
        lineup = ev.get("lineup") or []
        if lineup:
            shown = " · ".join(lineup[:5])
            extra = f" +{len(lineup) - 5}" if len(lineup) > 5 else ""
            st.markdown(f"🎤 **Lineup:** {shown}{extra}")

        # Inline badges row: distance / price / age / vibes
        chip_bits = []
        if ev.get("distance_km") is not None:
            km = ev["distance_km"]
            chip_bits.append(f"📍 {int(round(km*1000))}m" if km < 1 else f"📍 {km:.1f} km")
        if ev.get("price"):
            chip_bits.append(f"💶 {ev['price']}")
        if ev.get("min_age"):
            chip_bits.append(f"🛡 {ev['min_age']}+")
        for v in ev.get("vibes") or []:
            chip_bits.append(f"`{v}`")
        if chip_bits:
            st.markdown(" · ".join(chip_bits))

        # Crowd note
        crowd = ev.get("crowd_note")
        if crowd:
            st.markdown(f"_{crowd}_")

        # Engagement + scores
        likes = ev.get("likes") or 0
        comments = ev.get("comments") or 0
        if likes or comments:
            st.caption(f"❤ {likes:,} · 💬 {comments:,}")

        sb = ev.get("score_breakdown") or {}
        if sb:
            score_cols = st.columns(4)
            for col, key, label in zip(
                score_cols,
                ["quality", "popularity", "fun_factor", "demographic_fit"],
                ["Quality", "Popularity", "Fun", "Fit"],
            ):
                col.metric(label, f"{float(sb.get(key, 0)):.2f}")

        reason = _curation_reason(sb)
        if reason:
            st.markdown(f":red[**{reason.upper()}**]")

        url = ev.get("source_url")
        if url:
            st.link_button("View on Instagram ↗", url)


def _tab_search():
    backend_url = _resolve_backend_url()
    col1, col2, col3 = st.columns([2, 1, 1])
    city = col1.text_input("City", value="berlin")
    date = col2.date_input("Date").isoformat()
    max_results = col3.number_input("Max results", min_value=10, max_value=100, value=40)
    vibes = st.multiselect(
        "Vibes",
        ["open_air", "club_night", "mingle", "headliner", "play_party", "other"],
        default=["club_night"],
    )
    st.caption(f"Backend: `{backend_url}`")
    if st.button("Run search", type="primary"):
        import httpx
        with st.spinner("Running pipeline (this can take 1–3 minutes)..."):
            try:
                r = httpx.post(
                    f"{backend_url}/api/search",
                    json={"city": city, "date": date, "vibes": vibes, "max_results": int(max_results)},
                    timeout=300,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                st.error(f"Search failed: {exc}")
                data = None
        if data:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Events", data["total_count"])
            c2.metric("Cost", f"${data['apify_cost_usd']:.4f}")
            c3.metric("Posts", data["posts_scraped"])
            c4.metric("Stories", data["stories_scraped"])
            if data.get("budget_blocked"):
                st.warning("Monthly budget hit — results came from cache only.")
            guide = data.get("curated_guide")
            if guide:
                st.subheader("Evening Guide")
                st.caption(guide.get("demographic_note", ""))
                st.write(guide.get("summary_text", ""))
            st.subheader("Events")
            events_by_id = {e["id"]: e for e in data.get("events", []) if e.get("id")}
            ordered_ids: list[str] = []
            if guide:
                for eid in (guide.get("itinerary_ids") or []):
                    if eid in events_by_id and eid not in ordered_ids:
                        ordered_ids.append(eid)
            for e in data.get("events", []):
                eid = e.get("id")
                if eid and eid not in ordered_ids:
                    ordered_ids.append(eid)
            for eid in ordered_ids:
                _render_event_card(events_by_id[eid])


def _tab_runs():
    st.subheader("Recent runs")
    city_filter = st.text_input("Filter by city (optional)", value="")
    limit = st.slider("Show last N", 10, 500, 100)
    if city_filter.strip():
        df = db.query_df(
            """
            SELECT run_at, city, search_date, vibes,
                   accounts_discovered, accounts_triaged, accounts_cache_hit,
                   posts_scraped, stories_scraped, events_extracted,
                   apify_cost_usd, duration_seconds, budget_blocked
            FROM cost_log
            WHERE city ILIKE %s
            ORDER BY run_at DESC
            LIMIT %s
            """,
            (f"%{city_filter.strip()}%", int(limit)),
        )
    else:
        df = db.query_df(
            """
            SELECT run_at, city, search_date, vibes,
                   accounts_discovered, accounts_triaged, accounts_cache_hit,
                   posts_scraped, stories_scraped, events_extracted,
                   apify_cost_usd, duration_seconds, budget_blocked
            FROM cost_log
            ORDER BY run_at DESC
            LIMIT %s
            """,
            (int(limit),),
        )
    if df.empty:
        st.info("No runs yet — fire off a search from the Search tab.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


def _tab_cost():
    st.subheader("This month")
    col1, col2, col3, col4 = st.columns(4)
    spent = db.fetchval(
        "SELECT COALESCE(SUM(apify_cost_usd),0)::float FROM cost_log "
        "WHERE run_at >= date_trunc('month', now() at time zone 'utc')"
    ) or 0.0
    runs = db.fetchval(
        "SELECT COUNT(*) FROM cost_log "
        "WHERE run_at >= date_trunc('month', now() at time zone 'utc')"
    ) or 0
    avg = (spent / runs) if runs else 0.0
    runway = ((MONTHLY_BUDGET_DEFAULT - spent) / avg) if avg else None
    col1.metric("Spent", f"${spent:.2f}")
    col2.metric("Budget", f"${MONTHLY_BUDGET_DEFAULT:.2f}")
    col3.metric("Runs", runs)
    col4.metric(
        "Searches left",
        "—" if runway is None else f"~{int(runway)}",
        help="Avg cost-per-run × remaining budget",
    )

    st.subheader("Daily spend (UTC)")
    daily = db.query_df(
        """
        SELECT date_trunc('day', run_at)::date AS day,
               SUM(apify_cost_usd)::float AS cost,
               COUNT(*) AS runs
        FROM cost_log
        WHERE run_at >= date_trunc('month', now() at time zone 'utc')
        GROUP BY 1
        ORDER BY 1
        """
    )
    if daily.empty:
        st.info("No spend yet this month.")
    else:
        st.line_chart(daily.set_index("day")["cost"])

    st.subheader("Cache hit rate")
    cache_stats = db.query_df(
        """
        SELECT
          SUM(accounts_cache_hit)::float / NULLIF(SUM(accounts_triaged), 0) AS hit_rate,
          SUM(accounts_cache_hit) AS hits,
          SUM(accounts_triaged)   AS triaged
        FROM cost_log
        WHERE run_at >= date_trunc('month', now() at time zone 'utc')
        """
    )
    if not cache_stats.empty and cache_stats.iloc[0]["hit_rate"] is not None:
        row = cache_stats.iloc[0]
        st.metric(
            "Hit rate",
            f"{(row['hit_rate'] or 0) * 100:.1f}%",
            f"{int(row['hits'])} of {int(row['triaged'])} accounts",
        )


def _tab_cache():
    st.subheader("Cached accounts")
    df = db.query_df(
        """
        SELECT
          account_handle,
          content_type,
          fetched_at,
          expires_at,
          expires_at > now() AS fresh,
          jsonb_array_length(items) AS item_count,
          results_billed
        FROM scrape_cache
        ORDER BY fetched_at DESC
        LIMIT 500
        """
    )
    if df.empty:
        st.info("Cache is empty.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            handle_to_purge = st.text_input("Purge a single handle")
            if st.button("Purge handle"):
                if handle_to_purge.strip():
                    db.execute(
                        "DELETE FROM scrape_cache WHERE account_handle = %s",
                        (handle_to_purge.strip(),),
                    )
                    st.success(f"Purged {handle_to_purge.strip()}")
                    st.rerun()
        with col_b:
            if st.button("Purge ALL expired rows"):
                db.execute("DELETE FROM scrape_cache WHERE expires_at <= now()")
                st.success("Expired rows purged")
                st.rerun()


def main():
    st.title("City Event Crawler — Admin")
    _sidebar_budget()

    search_tab, runs_tab, cost_tab, cache_tab = st.tabs(
        ["Search", "Runs", "Cost", "Cache"]
    )

    with search_tab:
        _tab_search()
    with runs_tab:
        _tab_runs()
    with cost_tab:
        _tab_cost()
    with cache_tab:
        _tab_cache()


if __name__ == "__main__":
    main()
