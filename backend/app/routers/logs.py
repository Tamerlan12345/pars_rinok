"""Logs router — audit log query and SSE stream."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.routers.auth import get_current_user, verify_access_token
from app.services.logger_service import get_recent_logs

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/recent")
async def recent_logs(
    limit: int = Query(50, ge=1, le=500),
    level: str = Query("ALL"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> list[dict]:
    logs = await get_recent_logs(db, limit=limit, level_filter=level)
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat() + "Z",
            "level": log.level,
            "event": log.event,
            "message": log.message,
            "context": log.context,
            "request_id": log.request_id,
            "ip_address": log.ip_address,
        }
        for log in logs
    ]


@router.get("/stream")
async def stream_logs(token: str = Query(...)) -> StreamingResponse:
    """
    Server-Sent Events stream of new audit log entries.
    Polls DB every 3 seconds, emits new entries since last seen ID.
    EventSource cannot send Authorization headers, so the browser passes a JWT
    query token that is validated before the stream opens.
    """
    verify_access_token(token)

    async def event_generator():
        last_id = 0
        # Bootstrap: get current max id
        async with AsyncSessionLocal() as session:
            logs = await get_recent_logs(session, limit=1)
            if logs:
                last_id = logs[0].id

        while True:
            await asyncio.sleep(3)
            try:
                async with AsyncSessionLocal() as session:
                    from sqlalchemy import select
                    from app.models.audit_log import AuditLog
                    result = await session.execute(
                        select(AuditLog)
                        .where(AuditLog.id > last_id)
                        .order_by(AuditLog.id)
                        .limit(20)
                    )
                    new_logs = result.scalars().all()

                for log in new_logs:
                    last_id = max(last_id, log.id)
                    data = json.dumps({
                        "id": log.id,
                        "timestamp": log.timestamp.isoformat() + "Z",
                        "level": log.level,
                        "event": log.event,
                        "message": log.message,
                        "context": log.context,
                    })
                    yield f"data: {data}\n\n"

                # Keep-alive ping every cycle
                yield f": ping {datetime.utcnow().isoformat()}\n\n"

            except asyncio.CancelledError:
                break
            except Exception:
                yield ": error\n\n"
                await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
