from __future__ import annotations

from typing import Any, Optional

from galileo_plugin_api import (
    DeviceCapabilities,
    DeviceStatus,
    PluginContext,
    PluginManifest,
    SafetyMonitorPort,
)

from .classifier import ClassificationResult, CloudClassifier
from .config import MlCloudDetectConfig
from .image_source import FileImageSource, ImageSource, ImageSourceError, IndiAllskyDbImageSource

MANIFEST = PluginManifest(
    name="mlclouddetect",
    version="0.1.0",
    api_compat_range=">=0.1,<1.0",
    description="Cloud-cover safety monitor via ML classification of all-sky camera imagery.",
)


def _build_image_source(config: MlCloudDetectConfig) -> ImageSource:
    if config.image_source == "file":
        assert config.allsky_file is not None  # enforced by MlCloudDetectConfig.__post_init__
        return FileImageSource(config.allsky_file)
    return IndiAllskyDbImageSource(
        db_path=config.indi_allsky_db_path,
        camera_id=config.camera_id,
        image_root=config.indi_allsky_image_root,
    )


class MlCloudDetectSafetyMonitor(SafetyMonitorPort):
    """SafetyMonitorPort implementation backed by mlCloudDetect-style ML classification.

    Reads the latest all-sky camera frame (file or indi-allsky database — Project
    Scope Document Section 6.7) and reports cloud-cover safety state, debounced over
    `pending_count` consecutive consistent readings so a single borderline frame
    can't flip the reported state (mirrors mlCloudDetect's own pending-state design).
    """

    def __init__(self, context: PluginContext, config: MlCloudDetectConfig) -> None:
        self._context = context
        self._config = config
        self._image_source = _build_image_source(config)
        self._classifier = CloudClassifier(config.model_path, config.labels_path, config.image_size)
        self._connected = False
        self._is_safe = True
        self._last_label: Optional[str] = None
        self._consistent_count = 0
        self._last_result: Optional[ClassificationResult] = None

    def connect(self) -> None:
        self._connected = True
        self._context.log.info("mlclouddetect: connected (source=%s)", self._config.image_source)

    def disconnect(self) -> None:
        self._connected = False
        self._context.log.info("mlclouddetect: disconnected")

    def capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            can_report_safety=True,
            extra={"image_source": self._config.image_source},
        )

    def poll(self) -> ClassificationResult:
        """Fetch and classify the latest frame, updating debounced safety state.

        Raises ImageSourceError / RuntimeError on failure rather than silently
        reporting stale state — the caller (galileo.safety, SDD Section 4.16) is
        responsible for deciding how a poll failure affects the overall safety
        picture, consistent with this plugin only ever acting as one input among
        several device-backed and internet-advisory sources.
        """
        if not self._connected:
            raise RuntimeError("mlclouddetect plugin is not connected")

        image_path = self._image_source.latest_image_path()
        result = self._classifier.classify(image_path)

        if result.label == self._last_label:
            self._consistent_count += 1
        else:
            self._last_label = result.label
            self._consistent_count = 1

        if self._consistent_count >= self._config.pending_count:
            self._is_safe = result.label != self._config.cloudy_label

        self._last_result = result
        self._context.log.debug(
            "mlclouddetect: label=%s confidence=%.3f streak=%d/%d is_safe=%s",
            result.label,
            result.confidence,
            self._consistent_count,
            self._config.pending_count,
            self._is_safe,
        )
        return result

    @property
    def is_safe(self) -> bool:
        return self._is_safe

    @property
    def status(self) -> DeviceStatus:
        detail = self._last_result.label if self._last_result else "no reading yet"
        return DeviceStatus(connected=self._connected, safe=self._is_safe, detail=detail)


def create_plugin(context: PluginContext, raw_config: dict[str, Any]) -> MlCloudDetectSafetyMonitor:
    """Entry-point factory referenced by pyproject.toml's [project.entry-points]."""
    config = MlCloudDetectConfig.from_dict(raw_config)
    return MlCloudDetectSafetyMonitor(context, config)
