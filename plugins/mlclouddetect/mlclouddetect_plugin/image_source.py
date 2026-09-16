from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path


class ImageSourceError(RuntimeError):
    """Raised when the latest all-sky image cannot be located."""


class ImageSource(ABC):
    @abstractmethod
    def latest_image_path(self) -> Path: ...


class FileImageSource(ImageSource):
    """Reads a single, continuously-overwritten "latest image" file path."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def latest_image_path(self) -> Path:
        if not self._path.is_file():
            raise ImageSourceError(f"configured allsky_file does not exist: {self._path}")
        return self._path


class IndiAllskyDbImageSource(ImageSource):
    """Reads the most recent frame for a camera from an indi-allsky SQLite database.

    Schema per https://github.com/aaronwmorris/indi-allsky: an `image` table with
    `filename` and `createDate` columns, joined to a `camera` table via `camera_id`.
    """

    _QUERY = (
        "SELECT image.filename AS filename FROM image "
        "JOIN camera ON camera.id = image.camera_id "
        "WHERE camera.id = ? "
        "ORDER BY image.createDate DESC LIMIT 1"
    )

    def __init__(self, db_path: str, camera_id: int, image_root: str) -> None:
        self._db_path = Path(db_path)
        self._camera_id = camera_id
        self._image_root = Path(image_root)

    def latest_image_path(self) -> Path:
        if not self._db_path.is_file():
            raise ImageSourceError(f"indi-allsky database not found: {self._db_path}")

        try:
            connection = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
            try:
                cursor = connection.execute(self._QUERY, (self._camera_id,))
                row = cursor.fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise ImageSourceError(f"indi-allsky database query failed: {exc}") from exc

        if row is None:
            raise ImageSourceError(
                f"no images found in indi-allsky database for camera_id={self._camera_id}"
            )

        image_path = self._image_root / row[0]
        if not image_path.is_file():
            raise ImageSourceError(f"latest indi-allsky image does not exist on disk: {image_path}")
        return image_path
