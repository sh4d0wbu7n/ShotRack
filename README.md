# ShotRack 0.0.4

ShotRack is a local Windows desktop app for managing AI-generated image, video, and audio takes.

## MVP scope

- One local project open at a time.
- Scene / shot / take structure.
- Drag-and-drop import into the selected shot.
- Imported files are copied into the project folder.
- Video + PNG dragged together means the PNG is stored as a workflow sidecar.
- PNG alone is imported as an image take.
- Ratings, statuses, and comment history.
- Move to project bin and restore.
- Export approved takes to one flat export folder.

## Setup

Create a venv and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
```

If `python` is not on PATH, replace `python` with the full path to your Python 3.13 executable.

## Run

```powershell
.\.venv\Scripts\python.exe -m shotrack
```

## Portable build

```powershell
.\build_portable.ps1
```

The portable app is written to:

```text
dist/ShotRack-0.0.4/
```

## Project format

A ShotRack project folder contains:

```text
project.db
media/
thumbnails/
exports/approved/
bin/
```
