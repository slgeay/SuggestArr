"""Tests for dual Seer target configuration helpers."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from api_service.services.seer.seer_config import (
    build_ai_search_payload,
    create_seer_client,
    get_seer_target_config,
    is_secondary_seer_configured,
    list_seer_targets,
    normalize_seer_target,
    submit_direct_seer_request,
)


def test_normalize_seer_target_defaults_to_primary():
    assert normalize_seer_target(None) == 'primary'
    assert normalize_seer_target('') == 'primary'
    assert normalize_seer_target('SECONDARY') == 'secondary'
    assert normalize_seer_target('invalid') == 'primary'


def test_get_seer_target_config_primary_requires_url_and_token():
    assert get_seer_target_config({}, 'primary') is None
    assert get_seer_target_config({'SEER_API_URL': 'http://seer'}, 'primary') is None
    config = get_seer_target_config({
        'SEER_API_URL': 'http://seer/',
        'SEER_TOKEN': 'token',
        'SEER_SESSION_TOKEN': 'sess',
    }, 'primary')
    assert config['api_url'] == 'http://seer/'
    assert config['token'] == 'token'
    assert config['session_token'] == 'sess'


def test_get_seer_target_config_secondary_requires_url_and_token():
    assert get_seer_target_config({}, 'secondary') is None
    config = get_seer_target_config({
        'SECONDARY_SEER_API_URL': 'http://second/',
        'SECONDARY_SEER_TOKEN': 'tok2',
    }, 'secondary')
    assert config['api_url'] == 'http://second/'
    assert config['token'] == 'tok2'


def test_is_secondary_seer_configured():
    assert not is_secondary_seer_configured({})
    assert is_secondary_seer_configured({
        'SECONDARY_SEER_API_URL': 'http://second',
        'SECONDARY_SEER_TOKEN': 'tok',
    })


def test_list_seer_targets_includes_labels_and_web_urls():
    targets = list_seer_targets({
        'SEER_API_URL': 'http://primary/',
        'SEER_TOKEN': 'p',
        'SEER_PRIMARY_LABEL': 'Home',
        'SECONDARY_SEER_API_URL': 'http://secondary/',
        'SECONDARY_SEER_TOKEN': 's',
        'SECONDARY_SEER_LABEL': 'Remote',
    })
    assert len(targets) == 2
    assert targets[0] == {
        'id': 'primary',
        'label': 'Home',
        'configured': True,
        'web_url': 'http://primary',
    }
    assert targets[1]['id'] == 'secondary'
    assert targets[1]['label'] == 'Remote'
    assert targets[1]['web_url'] == 'http://secondary'


def test_build_ai_search_payload_tv_season_rules():
    payload = build_ai_search_payload({'REQUEST_FIRST_SEASON_ONLY': True}, 'tv', 123)
    assert payload['seasons'] == [1]

    payload = build_ai_search_payload({'FILTER_NUM_SEASONS': 3}, 'tv', 123)
    assert payload['seasons'] == [1, 2, 3]

    payload = build_ai_search_payload({}, 'movie', 456)
    assert payload == {'mediaType': 'movie', 'mediaId': 456}


def test_create_seer_client_returns_none_when_unconfigured():
    assert create_seer_client({}, 'secondary') is None


@pytest.mark.asyncio
async def test_submit_direct_seer_request_uses_target_client():
    env = {
        'SEER_API_URL': 'http://primary',
        'SEER_TOKEN': 'p',
        'SECONDARY_SEER_API_URL': 'http://secondary',
        'SECONDARY_SEER_TOKEN': 's',
    }
    mock_client = AsyncMock()
    mock_client.submit_queued_request = AsyncMock(return_value=True)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('api_service.services.seer.seer_config.create_seer_client', return_value=mock_client):
        success = await submit_direct_seer_request(env, 'secondary', 'movie', 99)

    assert success is True
    mock_client.init.assert_awaited_once()
    payload = mock_client.submit_queued_request.await_args.args[0]
    assert payload['mediaType'] == 'movie'
    assert payload['mediaId'] == 99


def test_apply_seer_target_to_payloads_on_approve():
    import sqlite3

    from api_service.db.components.request_queue_mixin import RequestQueueMixin

    class Queue(RequestQueueMixin):
        db_type = 'sqlite'

        def __init__(self, connection):
            self.connection = connection

        def get_connection(self):
            return self.connection

    connection = sqlite3.connect(':memory:')
    connection.executescript("""
        CREATE TABLE pending_requests (
            id INTEGER PRIMARY KEY,
            payload TEXT,
            owner_id INTEGER
        );
        INSERT INTO pending_requests VALUES (1, '{"mediaType":"movie","mediaId":1}', 7);
    """)
    queue = Queue(connection)
    updated = queue._apply_seer_target_to_payloads([1], 7, 'secondary')
    assert updated == 1
    payload = json.loads(connection.execute('SELECT payload FROM pending_requests WHERE id=1').fetchone()[0])
    assert payload['_seer_target'] == 'secondary'
