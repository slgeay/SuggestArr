"""
Loader for the optional secondary media server library.

The secondary server is used for a single purpose: widening the set of TMDB IDs
that are considered "already owned", so content available on either server is
never requested again. It contributes no watch history, users, or cleanup
behaviour.
"""
from typing import Any, Dict, Optional, Set

from api_service.config.logger_manager import LoggerManager

logger = LoggerManager.get_logger("SecondaryLibrary")

JELLYFIN_COMPATIBLE_SERVICES = ('jellyfin', 'emby')


def _to_tmdb_id_sets(existing_content: Optional[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Normalize a client's existing-content map into media-type keyed TMDB ID sets."""
    content_sets: Dict[str, Set[str]] = {}
    if not existing_content:
        return content_sets

    for media_type, items in existing_content.items():
        ids = set()
        for item in items or []:
            if isinstance(item, dict):
                tmdb_id = item.get('tmdb_id')
                if tmdb_id:
                    ids.add(str(tmdb_id))
            elif item:
                ids.add(str(item))
        if ids:
            content_sets[media_type] = ids
    return content_sets


def get_secondary_config(env_vars: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract the secondary media server configuration.

    Args:
        env_vars: Flat configuration dictionary.

    Returns:
        A dict with 'service', 'api_url', 'token' and 'libraries' keys, or None
        when the secondary server is not fully configured.
    """
    service = str(env_vars.get('SECONDARY_SERVICE') or '').strip().lower()
    api_url = str(env_vars.get('SECONDARY_API_URL') or '').strip()
    token = str(env_vars.get('SECONDARY_TOKEN') or '').strip()

    if not service or not api_url or not token:
        return None

    if service not in JELLYFIN_COMPATIBLE_SERVICES and service != 'plex':
        logger.warning("Unsupported secondary media server type: %s", service)
        return None

    libraries_raw = env_vars.get('SECONDARY_LIBRARIES')
    libraries = libraries_raw if isinstance(libraries_raw, list) else []

    return {
        'service': service,
        'api_url': api_url,
        'token': token,
        'libraries': libraries,
    }


async def load_secondary_library_sets(env_vars: Dict[str, Any], max_content: int = 10) -> Dict[str, Set[str]]:
    """
    Load the secondary media server library as media-type keyed TMDB ID sets.

    Failures are non-fatal: an unreachable or misconfigured secondary server
    degrades to an empty result rather than blocking the automation run.

    Args:
        env_vars: Flat configuration dictionary.
        max_content: Max content hint passed to the media client.

    Returns:
        Dict mapping media type ('movie'/'tv') to a set of TMDB ID strings.
        Empty when no secondary server is configured or the fetch failed.
    """
    config = get_secondary_config(env_vars)
    if not config:
        return {}

    service = config['service']
    client = None
    try:
        if service in JELLYFIN_COMPATIBLE_SERVICES:
            from api_service.services.jellyfin.jellyfin_client import JellyfinClient

            client = JellyfinClient(
                config['api_url'],
                config['token'],
                max_content,
                config['libraries'],
            )
            await client.init_existing_content()
            content_sets = _to_tmdb_id_sets(client.existing_content)
        else:
            from api_service.services.plex.plex_client import PlexClient, normalize_guid_provider_id

            client = PlexClient(
                api_url=config['api_url'],
                token=config['token'],
                max_content=max_content,
                library_ids=config['libraries'],
            )
            await client.init_existing_content()
            content_sets = {
                media_type: {
                    normalize_guid_provider_id(f'tmdb://{tmdb_id}', 'tmdb') or str(tmdb_id)
                    for tmdb_id in ids
                }
                for media_type, ids in _to_tmdb_id_sets(client.existing_content).items()
            }

        total = sum(len(ids) for ids in content_sets.values())
        logger.info("Secondary %s library loaded: %d TMDB IDs.", service, total)
        return content_sets
    except Exception as exc:
        logger.warning(
            "Could not load secondary %s library; continuing without it: %s",
            service, exc,
        )
        return {}
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as exc:
                logger.debug("Error closing secondary %s client: %s", service, exc)
