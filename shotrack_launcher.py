"""Small portable bootstrap; application source remains in the sidecar folder."""
import runpy
import sys
from pathlib import Path


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(sys._MEIPASS) / "app"))
    runpy.run_module("shotrack", run_name="__main__")
