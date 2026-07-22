from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .db import Database, Shot, Take
from .utils import (
    ensure_unique_path,
    is_png,
    is_video,
    media_kind,
    project_path,
    relative_to_project,
    scene_code,
    shot_code,
    snake_case,
    take_code,
)


THUMB_SIZE = (320, 180)


def ensure_project_dirs(root: Path) -> None:
    for name in ["media", "thumbnails", "exports/approved", "bin"]:
        (root / name).mkdir(parents=True, exist_ok=True)


def shot_folder(root: Path, scene_number: int, shot_number: int) -> Path:
    return root / "media" / scene_code(scene_number) / shot_code(shot_number)


def thumb_folder(root: Path, scene_number: int, shot_number: int) -> Path:
    return root / "thumbnails" / scene_code(scene_number) / shot_code(shot_number)


def base_take_name(scene_number: int, shot_number: int, description: str, take_number: int) -> str:
    return (
        f"{scene_code(scene_number)}_"
        f"{shot_code(shot_number)}_"
        f"{snake_case(description)}_"
        f"{take_code(take_number)}"
    )


def import_take(
    db: Database,
    root: Path,
    shot: Shot,
    scene_number: int,
    paths: list[Path],
    model: str = "",
    prompt: str = "",
) -> Take:
    ensure_project_dirs(root)
    videos = [path for path in paths if is_video(path)]
    pngs = [path for path in paths if is_png(path)]
    if len(paths) == 2 and len(videos) == 1 and len(pngs) == 1:
        media_source = videos[0]
        sidecar_source = pngs[0]
    elif len(paths) == 1:
        media_source = paths[0]
        sidecar_source = None
    else:
        raise ValueError("Drag one media file, or one video plus one PNG workflow sidecar.")

    take_number = db.next_take_number(shot.id)
    base = base_take_name(scene_number, shot.number, shot.description, take_number)
    destination_dir = shot_folder(root, scene_number, shot.number)
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = ensure_unique_path(destination_dir / f"{base}{media_source.suffix.lower()}")
    shutil.copy2(media_source, target)

    sidecar_target = None
    if sidecar_source is not None:
        sidecar_target = ensure_unique_path(destination_dir / f"{base}_workflow.png")
        shutil.copy2(sidecar_source, sidecar_target)

    thumb_dir = thumb_folder(root, scene_number, shot.number)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_target = thumb_dir / f"{base}.jpg"
    create_thumbnail(target, thumb_target)

    return db.create_take(
        shot_id=shot.id,
        take_number=take_number,
        media_type=media_kind(target),
        original_name=media_source.name,
        media_path=relative_to_project(root, target) or "",
        sidecar_path=relative_to_project(root, sidecar_target),
        thumbnail_path=relative_to_project(root, thumb_target) if thumb_target.exists() else None,
        model=model,
        prompt=prompt,
    )


def create_thumbnail(media_path: Path, thumb_path: Path) -> None:
    kind = media_kind(media_path)
    try:
        if kind == "image":
            with Image.open(media_path) as image:
                image.thumbnail(THUMB_SIZE)
                canvas = Image.new("RGB", THUMB_SIZE, "#20242b")
                x = (THUMB_SIZE[0] - image.width) // 2
                y = (THUMB_SIZE[1] - image.height) // 2
                canvas.paste(image.convert("RGB"), (x, y))
                canvas.save(thumb_path, "JPEG", quality=88)
            return
        if kind == "video" and ffmpeg_thumbnail(media_path, thumb_path):
            return
        draw_placeholder(thumb_path, kind.upper(), media_path.suffix.lower())
    except Exception:
        draw_placeholder(thumb_path, kind.upper(), media_path.suffix.lower())


def ffmpeg_thumbnail(media_path: Path, thumb_path: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(media_path),
        "-vf",
        "thumbnail,scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
        "-frames:v",
        "1",
        str(thumb_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    return result.returncode == 0 and thumb_path.exists()


def draw_placeholder(thumb_path: Path, label: str, suffix: str) -> None:
    image = Image.new("RGB", THUMB_SIZE, "#2b3038")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, THUMB_SIZE[0] - 1, THUMB_SIZE[1] - 1), outline="#5b6472")
    draw.text((18, 72), label, fill="#f1f3f5")
    draw.text((18, 98), suffix or "file", fill="#aab2bf")
    image.save(thumb_path, "JPEG", quality=88)


def rebuild_take_paths(db: Database, root: Path, shot: Shot, scene_number: int) -> None:
    media_dir = shot_folder(root, scene_number, shot.number)
    thumbs_dir = thumb_folder(root, scene_number, shot.number)
    media_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    for take in db.takes_for_shot(shot.id, include_binned=False):
        media = project_path(root, take.media_path)
        sidecar = project_path(root, take.sidecar_path)
        thumb = project_path(root, take.thumbnail_path)
        base = base_take_name(scene_number, shot.number, shot.description, take.take_number)

        new_media = media_dir / f"{base}{media.suffix.lower()}" if media else None
        new_sidecar = media_dir / f"{base}_workflow.png" if sidecar else None
        new_thumb = thumbs_dir / f"{base}.jpg" if thumb else None

        if media and media.exists() and new_media and media.resolve() != new_media.resolve():
            new_media.parent.mkdir(parents=True, exist_ok=True)
            media.rename(new_media)
        if sidecar and sidecar.exists() and new_sidecar and sidecar.resolve() != new_sidecar.resolve():
            new_sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.rename(new_sidecar)
        if thumb and thumb.exists() and new_thumb and thumb.resolve() != new_thumb.resolve():
            new_thumb.parent.mkdir(parents=True, exist_ok=True)
            thumb.rename(new_thumb)

        db.update_take_paths(
            take.id,
            relative_to_project(root, new_media) or take.media_path,
            relative_to_project(root, new_sidecar),
            relative_to_project(root, new_thumb),
        )


def delete_take_files_and_record(db: Database, root: Path, take: Take) -> None:
    delete_take_files(root, take)
    db.delete_take(take.id)


def delete_shot_files_and_record(db: Database, root: Path, shot: Shot, scene_number: int) -> None:
    for take in db.takes_for_shot(shot.id, include_binned=True):
        delete_take_files(root, take)
    shutil.rmtree(shot_folder(root, scene_number, shot.number), ignore_errors=True)
    shutil.rmtree(thumb_folder(root, scene_number, shot.number), ignore_errors=True)
    db.delete_shot(shot.id)


def delete_scene_files_and_record(db: Database, root: Path, scene_id: int) -> None:
    scene = db.scene(scene_id)
    for take in db.takes_for_scene(scene_id, include_binned=True):
        delete_take_files(root, take)
    shutil.rmtree(root / "media" / scene_code(scene.number), ignore_errors=True)
    shutil.rmtree(root / "thumbnails" / scene_code(scene.number), ignore_errors=True)
    db.delete_scene(scene_id)


def delete_take_files(root: Path, take: Take) -> None:
    for path in [
        project_path(root, take.media_path),
        project_path(root, take.sidecar_path),
        project_path(root, take.thumbnail_path),
    ]:
        if path and path.exists() and path.is_file():
            path.unlink()


def move_take_to_bin(db: Database, root: Path, take: Take) -> None:
    move_take_between_roots(db, root, take, "bin")
    db.set_binned(take.id, True)


def restore_take_from_bin(db: Database, root: Path, take: Take) -> None:
    shot = db.shot(take.shot_id)
    scene = db.scene(shot.scene_id)
    base = base_take_name(scene.number, shot.number, shot.description, take.take_number)
    media = project_path(root, take.media_path)
    sidecar = project_path(root, take.sidecar_path)
    thumb = project_path(root, take.thumbnail_path)
    media_dir = shot_folder(root, scene.number, shot.number)
    thumb_dir = thumb_folder(root, scene.number, shot.number)
    media_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)

    new_media = media_dir / f"{base}{media.suffix.lower()}" if media else None
    new_sidecar = media_dir / f"{base}_workflow.png" if sidecar else None
    new_thumb = thumb_dir / f"{base}.jpg" if thumb else None

    if media and media.exists() and new_media:
        new_media = ensure_unique_path(new_media)
        media.rename(new_media)
    if sidecar and sidecar.exists() and new_sidecar:
        new_sidecar = ensure_unique_path(new_sidecar)
        sidecar.rename(new_sidecar)
    if thumb and thumb.exists() and new_thumb:
        new_thumb = ensure_unique_path(new_thumb)
        thumb.rename(new_thumb)

    db.update_take_paths(
        take.id,
        relative_to_project(root, new_media) or take.media_path,
        relative_to_project(root, new_sidecar),
        relative_to_project(root, new_thumb),
    )
    db.set_binned(take.id, False)


def move_take_between_roots(db: Database, root: Path, take: Take, target_root_name: str) -> None:
    media = project_path(root, take.media_path)
    sidecar = project_path(root, take.sidecar_path)
    thumb = project_path(root, take.thumbnail_path)
    shot = db.shot(take.shot_id)
    scene = db.scene(shot.scene_id)
    target_dir = root / target_root_name / scene_code(scene.number) / shot_code(shot.number)
    target_dir.mkdir(parents=True, exist_ok=True)

    def move_one(path: Path | None) -> Path | None:
        if path is None or not path.exists():
            return None
        target = ensure_unique_path(target_dir / path.name)
        path.rename(target)
        return target

    new_media = move_one(media)
    new_sidecar = move_one(sidecar)
    new_thumb = move_one(thumb)
    db.update_take_paths(
        take.id,
        relative_to_project(root, new_media) or take.media_path,
        relative_to_project(root, new_sidecar),
        relative_to_project(root, new_thumb),
    )


def export_approved(db: Database, root: Path, conflict_mode: str) -> int:
    export_dir = root / "exports" / "approved"
    export_dir.mkdir(parents=True, exist_ok=True)
    exported: list[int] = []
    for take in db.approved_takes():
        media = project_path(root, take.media_path)
        if not media or not media.exists():
            continue
        destination = export_dir / f"{media.stem}_Approved{media.suffix.lower()}"
        final_destination = resolve_export_conflict(destination, conflict_mode)
        if final_destination is not None:
            shutil.copy2(media, final_destination)
            exported.append(take.id)
        if take.sidecar_path:
            sidecar = project_path(root, take.sidecar_path)
            if sidecar and sidecar.exists():
                sidecar_destination = export_dir / sidecar.name
                final_sidecar = resolve_export_conflict(sidecar_destination, conflict_mode)
                if final_sidecar is not None:
                    shutil.copy2(sidecar, final_sidecar)
    db.set_exported(exported)
    return len(exported)


def resolve_export_conflict(destination: Path, conflict_mode: str) -> Path | None:
    if not destination.exists():
        return destination
    if conflict_mode == "overwrite":
        return destination
    if conflict_mode == "skip":
        return None
    if conflict_mode == "rename":
        return ensure_unique_path(destination)
    raise ValueError("Export canceled due to file conflict.")
