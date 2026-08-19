from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def main() -> int:
    source_history_path = Path(
        os.environ.get("SOURCE_HISTORY_PATH", "data/source_video_history.json")
    )
    paths_to_remove = [
        Path(os.environ.get("PIPELINE_WORKDIR", "workdir")),
        Path(os.environ.get("PIPELINE_DB_PATH", "data/pipeline.sqlite3")),
    ]

    removed: list[str] = []
    for path in paths_to_remove:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path))
        elif path.exists():
            path.unlink()
            removed.append(str(path))

    source_history_path.parent.mkdir(parents=True, exist_ok=True)
    if not source_history_path.exists():
        source_history_path.write_text(
            json.dumps({"videos": {}, "queries": {}}, indent=2),
            encoding="utf-8",
        )

    print(json.dumps({"removed": removed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
