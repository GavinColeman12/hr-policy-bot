"""City Event Crawler — admin/ops dashboard."""

from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # local-dev only; harmless on Streamlit Cloud

from streamlit_app import db  # noqa: E402

MONTHLY_BUDGET_DEFAULT = float(os.environ.get("MONTHLY_BUDGET_USD", "25.0"))

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


def main():
    st.title("City Event Crawler — Admin")
    _sidebar_budget()

    search_tab, runs_tab, cost_tab, cache_tab = st.tabs(
        ["Search", "Runs", "Cost", "Cache"]
    )

    with search_tab:
        st.write("(Search tab — implemented in Task 13)")
    with runs_tab:
        st.write("(Runs tab — implemented in Task 14)")
    with cost_tab:
        st.write("(Cost tab — implemented in Task 15)")
    with cache_tab:
        st.write("(Cache tab — implemented in Task 16)")


if __name__ == "__main__":
    main()
