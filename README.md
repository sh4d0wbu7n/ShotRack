# ShotRack 0.0.6

ShotRack is a local Windows desktop app for managing AI-generated image, video, and audio takes.

## MVP scope

- One local project open at a time.
- Scene / shot / take structure.
- Drag-and-drop import into the selected shot.
- Imported files are copied into the project folder.
- Video + PNG dragged together means the PNG is stored as a workflow sidecar.
- PNG alone is imported as an image take.
- Ratings, statuses, and comment history.
- Per-take model and prompt tracking.
- Project overview boards in PureRef, with explicit per-asset transfer.
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

## PureRef integration

PureRef 2.x must be installed separately at
`C:\Program Files\PureRef\PureRef.exe` to use project boards. ShotRack launches
PureRef as an external application and stores the project board as
`ShotRack Canvas.pur` in the project folder.

ShotRack never adds project assets to PureRef automatically. Assets are sent
only when you use `Add to PureRef` or `Add Selected`.

PureRef is not included in the ShotRack portable package and must not be copied
into a distributed ShotRack package. Every PureRef user is responsible for
installing it separately and holding the license required for their use. See
the [PureRef license agreement](https://www.pureref.com/license.php).

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
dist/ShotRack-0.0.6/
```

## Project format

A ShotRack project folder contains:

```text
project.db
ShotRack Canvas.pur
media/
thumbnails/
exports/approved/
bin/
```
