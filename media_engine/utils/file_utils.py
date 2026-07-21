import os
import uuid
import shutil
from .. import config


def make_temp_path(suffix: str = ".mp4") -> str:
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    return os.path.join(config.TEMP_DIR, f"me_{uuid.uuid4().hex}{suffix}")


def make_output_path(suffix: str = ".mp4") -> str:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    return os.path.join(config.OUTPUT_DIR, f"output_{uuid.uuid4().hex}{suffix}")


def remove_files(*paths: str) -> None:
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def remove_dir(path: str) -> None:
    try:
        if path and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
