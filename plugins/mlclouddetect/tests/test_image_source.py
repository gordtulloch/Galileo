import sqlite3
import tempfile
import unittest
from pathlib import Path

from mlclouddetect_plugin.image_source import (
    FileImageSource,
    ImageSourceError,
    IndiAllskyDbImageSource,
)


class FileImageSourceTests(unittest.TestCase):
    def test_returns_path_when_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "latest.jpg"
            image_path.write_bytes(b"fake-jpeg-bytes")

            source = FileImageSource(str(image_path))

            self.assertEqual(source.latest_image_path(), image_path)

    def test_raises_when_file_missing(self) -> None:
        source = FileImageSource("/nonexistent/path/latest.jpg")

        with self.assertRaises(ImageSourceError):
            source.latest_image_path()


class IndiAllskyDbImageSourceTests(unittest.TestCase):
    def _make_db(self, tmp: str, rows: list[tuple[int, str, str]]) -> Path:
        db_path = Path(tmp) / "indi-allsky.sqlite"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("CREATE TABLE camera (id INTEGER PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE image (id INTEGER PRIMARY KEY, filename TEXT, "
                "createDate TEXT, camera_id INTEGER)"
            )
            camera_ids = {camera_id for camera_id, _, _ in rows}
            connection.executemany(
                "INSERT INTO camera (id) VALUES (?)", [(c,) for c in camera_ids]
            )
            connection.executemany(
                "INSERT INTO image (camera_id, filename, createDate) VALUES (?, ?, ?)",
                rows,
            )
            connection.commit()
        finally:
            connection.close()
        return db_path

    def test_returns_most_recent_image_for_camera(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._make_db(
                tmp,
                rows=[
                    (1, "older.jpg", "2026-09-01 00:00:00"),
                    (1, "newest.jpg", "2026-09-02 00:00:00"),
                    (2, "other_camera.jpg", "2026-09-03 00:00:00"),
                ],
            )
            image_root = Path(tmp) / "images"
            image_root.mkdir()
            (image_root / "newest.jpg").write_bytes(b"fake")
            (image_root / "older.jpg").write_bytes(b"fake")

            source = IndiAllskyDbImageSource(
                db_path=str(db_path), camera_id=1, image_root=str(image_root)
            )

            self.assertEqual(source.latest_image_path(), image_root / "newest.jpg")

    def test_raises_when_no_rows_for_camera(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._make_db(tmp, rows=[(2, "other.jpg", "2026-09-01 00:00:00")])
            source = IndiAllskyDbImageSource(
                db_path=str(db_path), camera_id=1, image_root=tmp
            )

            with self.assertRaises(ImageSourceError):
                source.latest_image_path()

    def test_raises_when_database_missing(self) -> None:
        source = IndiAllskyDbImageSource(
            db_path="/nonexistent/indi-allsky.sqlite", camera_id=1, image_root="/tmp"
        )

        with self.assertRaises(ImageSourceError):
            source.latest_image_path()

    def test_raises_when_referenced_file_missing_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._make_db(tmp, rows=[(1, "missing.jpg", "2026-09-01 00:00:00")])
            source = IndiAllskyDbImageSource(
                db_path=str(db_path), camera_id=1, image_root=tmp
            )

            with self.assertRaises(ImageSourceError):
                source.latest_image_path()


if __name__ == "__main__":
    unittest.main()
