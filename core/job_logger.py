from __future__ import annotations

import json
from typing import Any

from core.db import get_db


def record_job_log(job_name: str, status: str, message: str, payload: dict[str, Any] | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO job_logs (job_name, status, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (
                job_name,
                status,
                message,
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )


def list_job_logs(
    *,
    job_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, job_name, status, message, payload_json, created_at
            FROM job_logs
            WHERE (? IS NULL OR job_name = ?)
              AND (? IS NULL OR status = ?)
            ORDER BY id DESC
            LIMIT ?
            """,
            (job_name, job_name, status, status, limit),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        result.append(item)
    return result
