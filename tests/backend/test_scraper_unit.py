"""Unit tests for the scraper, with apify-client and DB mocked."""

from __future__ import annotations

from unittest.mock import patch

from backend.instagram import scraper


def _fake_post(owner: str, code: str) -> dict:
    return {"shortCode": code, "ownerUsername": owner, "caption": "fake"}


def _fake_story(owner: str, sid: str) -> dict:
    return {"id": sid, "username": owner}


def _reset_settings(monkeypatch, **env):
    """Apply env vars and force a fresh Settings instance."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from backend import config
    if hasattr(config.get_settings, "cache_clear"):
        config.get_settings.cache_clear()


async def test_no_token_returns_empty(monkeypatch):
    _reset_settings(monkeypatch, INSTAGRAM_APIFY_TOKEN="", DATABASE_URL="")
    items, summary = await scraper.scrape_account_content(["acc1"], pool=None)
    assert items == []
    assert summary["posts_billed"] == 0


async def test_two_passes_invoke_two_actors(monkeypatch):
    """When token is set, both posts and stories actors are called once."""
    _reset_settings(monkeypatch, INSTAGRAM_APIFY_TOKEN="fake_token")

    calls: list[str] = []

    def fake_run(client, actor_id, run_input):
        calls.append(actor_id)
        if "stories" in actor_id:
            return [_fake_story("acc1", "s1"), _fake_story("acc2", "s2")]
        return [_fake_post("acc1", "p1"), _fake_post("acc2", "p2")]

    with patch.object(scraper, "_run_actor_sync", side_effect=fake_run):
        items, summary = await scraper.scrape_account_content(
            ["acc1", "acc2"], pool=None
        )

    assert len(calls) == 2
    assert any("instagram-api-scraper" in c for c in calls)
    assert any("instagram-stories-scraper" in c for c in calls)
    assert summary["posts_billed"] == 2
    assert summary["stories_billed"] == 2
    # All items get an _origin tag.
    assert all("_origin" in i for i in items)
    origins = {i["_origin"] for i in items}
    assert origins == {"profile", "story"}


async def test_stories_disabled_skips_stories_pass(monkeypatch):
    _reset_settings(
        monkeypatch,
        INSTAGRAM_APIFY_TOKEN="fake_token",
        SCRAPE_INCLUDE_STORIES="false",
    )

    calls: list[str] = []

    def fake_run(client, actor_id, run_input):
        calls.append(actor_id)
        return [_fake_post("acc1", "p1")]

    with patch.object(scraper, "_run_actor_sync", side_effect=fake_run):
        _, summary = await scraper.scrape_account_content(["acc1"], pool=None)

    assert len(calls) == 1
    assert "stories" not in calls[0]
    assert summary["stories_billed"] == 0


async def test_error_rows_are_filtered(monkeypatch):
    _reset_settings(
        monkeypatch,
        INSTAGRAM_APIFY_TOKEN="fake_token",
        SCRAPE_INCLUDE_STORIES="false",
    )

    def fake_run(client, actor_id, run_input):
        return [
            {"error": "not_found", "errorDescription": "Post does not exist", "username": "acc1"},
            _fake_post("acc1", "p1"),
        ]

    with patch.object(scraper, "_run_actor_sync", side_effect=fake_run):
        items, summary = await scraper.scrape_account_content(["acc1"], pool=None)

    assert summary["posts_billed"] == 1
    assert all("error" not in i for i in items)


async def test_per_account_story_cap(monkeypatch):
    _reset_settings(
        monkeypatch,
        INSTAGRAM_APIFY_TOKEN="fake_token",
        MAX_STORIES_PER_ACCOUNT="2",
    )

    def fake_run(client, actor_id, run_input):
        if "stories" in actor_id:
            # 5 stories from same account
            return [_fake_story("acc1", f"s{i}") for i in range(5)]
        return []

    with patch.object(scraper, "_run_actor_sync", side_effect=fake_run):
        items, summary = await scraper.scrape_account_content(["acc1"], pool=None)

    story_items = [i for i in items if i.get("_origin") == "story"]
    assert len(story_items) == 2
