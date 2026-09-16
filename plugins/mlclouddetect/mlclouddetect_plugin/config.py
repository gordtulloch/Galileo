from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class MlCloudDetectConfig:
    image_source: str = "file"
    allsky_file: Optional[str] = None
    indi_allsky_db_path: str = "/var/lib/indi-allsky/indi-allsky.sqlite"
    indi_allsky_image_root: str = "/var/www/html/allsky/images/"
    camera_id: int = 1
    model_path: str = "keras_model.h5"
    labels_path: Optional[str] = "labels.txt"
    cloudy_label: str = "Cloudy"
    image_size: Tuple[int, int] = (224, 224)
    pending_count: int = 3

    def __post_init__(self) -> None:
        if self.image_source not in ("file", "indi_allsky_db"):
            raise ValueError(
                f"image_source must be 'file' or 'indi_allsky_db', got {self.image_source!r}"
            )
        if self.image_source == "file" and not self.allsky_file:
            raise ValueError("allsky_file is required when image_source is 'file'")
        if self.pending_count < 1:
            raise ValueError("pending_count must be >= 1")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MlCloudDetectConfig":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in raw.items() if k in known}
        if "image_size" in filtered:
            filtered["image_size"] = tuple(filtered["image_size"])
        return cls(**filtered)
