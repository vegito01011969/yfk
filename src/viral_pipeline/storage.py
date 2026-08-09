from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from viral_pipeline.domain import PipelineContext, RunStatus, StageName, StageStatus, utc_now


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value)!r}")


def encode_model(model: BaseModel) -> str:
    return model.model_dump_json()


def encode_value(value: Any) -> str:
    return json.dumps(value, default=_json_default)


class PipelineStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self.init()

    def close(self) -> None:
        self._conn.close()

    def init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                workdir TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS stage_runs (
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                error TEXT,
                PRIMARY KEY (run_id, stage),
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                run_id TEXT NOT NULL,
                name TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, name),
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );
            """
        )
        self._conn.commit()

    def create_run(self, run_id: str, workdir: Path, stages: Iterable[StageName]) -> None:
        now = utc_now().isoformat()
        self._conn.execute(
            "INSERT INTO runs (id, status, workdir, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, RunStatus.CREATED.value, str(workdir), now, now),
        )
        self._conn.executemany(
            "INSERT INTO stage_runs (run_id, stage, status) VALUES (?, ?, ?)",
            [(run_id, stage.value, StageStatus.PENDING.value) for stage in stages],
        )
        self._conn.commit()

    def update_run(self, run_id: str, status: RunStatus, error: str | None = None) -> None:
        self._conn.execute(
            "UPDATE runs SET status = ?, updated_at = ?, error = ? WHERE id = ?",
            (status.value, utc_now().isoformat(), error, run_id),
        )
        self._conn.commit()

    def start_stage(self, run_id: str, stage: StageName) -> None:
        self._conn.execute(
            """
            UPDATE stage_runs
            SET status = ?, started_at = COALESCE(started_at, ?), error = NULL
            WHERE run_id = ? AND stage = ?
            """,
            (StageStatus.RUNNING.value, utc_now().isoformat(), run_id, stage.value),
        )
        self._conn.commit()

    def complete_stage(self, run_id: str, stage: StageName) -> None:
        self._conn.execute(
            """
            UPDATE stage_runs
            SET status = ?, completed_at = ?, error = NULL
            WHERE run_id = ? AND stage = ?
            """,
            (StageStatus.COMPLETE.value, utc_now().isoformat(), run_id, stage.value),
        )
        self._conn.commit()

    def fail_stage(self, run_id: str, stage: StageName, error: str) -> None:
        self._conn.execute(
            """
            UPDATE stage_runs
            SET status = ?, completed_at = ?, error = ?
            WHERE run_id = ? AND stage = ?
            """,
            (StageStatus.FAILED.value, utc_now().isoformat(), error, run_id, stage.value),
        )
        self._conn.commit()

    def save_artifact(self, run_id: str, name: str, value: Any) -> None:
        payload = encode_model(value) if isinstance(value, BaseModel) else encode_value(value)
        self._conn.execute(
            """
            INSERT INTO artifacts (run_id, name, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id, name)
            DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
            """,
            (run_id, name, payload, utc_now().isoformat()),
        )
        self._conn.commit()

    def load_artifact(self, run_id: str, name: str) -> Any | None:
        row = self._conn.execute(
            "SELECT payload FROM artifacts WHERE run_id = ? AND name = ?", (run_id, name)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_context(self, context: PipelineContext) -> None:
        self.save_artifact(context.run_id, "context", context)

    def load_context(self, run_id: str) -> PipelineContext:
        payload = self.load_artifact(run_id, "context")
        if payload is not None:
            return PipelineContext.model_validate(payload)
        row = self.get_run(run_id)
        if row is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return PipelineContext(run_id=run_id, workdir=Path(row["workdir"]))

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

    def latest_run_id(self) -> str | None:
        row = self._conn.execute(
            "SELECT id FROM runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return str(row["id"]) if row else None

    def list_runs(self) -> list[sqlite3.Row]:
        return list(self._conn.execute("SELECT * FROM runs ORDER BY created_at DESC"))

    def list_stage_runs(self, run_id: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM stage_runs WHERE run_id = ? ORDER BY rowid ASC", (run_id,)
            )
        )

    def completed_stages(self, run_id: str) -> set[StageName]:
        rows = self._conn.execute(
            "SELECT stage FROM stage_runs WHERE run_id = ? AND status = ?",
            (run_id, StageStatus.COMPLETE.value),
        ).fetchall()
        return {StageName(row["stage"]) for row in rows}
