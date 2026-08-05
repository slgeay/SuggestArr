"""
Seer Queue Worker — drains the pending_requests table with retry + exponential backoff.

Registered in app.py as a fixed-interval APScheduler job (every 2 minutes,
max_instances=1 to prevent overlap).
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from api_service.config.logger_manager import LoggerManager
from api_service.services.config_service import ConfigService
from api_service.db.database_manager import DatabaseManager
from api_service.services.seer.seer_config import create_seer_client, normalize_seer_target
from api_service.utils.asyncio_loop import close_event_loop

MAX_RETRIES = 5
WORKER_BATCH = 50

logger = LoggerManager.get_logger("QueueWorker")


def _backoff_seconds(retry_count: int) -> int:
    """Exponential backoff: 30 s → 60 s → 120 s → 240 s → 480 s (capped at 1 h)."""
    return min(30 * (2 ** retry_count), 3600)


def _next_attempt_at(retry_count: int) -> datetime:
    """Return a UTC datetime offset by the backoff for *retry_count*."""
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=_backoff_seconds(retry_count))


async def _process_items(db, env, items, clients) -> int:
    """Submit queued rows using the configured Seer clients."""
    submitted = 0

    for item in items:
        row_id = item['id']
        tmdb_id = item['tmdb_id']
        media_type = item['media_type']
        retry_count = item['retry_count']
        try:
            payload = json.loads(item['payload'])
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error(
                "Queue worker: corrupt payload for %s tmdb:%s (row %s) — %s. Marking as failed.",
                media_type, tmdb_id, row_id, exc,
            )
            db.mark_pending_failed(row_id, retry_count, "Corrupt queued payload")
            continue

        target = normalize_seer_target(payload.get('_seer_target'))
        seer = clients.get(target) or clients.get('primary')
        if seer is None:
            db.mark_pending_failed(
                row_id,
                retry_count,
                f"Seer target '{target}' is not configured",
            )
            continue

        if db.check_request_exists(media_type, tmdb_id):
            logger.debug("Queue worker: %s tmdb:%s already in requests, marking submitted.", media_type, tmdb_id)
            db.mark_pending_submitted(row_id, retry_count)
            continue

        db.mark_pending_submitting(row_id, retry_count)

        try:
            success = await seer.submit_queued_request(payload)
        except Exception as exc:
            logger.error(
                "Queue worker: unexpected error submitting %s tmdb:%s — %s",
                media_type, tmdb_id, exc, exc_info=True,
            )
            success = False

        if success:
            db.save_request(
                media_type,
                tmdb_id,
                payload.get('_source_id'),
                payload.get('_user_id'),
                is_anime=bool(payload.get('_is_anime', False)),
                rationale=payload.get('_rationale'),
                source_origin=payload.get('_source_origin'),
            )
            db.mark_pending_submitted(row_id, retry_count)
            logger.info("Queue worker: submitted %s tmdb:%s via %s Seer.", media_type, tmdb_id, target)
            submitted += 1
            continue

        new_retry = retry_count + 1
        if new_retry >= MAX_RETRIES:
            db.mark_pending_failed(row_id, new_retry, "Seer rejected the request after maximum retries")
            logger.error(
                "Queue worker: %s tmdb:%s permanently failed after %d retries.",
                media_type, tmdb_id, new_retry,
            )
        else:
            next_at = _next_attempt_at(new_retry)
            db.increment_pending_retry(row_id, new_retry, next_at)
            logger.warning(
                "Queue worker: %s tmdb:%s retry %d scheduled at %s.",
                media_type, tmdb_id, new_retry, next_at,
            )

    return submitted


async def _run_worker() -> int:
    """Core async drain loop."""
    db = DatabaseManager()
    env = ConfigService.get_runtime_config()

    expired = db.expire_pending_approvals(int(env.get('AUTO_REJECT_APPROVAL_DAYS') or 0))
    if expired:
        logger.info("Queue worker: automatically rejected %d expired approval(s).", expired)

    db.reset_stale_inflight(cutoff_minutes=10)

    items = db.get_due_requests(max_items=WORKER_BATCH)
    if not items:
        logger.debug("Queue worker: nothing to process.")
        return 0

    logger.info("Queue worker: processing %d item(s).", len(items))

    primary = create_seer_client(env, 'primary')
    if primary is None:
        logger.error("Queue worker: primary Seer is not configured.")
        return 0

    secondary = create_seer_client(env, 'secondary')
    async with primary:
        await primary.init()
        clients = {'primary': primary}
        if secondary is not None:
            async with secondary:
                await secondary.init()
                clients['secondary'] = secondary
                return await _process_items(db, env, items, clients)
        return await _process_items(db, env, items, clients)


def run_queue_worker() -> None:
    """Synchronous entry point called by APScheduler."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        submitted = loop.run_until_complete(_run_worker())
        if submitted:
            logger.info("Queue worker cycle complete: %d submission(s).", submitted)
    except Exception as e:
        logger.error("Queue worker cycle failed: %s", e, exc_info=True)
    finally:
        close_event_loop(loop, logger)
