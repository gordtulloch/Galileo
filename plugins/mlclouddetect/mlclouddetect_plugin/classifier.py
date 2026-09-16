from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_LABELS = ("Clear", "Cloudy")


@dataclass(frozen=True)
class ClassificationResult:
    label: str
    confidence: float
    raw_scores: List[float]


class CloudClassifier:
    """Wraps a Keras image classifier trained on all-sky camera frames.

    Model I/O follows the common Teachable-Machine export convention this class of
    model is typically trained with: a 224x224 RGB input normalized to [-1, 1], and
    an output vector of per-class scores read via argmax. TensorFlow/Keras is an
    optional dependency, imported lazily so this module (and the rest of the plugin)
    can be imported and unit-tested without it installed.
    """

    def __init__(
        self,
        model_path: str,
        labels_path: Optional[str] = None,
        image_size: Tuple[int, int] = (224, 224),
    ) -> None:
        self._model_path = Path(model_path)
        self._image_size = image_size
        self._labels = self._load_labels(labels_path)
        self._model = None

    def _load_labels(self, labels_path: Optional[str]) -> List[str]:
        if labels_path and Path(labels_path).is_file():
            lines = Path(labels_path).read_text(encoding="utf-8").splitlines()
            labels = [line.split(maxsplit=1)[-1].strip() if line.strip() else line for line in lines if line.strip()]
            if labels:
                return labels
        return list(DEFAULT_LABELS)

    def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            import tensorflow as tf
        except ImportError as exc:
            raise RuntimeError(
                "TensorFlow/Keras is required for cloud classification. "
                "Install it with `pip install tensorflow` (see plugins/mlclouddetect/README.md)."
            ) from exc
        if not self._model_path.is_file():
            raise RuntimeError(f"cloud-classification model not found: {self._model_path}")
        self._model = tf.keras.models.load_model(self._model_path)

    def _preprocess(self, image_path: Path):
        import numpy as np
        from PIL import Image

        with Image.open(image_path) as img:
            resized = img.convert("RGB").resize(self._image_size)
        array = (np.asarray(resized, dtype=np.float32) / 127.5) - 1.0
        return np.expand_dims(array, axis=0)

    def classify(self, image_path: Path) -> ClassificationResult:
        import numpy as np

        self._ensure_model_loaded()
        batch = self._preprocess(image_path)
        predictions = self._model.predict(batch, verbose=0)[0]
        index = int(np.argmax(predictions))
        label = self._labels[index] if index < len(self._labels) else f"class_{index}"
        return ClassificationResult(
            label=label,
            confidence=float(predictions[index]),
            raw_scores=[float(v) for v in predictions],
        )
