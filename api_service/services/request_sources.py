"""Canonical request-source tags for non-TMDb automation origins."""

DISCOVER_SOURCE = "discover"
TRAKT_RECOMMENDATIONS_SOURCE = "trakt_recommendations"
AI_SEARCH_SOURCE = "ai_search"

REQUEST_SOURCE_LABELS = {
    DISCOVER_SOURCE: "Discover",
    TRAKT_RECOMMENDATIONS_SOURCE: "Trakt Recommendations",
}

# Shown when no watched item could be attributed to the recommendation.
LLM_RECOMMENDATION_LABEL = "LLM Recommendation"

AI_SEARCH_LABEL = "AI Search"


def is_tmdb_metadata_source_id(source_id) -> bool:
    """Return True when *source_id* should be stored in the metadata table."""
    if source_id is None:
        return False
    text = str(source_id)
    if text in REQUEST_SOURCE_LABELS or text == AI_SEARCH_SOURCE:
        return False
    return text.isdigit()


def resolve_request_source_label(source_id, metadata_title=None) -> str:
    """Resolve a request source id to its display label.

    Python counterpart of :func:`request_source_title_sql` for call sites that
    cannot resolve the label in SQL (e.g. sources stored inside a JSON payload).

    :param source_id: Raw source id: a TMDb id, a canonical source tag
        (``discover``, ``trakt_recommendations``, ``ai_search``), ``0`` or None.
    :param metadata_title: Title looked up in the metadata table for a TMDb
        source id, when available.
    :return: Human-readable source label.
    """
    if metadata_title:
        return metadata_title
    text = str(source_id) if source_id is not None else ""
    if text in REQUEST_SOURCE_LABELS:
        return REQUEST_SOURCE_LABELS[text]
    if text == AI_SEARCH_SOURCE:
        return AI_SEARCH_LABEL
    return LLM_RECOMMENDATION_LABEL


def request_source_title_sql(source_alias: str = "r") -> str:
    """Build a SQL CASE expression for grouped request source titles."""
    when_clauses = "\n                ".join(
        f"WHEN {source_alias}.tmdb_source_id = '{tag}' THEN '{label}'"
        for tag, label in REQUEST_SOURCE_LABELS.items()
    )
    return f"""CASE
                WHEN s.title IS NOT NULL THEN s.title
                {when_clauses}
                ELSE '{LLM_RECOMMENDATION_LABEL}'
            END"""
