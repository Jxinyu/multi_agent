from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from config import settings


def test_alembic_upgrades_empty_database_to_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "migration.db"
    monkeypatch.setattr(settings.database, "url", f"sqlite+aiosqlite:///{database_path}")

    command.upgrade(Config("alembic.ini"), "head")

    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        message_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(conversation_messages)")
        }
        feedback_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(conversation_feedback)")
        }
        feedback_foreign_keys = {
            (row[3], row[2], row[4])
            for row in connection.execute("PRAGMA foreign_key_list(conversation_feedback)")
        }

    assert revision == ("20260902_0003",)
    assert "message_id" not in message_columns
    assert "message_id" in feedback_columns
    assert ("message_id", "conversation_messages", "id") in feedback_foreign_keys
