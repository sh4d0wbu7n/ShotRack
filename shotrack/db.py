from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


STATUSES = [
    "New",
    "In Progress",
    "Needs Fix",
    "Ready to Edit",
    "Approved",
    "Rejected",
    "Archived",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Scene:
    id: int
    number: int


@dataclass(frozen=True)
class Shot:
    id: int
    scene_id: int
    number: int
    description: str


@dataclass(frozen=True)
class Take:
    id: int
    shot_id: int
    take_number: int
    media_type: str
    original_name: str
    media_path: str
    sidecar_path: str | None
    thumbnail_path: str | None
    stars: int
    status: str
    is_binned: int
    exported_at: str | None
    created_at: str


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scenes (
                id INTEGER PRIMARY KEY,
                number INTEGER NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS shots (
                id INTEGER PRIMARY KEY,
                scene_id INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
                number INTEGER NOT NULL,
                description TEXT NOT NULL,
                UNIQUE(scene_id, number)
            );

            CREATE TABLE IF NOT EXISTS takes (
                id INTEGER PRIMARY KEY,
                shot_id INTEGER NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
                take_number INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                original_name TEXT NOT NULL,
                media_path TEXT NOT NULL,
                sidecar_path TEXT,
                thumbnail_path TEXT,
                stars INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'New',
                is_binned INTEGER NOT NULL DEFAULT 0,
                exported_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(shot_id, take_number)
            );

            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY,
                take_id INTEGER NOT NULL REFERENCES takes(id) ON DELETE CASCADE,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def scenes(self) -> list[Scene]:
        rows = self.conn.execute("SELECT * FROM scenes ORDER BY number").fetchall()
        return [Scene(**dict(row)) for row in rows]

    def shots_for_scene(self, scene_id: int) -> list[Shot]:
        rows = self.conn.execute(
            "SELECT * FROM shots WHERE scene_id = ? ORDER BY number", (scene_id,)
        ).fetchall()
        return [Shot(**dict(row)) for row in rows]

    def shot(self, shot_id: int) -> Shot:
        row = self.conn.execute("SELECT * FROM shots WHERE id = ?", (shot_id,)).fetchone()
        return Shot(**dict(row))

    def scene(self, scene_id: int) -> Scene:
        row = self.conn.execute("SELECT * FROM scenes WHERE id = ?", (scene_id,)).fetchone()
        return Scene(**dict(row))

    def create_scene(self) -> Scene:
        max_number = self.conn.execute("SELECT COALESCE(MAX(number), 0) FROM scenes").fetchone()[0]
        number = max_number + 1
        cur = self.conn.execute("INSERT INTO scenes(number) VALUES (?)", (number,))
        self.conn.commit()
        return Scene(cur.lastrowid, number)

    def create_shot(self, scene_id: int) -> Shot:
        max_number = self.conn.execute(
            "SELECT COALESCE(MAX(number), 0) FROM shots WHERE scene_id = ?", (scene_id,)
        ).fetchone()[0]
        number = max_number + 10
        cur = self.conn.execute(
            "INSERT INTO shots(scene_id, number, description) VALUES (?, ?, ?)",
            (scene_id, number, "untitled"),
        )
        self.conn.commit()
        return Shot(cur.lastrowid, scene_id, number, "untitled")

    def update_scene_number(self, scene_id: int, number: int) -> None:
        self.conn.execute("UPDATE scenes SET number = ? WHERE id = ?", (number, scene_id))
        self.conn.commit()

    def update_shot(self, shot_id: int, number: int, description: str) -> None:
        self.conn.execute(
            "UPDATE shots SET number = ?, description = ? WHERE id = ?",
            (number, description, shot_id),
        )
        self.conn.commit()

    def next_take_number(self, shot_id: int) -> int:
        return (
            self.conn.execute(
                "SELECT COALESCE(MAX(take_number), 0) + 1 FROM takes WHERE shot_id = ?",
                (shot_id,),
            ).fetchone()[0]
        )

    def create_take(
        self,
        shot_id: int,
        take_number: int,
        media_type: str,
        original_name: str,
        media_path: str,
        sidecar_path: str | None,
        thumbnail_path: str | None,
    ) -> Take:
        cur = self.conn.execute(
            """
            INSERT INTO takes(
                shot_id, take_number, media_type, original_name, media_path,
                sidecar_path, thumbnail_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shot_id,
                take_number,
                media_type,
                original_name,
                media_path,
                sidecar_path,
                thumbnail_path,
                now_iso(),
            ),
        )
        self.conn.commit()
        return self.take(cur.lastrowid)

    def takes_for_shot(self, shot_id: int, include_binned: bool = False) -> list[Take]:
        if include_binned:
            rows = self.conn.execute(
                "SELECT * FROM takes WHERE shot_id = ? ORDER BY take_number", (shot_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM takes WHERE shot_id = ? AND is_binned = 0 ORDER BY take_number",
                (shot_id,),
            ).fetchall()
        return [Take(**dict(row)) for row in rows]

    def binned_takes(self) -> list[Take]:
        rows = self.conn.execute(
            "SELECT * FROM takes WHERE is_binned = 1 ORDER BY created_at DESC"
        ).fetchall()
        return [Take(**dict(row)) for row in rows]

    def take(self, take_id: int) -> Take:
        row = self.conn.execute("SELECT * FROM takes WHERE id = ?", (take_id,)).fetchone()
        return Take(**dict(row))

    def update_take_review(self, take_id: int, stars: int, status: str) -> None:
        self.conn.execute(
            "UPDATE takes SET stars = ?, status = ? WHERE id = ?",
            (stars, status, take_id),
        )
        self.conn.commit()

    def update_take_paths(
        self,
        take_id: int,
        media_path: str,
        sidecar_path: str | None,
        thumbnail_path: str | None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE takes
            SET media_path = ?, sidecar_path = ?, thumbnail_path = ?
            WHERE id = ?
            """,
            (media_path, sidecar_path, thumbnail_path, take_id),
        )
        self.conn.commit()

    def set_binned(self, take_id: int, is_binned: bool) -> None:
        self.conn.execute(
            "UPDATE takes SET is_binned = ? WHERE id = ?", (1 if is_binned else 0, take_id)
        )
        self.conn.commit()

    def set_exported(self, take_ids: Iterable[int]) -> None:
        timestamp = now_iso()
        self.conn.executemany(
            "UPDATE takes SET exported_at = ? WHERE id = ?",
            [(timestamp, take_id) for take_id in take_ids],
        )
        self.conn.commit()

    def approved_takes(self) -> list[Take]:
        rows = self.conn.execute(
            "SELECT * FROM takes WHERE status = 'Approved' AND is_binned = 0 ORDER BY id"
        ).fetchall()
        return [Take(**dict(row)) for row in rows]

    def comments(self, take_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM comments WHERE take_id = ? ORDER BY created_at", (take_id,)
        ).fetchall()

    def add_comment(self, take_id: int, body: str) -> None:
        self.conn.execute(
            "INSERT INTO comments(take_id, body, created_at) VALUES (?, ?, ?)",
            (take_id, body, now_iso()),
        )
        self.conn.commit()
