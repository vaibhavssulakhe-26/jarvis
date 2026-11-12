"""Reading and writing the small JSON files under data/ in one place."""
import json
import os
import threading


def read(path, default=None, kind=None):
    """The parsed file, or `default` when it is missing, damaged, or not of type `kind` (dict or list)."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return default
    return data if kind is None or isinstance(data, kind) else default


def write(path, data, indent=None):
    """Write the file by replacing it in one step, so a reader never sees half a file. Creates the folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=indent))
    os.replace(tmp, path)
