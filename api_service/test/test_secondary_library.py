"""
Tests for the optional secondary media server library loader.

Covers:
- get_secondary_config(): fully configured, partially configured, unsupported type
- load_secondary_library_sets(): not configured, jellyfin/emby, plex ID normalisation,
  client failure (fails open), client is always closed
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api_service.services.secondary_library import (
    get_secondary_config,
    load_secondary_library_sets,
)


JELLYFIN_ENV = {
    'SECONDARY_SERVICE': 'jellyfin',
    'SECONDARY_API_URL': 'http://second-jellyfin.local',
    'SECONDARY_TOKEN': 'token-2',
    'SECONDARY_LIBRARIES': [{'id': 'lib-1', 'name': 'Movies'}],
}

PLEX_ENV = {
    'SECONDARY_SERVICE': 'plex',
    'SECONDARY_API_URL': 'http://second-plex.local:32400',
    'SECONDARY_TOKEN': 'plex-token-2',
    'SECONDARY_LIBRARIES': [{'id': '1', 'name': 'Films'}],
}


def _fake_client(existing_content):
    client = MagicMock()
    client.existing_content = existing_content
    client.init_existing_content = AsyncMock()
    client.close = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# get_secondary_config
# ---------------------------------------------------------------------------

def test_get_secondary_config_returns_normalized_config():
    config = get_secondary_config({**JELLYFIN_ENV, 'SECONDARY_SERVICE': ' Jellyfin '})

    assert config == {
        'service': 'jellyfin',
        'api_url': 'http://second-jellyfin.local',
        'token': 'token-2',
        'libraries': [{'id': 'lib-1', 'name': 'Movies'}],
    }


@pytest.mark.parametrize('missing_key', ['SECONDARY_SERVICE', 'SECONDARY_API_URL', 'SECONDARY_TOKEN'])
def test_get_secondary_config_requires_all_fields(missing_key):
    env = {**JELLYFIN_ENV, missing_key: ''}

    assert get_secondary_config(env) is None


def test_get_secondary_config_rejects_unsupported_service():
    assert get_secondary_config({**JELLYFIN_ENV, 'SECONDARY_SERVICE': 'trakt'}) is None


def test_get_secondary_config_defaults_non_list_libraries():
    config = get_secondary_config({**JELLYFIN_ENV, 'SECONDARY_LIBRARIES': 'not-a-list'})

    assert config['libraries'] == []


# ---------------------------------------------------------------------------
# load_secondary_library_sets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_returns_empty_when_not_configured():
    assert await load_secondary_library_sets({}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('service', ['jellyfin', 'emby'])
async def test_load_jellyfin_compatible_server(service):
    client = _fake_client({
        'movie': [{'tmdb_id': '550'}, {'tmdb_id': None}],
        'tv': [{'tmdb_id': '1399'}],
    })

    with patch(
        'api_service.services.jellyfin.jellyfin_client.JellyfinClient',
        return_value=client,
    ) as client_cls:
        result = await load_secondary_library_sets(
            {**JELLYFIN_ENV, 'SECONDARY_SERVICE': service}, max_content=15
        )

    assert result == {'movie': {'550'}, 'tv': {'1399'}}
    client_cls.assert_called_once_with(
        'http://second-jellyfin.local',
        'token-2',
        15,
        [{'id': 'lib-1', 'name': 'Movies'}],
    )
    client.init_existing_content.assert_awaited_once()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_plex_normalizes_tmdb_ids():
    client = _fake_client({'movie': [{'tmdb_id': '808?lang=en'}]})

    with patch(
        'api_service.services.plex.plex_client.PlexClient',
        return_value=client,
    ) as client_cls:
        result = await load_secondary_library_sets(PLEX_ENV)

    assert result == {'movie': {'808'}}
    assert client_cls.call_args.kwargs['api_url'] == 'http://second-plex.local:32400'
    assert client_cls.call_args.kwargs['token'] == 'plex-token-2'
    assert client_cls.call_args.kwargs['library_ids'] == [{'id': '1', 'name': 'Films'}]
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_returns_empty_and_closes_client_on_failure():
    client = _fake_client(None)
    client.init_existing_content = AsyncMock(side_effect=ConnectionError('unreachable'))

    with patch(
        'api_service.services.jellyfin.jellyfin_client.JellyfinClient',
        return_value=client,
    ):
        result = await load_secondary_library_sets(JELLYFIN_ENV)

    assert result == {}
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_handles_empty_library():
    client = _fake_client(None)

    with patch(
        'api_service.services.jellyfin.jellyfin_client.JellyfinClient',
        return_value=client,
    ):
        result = await load_secondary_library_sets(JELLYFIN_ENV)

    assert result == {}
    client.close.assert_awaited_once()
