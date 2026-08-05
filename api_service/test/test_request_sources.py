"""Tests for request source tag helpers."""
from unittest.mock import patch

from api_service.db import database_manager as dm_mod
from api_service.db.database_manager import DatabaseManager
from api_service.services.request_sources import (
    AI_SEARCH_SOURCE,
    DISCOVER_SOURCE,
    TRAKT_RECOMMENDATIONS_SOURCE,
    is_tmdb_metadata_source_id,
    request_source_title_sql,
    resolve_request_source_label,
)


def test_trakt_source_is_not_metadata_id():
    assert is_tmdb_metadata_source_id(TRAKT_RECOMMENDATIONS_SOURCE) is False
    assert is_tmdb_metadata_source_id(DISCOVER_SOURCE) is False
    assert is_tmdb_metadata_source_id("27205") is True
    assert is_tmdb_metadata_source_id("ai_search") is False


def test_resolve_request_source_label_covers_every_source_kind():
    assert resolve_request_source_label("27205", "Inception") == "Inception"
    assert resolve_request_source_label(DISCOVER_SOURCE) == "Discover"
    assert resolve_request_source_label(TRAKT_RECOMMENDATIONS_SOURCE) == "Trakt Recommendations"
    assert resolve_request_source_label(AI_SEARCH_SOURCE) == "AI Search"
    # LLM fallback sentinel, unknown TMDb id without metadata, and no source.
    assert resolve_request_source_label(0) == "LLM Recommendation"
    assert resolve_request_source_label("27205") == "LLM Recommendation"
    assert resolve_request_source_label(None) == "LLM Recommendation"


def test_resolve_request_source_label_matches_sql_fallback():
    assert f"ELSE '{resolve_request_source_label(None)}'" in request_source_title_sql("r")


def test_request_source_title_sql_includes_trakt_label():
    sql = request_source_title_sql("r")
    assert "trakt_recommendations" in sql
    assert "Trakt Recommendations" in sql
    assert "discover" in sql
    assert "Discover" in sql


def test_grouped_requests_labels_synthetic_sources(tmp_path):
    db_file = str(tmp_path / "requests.db")
    with (
        patch.object(dm_mod, "DB_PATH", db_file),
        patch("api_service.db.database_manager.load_env_vars", return_value={"DB_TYPE": "sqlite"}),
    ):
        DatabaseManager._instance = None
        db = DatabaseManager()
        db.save_metadata({"id": "101", "title": "Discover Request"}, "movie")
        db.save_metadata({"id": "202", "title": "Trakt Request"}, "tv")
        db.save_request("movie", "101", DISCOVER_SOURCE)
        db.save_request("tv", "202", TRAKT_RECOMMENDATIONS_SOURCE)

        result = db.get_all_requests_grouped_by_source(page=1, per_page=10)

    DatabaseManager._instance = None

    sources = {item["source_id"]: item for item in result["data"]}
    assert result["total_sources"] == 2
    assert sources[DISCOVER_SOURCE]["source_title"] == "Discover"
    assert sources[TRAKT_RECOMMENDATIONS_SOURCE]["source_title"] == "Trakt Recommendations"


def test_grouped_requests_include_requested_for_user(tmp_path):
    db_file = str(tmp_path / "requests.db")
    with (
        patch.object(dm_mod, "DB_PATH", db_file),
        patch("api_service.db.database_manager.load_env_vars", return_value={"DB_TYPE": "sqlite"}),
    ):
        DatabaseManager._instance = None
        db = DatabaseManager()
        db.save_user({"id": "plex-1", "name": "Alice"})
        db.save_user({"id": "plex-2", "name": "Bob"})
        db.save_metadata({"id": "101", "title": "Request"}, "movie")
        db.save_metadata({"id": "102", "title": "Other Request"}, "movie")
        db.save_request("movie", "101", DISCOVER_SOURCE, user_id="plex-1")
        db.save_request("movie", "102", DISCOVER_SOURCE, user_id="plex-2")

        result = db.get_all_requests_grouped_by_source(user_ids=["plex-1"])
        request = result["data"][0]["requests"][0]

    DatabaseManager._instance = None
    assert request["user_id"] == "plex-1"
    assert request["user_name"] == "Alice"
    assert result["total_requests"] == 1
    assert result["request_users"] == [{"id": "plex-1", "name": "Alice"}]


def test_grouped_requests_resolve_name_from_media_identity(tmp_path):
    db_file = str(tmp_path / "requests.db")
    with (
        patch.object(dm_mod, "DB_PATH", db_file),
        patch("api_service.db.database_manager.load_env_vars", return_value={"DB_TYPE": "sqlite"}),
    ):
        DatabaseManager._instance = None
        db = DatabaseManager()
        db.upsert_media_user_identity("jellyfin", "jellyfin-code", "Alice Jellyfin")
        db.save_metadata({"id": "101", "title": "Request"}, "movie")
        db.save_request("movie", "101", DISCOVER_SOURCE, user_id="jellyfin-code")

        request = db.get_all_requests_grouped_by_source()["data"][0]["requests"][0]

    DatabaseManager._instance = None
    assert request["user_name"] == "Alice Jellyfin"


def test_pending_requests_filter_by_requested_for_user(tmp_path):
    db_file = str(tmp_path / "requests.db")
    with (
        patch.object(dm_mod, "DB_PATH", db_file),
        patch("api_service.db.database_manager.load_env_vars", return_value={"DB_TYPE": "sqlite"}),
    ):
        DatabaseManager._instance = None
        db = DatabaseManager()
        db.enqueue_request("101", "movie", None, {"_user_id": "plex-1"}, status="awaiting_approval")
        db.enqueue_request("102", "movie", None, {"_user_id": "plex-2"}, status="awaiting_approval")

        items, total = db.list_suggestions(media_user_ids=["plex-1"])

    DatabaseManager._instance = None
    assert total == 1
    assert items[0]["media_user_id"] == "plex-1"


def test_pending_requests_resolve_source_from_payload(tmp_path):
    """The watched item a suggestion came from lives in the queued payload and
    must be resolved for the approval UI."""
    db_file = str(tmp_path / "requests.db")
    with (
        patch.object(dm_mod, "DB_PATH", db_file),
        patch("api_service.db.database_manager.load_env_vars", return_value={"DB_TYPE": "sqlite"}),
    ):
        DatabaseManager._instance = None
        db = DatabaseManager()
        db.save_metadata(
            {"id": "27205", "title": "Inception", "poster_path": "/inception.jpg"}, "movie"
        )
        db.enqueue_request(
            "101", "movie", None,
            {"_source_id": 27205, "_rationale": "Shared cerebral energy."},
            status="awaiting_approval",
        )
        db.enqueue_request(
            "102", "movie", None,
            {"_source_id": DISCOVER_SOURCE},
            status="awaiting_approval",
        )

        items, _total = db.list_suggestions()

    DatabaseManager._instance = None

    by_tmdb_id = {item["tmdb_id"]: item for item in items}
    assert by_tmdb_id["101"]["source_title"] == "Inception"
    assert by_tmdb_id["101"]["source_poster_path"] == "/inception.jpg"
    assert by_tmdb_id["101"]["rationale"] == "Shared cerebral energy."
    assert by_tmdb_id["102"]["source_title"] == "Discover"
    assert by_tmdb_id["102"]["source_poster_path"] is None


def test_save_user_without_name_falls_back_to_id(tmp_path):
    """Regression: the Trakt recommendations job calls save_user with only an
    'id' (no display name). save_user must not raise KeyError on 'name'."""
    db_file = str(tmp_path / "requests.db")
    with (
        patch.object(dm_mod, "DB_PATH", db_file),
        patch("api_service.db.database_manager.load_env_vars", return_value={"DB_TYPE": "sqlite"}),
    ):
        DatabaseManager._instance = None
        db = DatabaseManager()

        # Must not raise even though 'name' is absent.
        db.save_user({"id": "trakt-user-1"})

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_name FROM users WHERE user_id = ?", ("trakt-user-1",)
            )
            row = cursor.fetchone()

    DatabaseManager._instance = None
    assert row is not None
    assert row[0] == "trakt-user-1"  # falls back to the id when name is missing
