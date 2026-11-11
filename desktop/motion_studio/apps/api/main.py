from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "storage"
DEFAULT_COMFYUI_ROOT = Path.home() / "ComfyUI"
DEFAULT_FFMPEG = Path(shutil.which("ffmpeg") or "ffmpeg")
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not parsed.port
        ):
            raise ValueError
    except ValueError:
        raise ValueError("ComfyUI endpoint must be a loopback URL with a port.") from None
    return value.rstrip("/")


class Clip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: str = Field(pattern=r"^(video|image|audio|text)$")
    name: str = Field(min_length=1, max_length=160)
    start_frame: int = Field(ge=0, le=432000)
    duration_frames: int = Field(ge=1, le=432000)
    text: str | None = Field(default=None, max_length=2000)
    style: dict[str, Any] = Field(default_factory=dict)


class Track(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern=r"^(video|image|audio|text)$")
    clips: list[Clip] = Field(default_factory=list, max_length=256)


class PlannedScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene: int = Field(ge=1, le=64)
    title: str = Field(max_length=120)
    prompt: str = Field(max_length=1024)
    image_prompt: str = Field(default="", max_length=1024)
    hook: str = Field(default="", max_length=250)
    cliffhanger: str = Field(default="", max_length=250)
    speaker: str = Field(default="", max_length=64)
    dialogue: str = Field(default="", max_length=300)


class VisualReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: Literal["character", "setting"]
    name: str = Field(min_length=1, max_length=160)
    prompt: str = Field(max_length=4096)
    source: Literal["generated_brief", "generated_image", "upload"]
    image_data: str | None = Field(default=None, max_length=8_500_000)
    scene_number: int | None = Field(default=None, ge=1, le=64)


class Publication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cover_text: str = Field(default="", max_length=120)
    caption: str = Field(default="", max_length=2200)
    hashtags: str = Field(default="", max_length=500)


class Storyboard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: str = Field(max_length=2000)
    visual_bible: str = Field(default="", max_length=2000)
    scenes: list[PlannedScene] = Field(default_factory=list, max_length=64)
    references: list[VisualReference] = Field(default_factory=list, max_length=32)
    episode_status: Literal["draft", "approved"] = "draft"
    publication: Publication | None = None
    voice_profiles: dict[str, str] = Field(default_factory=dict, max_length=12)


class Timeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=1)
    fps: int = Field(default=24, ge=12, le=60)
    width: int = Field(default=1280, ge=320, le=3840)
    height: int = Field(default=720, ge=320, le=3840)
    tracks: list[Track] = Field(default_factory=list, max_length=32)
    storyboard: Storyboard | None = None


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=2000)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=2000)
    timeline: Timeline


def connect(database: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def initialize(database: Path) -> None:
    with closing(connect(database)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                timeline_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def serialize(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "timeline": json.loads(row["timeline_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_app(
    database: Path | None = None,
    comfy_url: str | None = None,
    comfy_root: Path | None = None,
    ffmpeg_path: Path | None = None,
) -> FastAPI:
    data_dir = Path(os.environ.get("MOTION_STUDIO_DATA", DEFAULT_DATA))
    db_path = database or data_dir / "ai-motion-studio.sqlite3"
    endpoint = local_endpoint(
        comfy_url or os.environ.get("MOTION_STUDIO_COMFYUI_URL", "http://127.0.0.1:8188")
    )
    model_root = Path(os.environ.get("MOTION_STUDIO_COMFYUI_ROOT", comfy_root or DEFAULT_COMFYUI_ROOT))
    ffmpeg = Path(os.environ.get("MOTION_STUDIO_FFMPEG", ffmpeg_path or DEFAULT_FFMPEG))
    initialize(db_path)

    app = FastAPI(title="AI Motion Studio API", version="0.1.0")
    app.state.database = db_path
    app.state.comfy_url = endpoint
    app.state.comfy_root = model_root
    app.state.ffmpeg_path = ffmpeg
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5174", "http://localhost:5174"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "database": "ready"}

    @app.get("/api/capabilities")
    async def capabilities() -> dict:
        comfy_status = "unavailable"
        try:
            async with httpx.AsyncClient(
                timeout=1.5, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.get(f"{endpoint}/system_stats")
                if response.status_code == 200 and isinstance(response.json(), dict):
                    comfy_status = "available"
                else:
                    comfy_status = "error"
        except (httpx.HTTPError, ValueError):
            pass
        return {
            "comfyui": {
                "installed": (model_root / "main.py").is_file(),
                "endpoint_configured": True,
                "status": comfy_status,
            },
            "wan21_t2v_13b": {
                "installed": (model_root / "models" / "diffusion_models" / "wan2.1_t2v_1.3B_fp16.safetensors").is_file(),
            },
            "ffmpeg": {"installed": ffmpeg.is_file(), "path_configured": str(ffmpeg)},
            "rendering": {"status": "not_implemented"},
            "transcription": {"status": "not_implemented"},
        }

    @app.get("/api/projects")
    def list_projects() -> list[dict]:
        with closing(connect(db_path)) as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC, id"
            ).fetchall()
        return [serialize(row) for row in rows]

    @app.post("/api/projects", status_code=201)
    def create_project(data: ProjectCreate) -> dict:
        project_id = uuid.uuid4().hex
        timestamp = now()
        timeline = Timeline().model_dump(mode="json")
        with closing(connect(db_path)) as connection:
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    data.title.strip(),
                    data.summary.strip(),
                    json.dumps(timeline, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        return serialize(row)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        if not ID_PATTERN.fullmatch(project_id):
            raise HTTPException(404, "Project not found.")
        with closing(connect(db_path)) as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Project not found.")
        return serialize(row)

    @app.put("/api/projects/{project_id}")
    def update_project(project_id: str, data: ProjectUpdate) -> dict:
        if not ID_PATTERN.fullmatch(project_id):
            raise HTTPException(404, "Project not found.")
        track_ids = [track.id for track in data.timeline.tracks]
        clip_ids = [clip.id for track in data.timeline.tracks for clip in track.clips]
        if len(track_ids) != len(set(track_ids)) or len(clip_ids) != len(set(clip_ids)):
            raise HTTPException(422, "Track and clip identifiers must be unique.")
        for track in data.timeline.tracks:
            if any(clip.kind != track.kind for clip in track.clips):
                raise HTTPException(422, "Clip kind must match its track kind.")
        timestamp = now()
        with closing(connect(db_path)) as connection:
            cursor = connection.execute(
                """
                UPDATE projects
                SET title=?, summary=?, timeline_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    data.title.strip(),
                    data.summary.strip(),
                    data.timeline.model_dump_json(),
                    timestamp,
                    project_id,
                ),
            )
            connection.commit()
            if cursor.rowcount != 1:
                raise HTTPException(404, "Project not found.")
            row = connection.execute(
                "SELECT * FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        return serialize(row)

    return app


app = create_app()
