"""Sync Postgres helpers for the Streamlit dashboard."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import psycopg
import streamlit as st


def _resolve_database_url() -> str:
    """Try env var first, then Streamlit secrets, fall back to empty."""
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    try:
        return st.secrets["DATABASE_URL"]
    except (FileNotFoundError, KeyError, AttributeError):
        return ""


@st.cache_resource
def _conn() -> psycopg.Connection:
    url = _resolve_database_url()
    if not url:
        st.error("DATABASE_URL is not configured. Set it in .env or Streamlit secrets.")
        st.stop()
    return psycopg.connect(url, autocommit=True)


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with _conn().cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in (cur.description or [])]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def execute(sql: str, params: tuple = ()) -> None:
    with _conn().cursor() as cur:
        cur.execute(sql, params)


def fetchval(sql: str, params: tuple = ()) -> Any:
    with _conn().cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row[0] if row else None
