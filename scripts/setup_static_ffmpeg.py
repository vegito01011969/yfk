from __future__ import annotations

import os
import subprocess
from pathlib import Path

from static_ffmpeg import run


def main() -> int:
    ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
    bin_dir = Path(ffmpeg).parent
    github_path = os.environ.get("GITHUB_PATH")
    if github_path:
        with Path(github_path).open("a", encoding="utf-8") as handle:
            handle.write(f"{bin_dir}\n")
    else:
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"

    subprocess.run([ffmpeg, "-version"], check=True)
    subprocess.run([ffprobe, "-version"], check=True)
    print(f"ffmpeg={ffmpeg}")
    print(f"ffprobe={ffprobe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
