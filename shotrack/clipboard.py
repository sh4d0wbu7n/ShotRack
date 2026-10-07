"""Eager Windows file clipboard data, independent of Qt's OLE data object."""
from __future__ import annotations

import ctypes
import struct
import sys
import time
from ctypes import wintypes
from pathlib import Path


def file_drop_data(paths: list[Path]) -> bytes:
    if not paths:
        raise ValueError("Select at least one file to copy.")
    names = [str(path.absolute()) for path in paths]
    if any("\0" in name for name in names):
        raise ValueError("File paths cannot contain null characters.")
    # DROPFILES: byte offset, POINT, non-client flag, Unicode flag.
    return struct.pack("<IiiII", 20, 0, 0, 0, 1) + (
        "\0".join(names) + "\0\0"
    ).encode("utf-16-le")


def copy_files(paths: list[Path], owner: int) -> None:
    if sys.platform != "win32":
        raise OSError("Native file copying requires Windows.")
    if not owner:
        raise ValueError("A clipboard owner window is required.")
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    preferred = user32.RegisterClipboardFormatW("Preferred DropEffect")
    if not preferred:
        raise ctypes.WinError(ctypes.get_last_error())
    payloads = [(15, file_drop_data(paths)), (preferred, struct.pack("<I", 1))]
    handles = []
    opened = False
    try:
        # Allocate before clearing the clipboard. Windows owns successful transfers.
        for format_id, payload in payloads:
            handle = kernel32.GlobalAlloc(0x0002, len(payload))  # GMEM_MOVEABLE
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append([format_id, handle])
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                ctypes.memmove(pointer, payload, len(payload))
            finally:
                kernel32.GlobalUnlock(handle)
        for attempt in range(10):
            if user32.OpenClipboard(owner):
                opened = True
                break
            time.sleep(0.01)
        if not opened or not user32.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        for entry in handles:
            if not user32.SetClipboardData(entry[0], entry[1]):
                raise ctypes.WinError(ctypes.get_last_error())
            entry[1] = None
    finally:
        if opened:
            user32.CloseClipboard()
        for _, handle in handles:
            if handle:
                kernel32.GlobalFree(handle)
