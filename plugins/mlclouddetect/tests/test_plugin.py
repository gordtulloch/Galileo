import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from galileo_plugin_api import PluginContext

from mlclouddetect_plugin.classifier import ClassificationResult
from mlclouddetect_plugin.config import MlCloudDetectConfig
from mlclouddetect_plugin.plugin import MlCloudDetectSafetyMonitor


def _result(label: str, confidence: float = 0.9) -> ClassificationResult:
    return ClassificationResult(label=label, confidence=confidence, raw_scores=[confidence])


class MlCloudDetectSafetyMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        image_path = Path(self._tmp.name) / "latest.jpg"
        image_path.write_bytes(b"fake")

        self.config = MlCloudDetectConfig(
            image_source="file",
            allsky_file=str(image_path),
            pending_count=3,
        )
        self.context = PluginContext(log=logging.getLogger("test.mlclouddetect"), config_dir=self._tmp.name)
        self.plugin = MlCloudDetectSafetyMonitor(self.context, self.config)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_capabilities_reports_safety_support(self) -> None:
        caps = self.plugin.capabilities()

        self.assertTrue(caps.can_report_safety)
        self.assertEqual(caps.extra["image_source"], "file")

    def test_poll_before_connect_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            self.plugin.poll()

    def test_default_state_is_safe_before_any_reading(self) -> None:
        self.assertTrue(self.plugin.is_safe)

    def test_single_cloudy_reading_does_not_flip_state(self) -> None:
        self.plugin.connect()

        with patch(
            "mlclouddetect_plugin.plugin.CloudClassifier.classify",
            return_value=_result("Cloudy"),
        ):
            self.plugin.poll()

        self.assertTrue(self.plugin.is_safe)  # only 1 of 3 required consistent readings

    def test_state_flips_after_pending_count_consistent_readings(self) -> None:
        self.plugin.connect()

        with patch(
            "mlclouddetect_plugin.plugin.CloudClassifier.classify",
            return_value=_result("Cloudy"),
        ):
            self.plugin.poll()
            self.plugin.poll()
            self.assertTrue(self.plugin.is_safe)
            self.plugin.poll()

        self.assertFalse(self.plugin.is_safe)

    def test_a_single_clear_reading_resets_the_cloudy_streak(self) -> None:
        self.plugin.connect()

        with patch("mlclouddetect_plugin.plugin.CloudClassifier.classify") as mock_classify:
            mock_classify.return_value = _result("Cloudy")
            self.plugin.poll()
            self.plugin.poll()

            mock_classify.return_value = _result("Clear")
            self.plugin.poll()

            mock_classify.return_value = _result("Cloudy")
            self.plugin.poll()
            self.plugin.poll()

        self.assertTrue(self.plugin.is_safe)  # streak was reset, never reached 3

    def test_status_reflects_last_reading(self) -> None:
        self.plugin.connect()
        with patch(
            "mlclouddetect_plugin.plugin.CloudClassifier.classify",
            return_value=_result("Clear"),
        ):
            self.plugin.poll()

        status = self.plugin.status
        self.assertTrue(status.connected)
        self.assertEqual(status.detail, "Clear")


if __name__ == "__main__":
    unittest.main()
