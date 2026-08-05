"""
AI Search blueprint — semantic movie/TV search powered by LLM + TMDB.
"""

import asyncio

from flask import Blueprint, jsonify, request

from api_service.auth.limiter import limiter
from api_service.config.logger_manager import LoggerManager
from api_service.db.database_manager import DatabaseManager
from api_service.services.ai_search.ai_search_service import AiSearchService
from api_service.services.config_service import ConfigService
from api_service.services.llm.llm_service import get_llm_client
from api_service.services.seer.seer_config import (
    get_seer_target_config,
    is_secondary_seer_configured,
    normalize_seer_target,
    submit_direct_seer_request,
)

ai_search_bp = Blueprint("ai_search", __name__)
logger = LoggerManager.get_logger("AiSearchRoute")


@ai_search_bp.route("/query", methods=["POST"])
@limiter.limit("10 per minute")
async def ai_search_query():
    """Execute an AI-powered semantic search.

    Request body:
        query (str): Natural language description of desired content.
        media_type (str): 'movie', 'tv', or 'both'. Defaults to 'movie'.
        user_ids (list): Optional list of media-server user IDs to scope history.
        max_results (int): Maximum results to return (default 12).

    Returns:
        JSON response with 'results', 'ai_reasoning', and 'total'.
    """
    try:
        data = request.json or {}
        query = (data.get("query") or "").strip()
        if not query:
            return jsonify({"status": "error", "message": "query is required"}), 400

        media_type = data.get("media_type", "movie")
        if media_type not in ("movie", "tv", "both"):
            media_type = "movie"

        user_ids = data.get("user_ids") or []
        max_results = int(data.get("max_results") or 12)
        use_history = data.get("use_history", True)
        if not isinstance(use_history, bool):
            use_history = True
        exclude_watched = data.get("exclude_watched", True)
        if not isinstance(exclude_watched, bool):
            exclude_watched = True
        exclude_seen = data.get("exclude_seen", False)
        if not isinstance(exclude_seen, bool):
            exclude_seen = False

        # Check LLM is configured (not strictly required — service degrades gracefully,
        # but we surface a clear error before attempting if completely unconfigured)
        if not get_llm_client():
            return jsonify({
                "status": "error",
                "message": (
                    "LLM is not configured. "
                    "Please set OPENAI_API_KEY (and optionally OPENAI_BASE_URL) "
                    "in the Advanced settings."
                ),
            }), 400

        service = AiSearchService()
        result = await service.search(
            query=query,
            media_type=media_type,
            user_ids=user_ids if user_ids else None,
            max_results=max_results,
            use_history=use_history,
            exclude_watched=exclude_watched,
            exclude_seen=exclude_seen,
        )

        return jsonify({
            "status": "success",
            "results": result.get("results", []),
            "ai_reasoning": result.get("ai_reasoning", {}),
            "total": result.get("total", 0),
        }), 200

    except Exception as exc:
        logger.error("Error during AI search query: %s", str(exc))
        return jsonify({"status": "error", "message": f"Search failed: {str(exc)}"}), 500


@ai_search_bp.route("/request", methods=["POST"])
@limiter.limit("20 per minute")
async def ai_search_request():
    """Request a media item via Seer.

    Calls the Seer API directly so the local database entry is saved with
    ``tmdb_source_id = 'ai_search'`` (allowing proper separation from
    watched-content recommendations) and with full item metadata so the title
    is stored correctly.

    Request body:
        tmdb_id (int): TMDB ID of the item to request.
        media_type (str): 'movie' or 'tv'.
        rationale (str): Optional AI per-item rationale (why this title was suggested).
        search_query (str): The original natural-language query used for this search.
        metadata (dict): Full item metadata dict (title, poster_path, overview,
            release_date, rating, …) returned by the search endpoint.
        seer_target (str): ``primary`` or ``secondary`` Seer instance to submit to.

    Returns:
        JSON response with 'status' and 'message'.
    """
    try:
        data = request.json or {}
        tmdb_id = data.get("tmdb_id")
        media_type = data.get("media_type", "movie")
        rationale = data.get("rationale") or None
        search_query = (data.get("search_query") or "").strip() or None
        metadata = data.get("metadata") or {}
        seer_target = normalize_seer_target(data.get("seer_target"))
        db_rationale = search_query or rationale

        if not tmdb_id:
            return jsonify({"status": "error", "message": "tmdb_id is required"}), 400
        if media_type not in ("movie", "tv"):
            return jsonify({"status": "error", "message": "media_type must be 'movie' or 'tv'"}), 400

        config = ConfigService.get_runtime_config()
        if seer_target == "secondary" and not is_secondary_seer_configured(config):
            return jsonify({
                "status": "error",
                "message": "Secondary Seer is not configured.",
            }), 400
        if get_seer_target_config(config, seer_target) is None:
            return jsonify({
                "status": "error",
                "message": "Seer is not configured.",
            }), 400

        success = await submit_direct_seer_request(
            config, seer_target, media_type, int(tmdb_id),
        )
        if success:
            db = DatabaseManager()
            media_dict = {"id": str(tmdb_id)}
            media_dict.update(metadata)
            db.save_metadata(media_dict, media_type)
            db.save_request(
                media_type, str(tmdb_id), "ai_search", None, rationale=db_rationale
            )
            return jsonify({"status": "success", "message": "Request submitted successfully."}), 200

        return jsonify({
            "status": "error",
            "message": "Already requested or already available.",
        }), 409

    except Exception as exc:
        logger.error("Error during AI search request: %s", str(exc))
        return jsonify({"status": "error", "message": f"Request failed: {str(exc)}"}), 500


@ai_search_bp.route("/status", methods=["GET"])
def ai_search_status():
    """Return whether the LLM is configured and AI search is available.

    Returns:
        JSON with 'available' bool and optional 'message'.
    """
    client = get_llm_client()
    if client:
        return jsonify({"available": True}), 200
    return jsonify({
        "available": False,
        "message": (
            "LLM is not configured. "
            "Set OPENAI_API_KEY (and optionally OPENAI_BASE_URL) in Advanced settings."
        ),
    }), 200


@ai_search_bp.route("/feedback", methods=["GET"])
def ai_search_feedback_list():
    """Return all stored like/dislike feedback so the frontend can render state."""
    try:
        rows = DatabaseManager().get_all_ai_feedback()
        return jsonify({"status": "success", "feedback": rows}), 200
    except Exception as exc:
        logger.error("Failed to list ai feedback: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@ai_search_bp.route("/feedback", methods=["POST"])
@limiter.limit("60 per minute")
def ai_search_feedback_set():
    """Record a like or dislike for an AI search result.

    Request body:
        tmdb_id (int|str): TMDB id.
        media_type (str): 'movie' or 'tv'.
        feedback (str): 'like' or 'dislike'.
        title (str, optional)
        year (int, optional)
    """
    try:
        data = request.json or {}
        tmdb_id = data.get("tmdb_id")
        media_type = data.get("media_type")
        feedback = data.get("feedback")
        title = data.get("title")
        year = data.get("year")
        if year is not None:
            try:
                year = int(year)
            except (TypeError, ValueError):
                year = None
        if not tmdb_id:
            return jsonify({"status": "error", "message": "tmdb_id is required"}), 400
        if media_type not in ("movie", "tv"):
            return jsonify({"status": "error", "message": "media_type must be 'movie' or 'tv'"}), 400
        if feedback not in ("like", "dislike"):
            return jsonify({"status": "error", "message": "feedback must be 'like' or 'dislike'"}), 400
        DatabaseManager().set_ai_feedback(str(tmdb_id), media_type, feedback, title=title, year=year)
        return jsonify({"status": "success"}), 200
    except Exception as exc:
        logger.error("Failed to set ai feedback: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@ai_search_bp.route("/feedback", methods=["DELETE"])
@limiter.limit("60 per minute")
def ai_search_feedback_delete():
    """Remove feedback for a TMDB item."""
    try:
        data = request.json or {}
        tmdb_id = data.get("tmdb_id")
        media_type = data.get("media_type")
        if not tmdb_id or media_type not in ("movie", "tv"):
            return jsonify({"status": "error", "message": "tmdb_id and media_type required"}), 400
        DatabaseManager().delete_ai_feedback(str(tmdb_id), media_type)
        return jsonify({"status": "success"}), 200
    except Exception as exc:
        logger.error("Failed to delete ai feedback: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500



@ai_search_bp.route("/seen", methods=["DELETE"])
@limiter.limit("30 per minute")
def ai_search_seen_clear():
    """Clear the already-recommended history (optionally per media_type)."""
    try:
        data = request.json or {}
        media_type = data.get("media_type")
        if media_type and media_type not in ("movie", "tv"):
            return jsonify({"status": "error", "message": "media_type must be 'movie' or 'tv'"}), 400
        deleted = DatabaseManager().clear_ai_seen(media_type)
        return jsonify({"status": "success", "deleted": deleted}), 200
    except Exception as exc:
        logger.error("Failed to clear ai seen: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
