"""
Вспомогательные утилиты.
"""
import os
import time
from pathlib import Path


def ensure_dir(path: str) -> str:
    """Создать директорию если не существует."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def timestamp() -> str:
    """Текущий timestamp для имён файлов."""
    return time.strftime("%Y%m%d_%H%M%S")


def save_screenshot(data: bytes, directory: str, prefix: str = "screen") -> str:
    """Сохранить скриншот в файл и вернуть путь."""
    ensure_dir(directory)
    filename = f"{prefix}_{timestamp()}.png"
    filepath = os.path.join(directory, filename)
    with open(filepath, "wb") as f:
        f.write(data)
    return filepath
