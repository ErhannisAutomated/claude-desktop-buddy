# PlatformIO extra-script: stage the default character pack into data/ so that
# `pio run -t uploadfs` (or buildfs) always bundles a character, so no separate
# flash_character.py needed. Only runs for filesystem targets, not normal builds.
Import("env")
import shutil
from pathlib import Path
from SCons.Script import COMMAND_LINE_TARGETS

CHARACTER = "bufo"

proj = Path(env["PROJECT_DIR"])
src  = proj / "characters" / CHARACTER
dst  = proj / "data" / "characters" / CHARACTER

if any(t in COMMAND_LINE_TARGETS for t in ("buildfs", "uploadfs")):
    if not src.exists():
        print(f"[prep_fs] WARNING: characters/{CHARACTER} not found, FS will be empty")
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"[prep_fs] staged characters/{CHARACTER} -> data/characters/{CHARACTER}")
