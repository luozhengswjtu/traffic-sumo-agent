from __future__ import annotations

import os
from pathlib import Path


UNC_PREFIX = "\\\\?\\UNC\\"
LOCAL_PREFIX = "\\\\?\\"


def normalize_local_path(path: Path | str) -> Path:
    raw = os.path.abspath(os.fspath(path))
    if raw.startswith(UNC_PREFIX):
        raw = "\\\\" + raw[len(UNC_PREFIX):]
    elif raw.startswith(LOCAL_PREFIX):
        raw = raw[len(LOCAL_PREFIX):]
    return Path(raw)
