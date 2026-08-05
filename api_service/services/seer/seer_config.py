"""
Helpers for routing requests to the primary or optional secondary Seer instance.
"""
from typing import Any, Dict, List, Optional

from api_service.config.logger_manager import LoggerManager
from api_service.services.seer.seer_client import SeerClient
from api_service.services.seer.seer_targets import VALID_TARGETS, normalize_seer_target

logger = LoggerManager.get_logger("SeerConfig")


def get_seer_target_config(env_vars: Dict[str, Any], target: str = "primary") -> Optional[Dict[str, Any]]:
    """
    Extract connection settings for a Seer target.

    Args:
        env_vars: Flat runtime configuration dictionary.
        target: ``primary`` or ``secondary``.

    Returns:
        Dict with api_url, token, session_token, user_name, password keys, or None
        when the target is not fully configured.
    """
    target = normalize_seer_target(target)
    if target == "primary":
        api_url = str(env_vars.get("SEER_API_URL") or "").strip()
        token = str(env_vars.get("SEER_TOKEN") or "").strip()
        return {
            "api_url": api_url,
            "token": token,
            "session_token": env_vars.get("SEER_SESSION_TOKEN"),
            "user_name": env_vars.get("SEER_USER_NAME"),
            "password": env_vars.get("SEER_USER_PSW"),
        } if api_url and token else None

    api_url = str(env_vars.get("SECONDARY_SEER_API_URL") or "").strip()
    token = str(env_vars.get("SECONDARY_SEER_TOKEN") or "").strip()
    if not api_url or not token:
        return None
    return {
        "api_url": api_url,
        "token": token,
        "session_token": env_vars.get("SECONDARY_SEER_SESSION_TOKEN"),
        "user_name": env_vars.get("SECONDARY_SEER_USER_NAME"),
        "password": env_vars.get("SECONDARY_SEER_USER_PSW"),
    }


def is_secondary_seer_configured(env_vars: Dict[str, Any]) -> bool:
    """Return True when the optional secondary Seer instance is configured."""
    return get_seer_target_config(env_vars, "secondary") is not None


def create_seer_client(env_vars: Dict[str, Any], target: str = "primary", **runtime_kwargs) -> Optional[SeerClient]:
    """
    Build a ``SeerClient`` for the requested target.

    Args:
        env_vars: Flat runtime configuration dictionary.
        target: ``primary`` or ``secondary``.
        **runtime_kwargs: Extra keyword arguments forwarded to ``SeerClient``.

    Returns:
        Configured client, or None when the target is unavailable.
    """
    config = get_seer_target_config(env_vars, target)
    if not config:
        return None

    kwargs = {
        "number_of_seasons": env_vars.get("FILTER_NUM_SEASONS") or "all",
        "exclude_downloaded": False,
        "exclude_watched": False,
        "anime_profile_config": env_vars.get("SEER_ANIME_PROFILE_CONFIG") or {},
        "request_first_season_only": env_vars.get("REQUEST_FIRST_SEASON_ONLY", False),
    }
    kwargs.update(runtime_kwargs)

    return SeerClient(
        config["api_url"],
        config["token"],
        seer_user_name=config.get("user_name"),
        seer_password=config.get("password"),
        session_token=config.get("session_token"),
        **kwargs,
    )


def list_seer_targets(env_vars: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    List configured Seer targets for UI routing and deep links.

    Args:
        env_vars: Flat runtime configuration dictionary.

    Returns:
        List of dicts with id, label, configured, and web_url keys.
    """
    primary_label = str(env_vars.get("SEER_PRIMARY_LABEL") or "Primary").strip() or "Primary"
    secondary_label = str(env_vars.get("SECONDARY_SEER_LABEL") or "Secondary").strip() or "Secondary"
    targets: List[Dict[str, Any]] = []

    primary = get_seer_target_config(env_vars, "primary")
    if primary:
        targets.append({
            "id": "primary",
            "label": primary_label,
            "configured": True,
            "web_url": primary["api_url"].rstrip("/"),
        })

    secondary = get_seer_target_config(env_vars, "secondary")
    if secondary:
        targets.append({
            "id": "secondary",
            "label": secondary_label,
            "configured": True,
            "web_url": secondary["api_url"].rstrip("/"),
        })

    return targets


def build_ai_search_payload(env_vars: Dict[str, Any], media_type: str, tmdb_id: int) -> Dict[str, Any]:
    """
    Build the Seer request payload used by AI Search direct submissions.

    Args:
        env_vars: Flat runtime configuration dictionary.
        media_type: ``movie`` or ``tv``.
        tmdb_id: TMDB id of the requested item.

    Returns:
        Payload dict suitable for ``SeerClient.submit_queued_request``.
    """
    payload: Dict[str, Any] = {"mediaType": media_type, "mediaId": int(tmdb_id)}
    if media_type != "tv":
        return payload

    num_seasons = env_vars.get("FILTER_NUM_SEASONS", "all")
    first_season_only = env_vars.get("REQUEST_FIRST_SEASON_ONLY", False)
    first_season_only = (
        first_season_only if isinstance(first_season_only, bool)
        else str(first_season_only).strip().lower() in {"1", "true", "yes", "on"}
    )
    if first_season_only:
        payload["seasons"] = [1]
    elif num_seasons in (None, "", "all", 0, "0"):
        payload["seasons"] = "all"
    else:
        payload["seasons"] = list(range(1, int(num_seasons) + 1))
    return payload


async def submit_direct_seer_request(
    env_vars: Dict[str, Any],
    target: str,
    media_type: str,
    tmdb_id: int,
) -> bool:
    """
    Submit a direct Seer request for AI Search or similar manual flows.

    Args:
        env_vars: Flat runtime configuration dictionary.
        target: ``primary`` or ``secondary``.
        media_type: ``movie`` or ``tv``.
        tmdb_id: TMDB id of the requested item.

    Returns:
        True when Seer accepted the request.
    """
    client = create_seer_client(env_vars, target)
    if client is None:
        logger.warning("Seer target %s is not configured.", target)
        return False

    payload = build_ai_search_payload(env_vars, media_type, tmdb_id)
    async with client:
        await client.init()
        return await client.submit_queued_request(payload)
