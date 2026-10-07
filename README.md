# ShotRack 0.0.8

ShotRack is a local Windows desktop app for managing AI-generated image, video, and audio takes.

## MVP scope

- One local project open at a time.
- Scene / shot / take structure.
- Drag-and-drop import into the selected shot.
- Imported files are copied into the project folder.
- Media imports run in the background so large videos do not freeze the app.
- `Ctrl+C` copies the selected take's media file for pasting into Windows Explorer.
- `Ctrl+Shift+C` copies the selected take's absolute media path, adding quotes only for whitespace or shell-special characters.
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
dist/ShotRack-0.0.8/
```

Run `ShotRack-0.0.8.exe` and keep its `_internal` sidecar folder beside it.
Only the small launcher is frozen; the application Python files remain in
`_internal/app/shotrack/`. No single-file executable is built. The script also
creates `dist/ShotRack-0.0.8-windows-portable.zip`. Build dependencies, temporary
files, and output stay inside the repository folder.

## Changes in 0.0.8

- File copy uses an eager Windows `CF_HDROP` file list and an explicit copy effect,
  avoiding Qt's deferred OLE clipboard object when pasting into Explorer.
- Text fields retain their normal `Ctrl+C` text-copy behavior.
- Last-project settings are stored per user at `~/.shotrack_settings.json`, even
  when ShotRack runs from a shared network drive. The shared 0.0.7 settings file
  is left untouched; open a project once to remember it for your user account.
- Newly created projects use `SC0001`, `SC0002`, etc. Existing 0.0.7 projects
  keep `SC001`, `SC002`, etc., including newly added scenes and media paths.
  The format is stored in an additive `project_settings` database table.
- Manual shot numbers accept 1–9999 (`S0005`, `S0011`, etc.). Add Shot continues
  choosing the previous maximum plus 10.
- Invalid saved settings no longer break startup; settings-write failures do
  not prevent a project from opening. Projects cannot close or switch during
  a background media import.
- Scene and shot selections survive tree refreshes. Duplicate shot numbers
  cannot partially save a scene rename. Automatic shot creation reports an
  error instead of creating a number above S9999.

0.0.8 opens and edits 0.0.7 projects without renumbering scenes or changing media
paths on open. Opening newly created 0.0.8 projects with 0.0.7 is unsupported.

Run the regression checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
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
