"""Tests for Temperature collector edge cases."""

import os
from unittest.mock import mock_open, patch

from app.collectors.temperature import TemperatureCollector


def normalize_path(path: str) -> str:
    """Normalize path for consistent dictionary keys."""
    return os.path.normpath(path)


def create_mock_open(file_contents: dict):
    """Create a mock open that returns different content based on file path."""
    # Normalize all keys upfront
    norm_contents = {normalize_path(k): v for k, v in file_contents.items()}
    def mock_open_func(path, *args, **kwargs):
        norm_path = normalize_path(path)
        if norm_path in norm_contents:
            return mock_open(read_data=norm_contents[norm_path])(path, *args, **kwargs)
        return mock_open(read_data="")(path, *args, **kwargs)
    return mock_open_func


def make_thermal_paths():
    """Create thermal zone paths with correct separators.

    Note: The collector looks for trip_point_1 for high and trip_point_2 for critical.
    """
    base = os.path.join("/sys/class/thermal", "thermal_zone0")
    raw = {
        os.path.join(base, "temp"): "45000",
        os.path.join(base, "type"): "x86_pkg_temp",
        # Collector checks for "trip_point_1" in path for high threshold
        os.path.join(base, "trip_point_1_temp"): "80000",
        # Collector checks for "trip_point_2" in path for critical threshold
        os.path.join(base, "trip_point_2_temp"): "95000",
    }
    # Normalize keys
    return {normalize_path(k): v for k, v in raw.items()}


def make_hwmon_paths():
    """Create hwmon paths with correct separators."""
    base = os.path.join("/sys/class/hwmon", "hwmon0")
    raw = {
        os.path.join(base, "name"): "coretemp",
        os.path.join(base, "temp1_input"): "50000",
        os.path.join(base, "temp1_label"): "Package id 0",
        os.path.join(base, "temp1_max"): "80000",
        os.path.join(base, "temp1_crit"): "100000",
    }
    # Normalize keys
    return {normalize_path(k): v for k, v in raw.items()}


class TestTemperatureCollector:
    """Test Temperature collector edge cases."""

    def test_no_sensors(self):
        """Test when no temperature sensors exist."""
        with patch("os.path.isdir", return_value=False):
            collector = TemperatureCollector(interval_seconds=10.0)
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_valid_thermal_sensor(self):
        """Test valid thermal zone sensor."""

        def mock_isdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/thermal"):
                return True
            if norm == normalize_path("/sys/class/thermal/thermal_zone0"):
                return True
            if norm == normalize_path("/sys/class/hwmon"):
                return True
            return False

        def mock_listdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/thermal"):
                return ["thermal_zone0"]
            if norm == normalize_path("/sys/class/hwmon"):
                return []
            return []

        mock_files = make_thermal_paths()

        def mock_exists(path):
            return normalize_path(path) in mock_files

        def mock_glob(pattern):
            norm_pattern = normalize_path(pattern)
            if "trip_point" in norm_pattern:
                return [
                    normalize_path(os.path.join("/sys/class/thermal", "thermal_zone0", "trip_point_1_temp")),
                    normalize_path(os.path.join("/sys/class/thermal", "thermal_zone0", "trip_point_2_temp")),
                ]
            return []

        with patch("os.path.isdir", side_effect=mock_isdir):
            with patch("os.path.exists", side_effect=mock_exists):
                with patch("os.listdir", side_effect=mock_listdir):
                    with patch("builtins.open", side_effect=create_mock_open(mock_files)):
                        with patch("glob.glob", side_effect=mock_glob):
                            collector = TemperatureCollector(interval_seconds=10.0)
                            import asyncio
                            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].name == "thermal_zone0"
        assert result[0].label == "x86_pkg_temp"
        assert result[0].current == 45.0
        assert result[0].high == 80.0
        assert result[0].critical == 95.0
        assert result[0].unit == "celsius"

    def test_malformed_sensor_value(self):
        """Test handling of malformed sensor value."""

        def mock_isdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/thermal"):
                return True
            if norm == normalize_path("/sys/class/thermal/thermal_zone0"):
                return True
            return False

        def mock_listdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/thermal"):
                return ["thermal_zone0"]
            return []

        base = normalize_path(os.path.join("/sys/class/thermal", "thermal_zone0"))
        mock_files = {
            normalize_path(os.path.join(base, "temp")): "not_a_number",
            normalize_path(os.path.join(base, "type")): "x86_pkg_temp",
        }

        def mock_exists(path):
            return normalize_path(path) in mock_files

        def mock_glob(pattern):
            return []

        with patch("os.path.isdir", side_effect=mock_isdir):
            with patch("os.path.exists", side_effect=mock_exists):
                with patch("os.listdir", side_effect=mock_listdir):
                    with patch("builtins.open", side_effect=create_mock_open(mock_files)):
                        with patch("glob.glob", side_effect=mock_glob):
                            collector = TemperatureCollector(interval_seconds=10.0)
                            import asyncio
                            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_sensor_disappearing(self):
        """Test sensor that disappears between discovery and read."""

        def mock_isdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/thermal"):
                return True
            if norm == normalize_path("/sys/class/thermal/thermal_zone0"):
                return True
            return False

        def mock_listdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/thermal"):
                return ["thermal_zone0"]
            return []

        base = normalize_path(os.path.join("/sys/class/thermal", "thermal_zone0"))
        mock_files = {
            normalize_path(os.path.join(base, "type")): "x86_pkg_temp",
            # temp file missing
        }

        def mock_exists(path):
            return normalize_path(path) in mock_files

        def mock_glob(pattern):
            return []

        with patch("os.path.isdir", side_effect=mock_isdir):
            with patch("os.path.exists", side_effect=mock_exists):
                with patch("os.listdir", side_effect=mock_listdir):
                    with patch("builtins.open", side_effect=create_mock_open(mock_files)):
                        with patch("glob.glob", side_effect=mock_glob):
                            collector = TemperatureCollector(interval_seconds=10.0)
                            import asyncio
                            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_missing_trip_point(self):
        """Test sensor without trip point thresholds."""

        def mock_isdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/thermal"):
                return True
            if norm == normalize_path("/sys/class/thermal/thermal_zone0"):
                return True
            return False

        def mock_listdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/thermal"):
                return ["thermal_zone0"]
            return []

        base = normalize_path(os.path.join("/sys/class/thermal", "thermal_zone0"))
        mock_files = {
            normalize_path(os.path.join(base, "temp")): "45000",
            normalize_path(os.path.join(base, "type")): "x86_pkg_temp",
            # No trip_point files
        }

        def mock_exists(path):
            return normalize_path(path) in mock_files

        def mock_glob(pattern):
            return []

        with patch("os.path.isdir", side_effect=mock_isdir):
            with patch("os.path.exists", side_effect=mock_exists):
                with patch("os.listdir", side_effect=mock_listdir):
                    with patch("builtins.open", side_effect=create_mock_open(mock_files)):
                        with patch("glob.glob", side_effect=mock_glob):
                            collector = TemperatureCollector(interval_seconds=10.0)
                            import asyncio
                            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].current == 45.0
        assert result[0].high is None
        assert result[0].critical is None

    def test_hwmon_sensor(self):
        """Test hwmon sensor discovery."""

        def mock_isdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/thermal"):
                return False
            if norm == normalize_path("/sys/class/hwmon"):
                return True
            if norm == normalize_path("/sys/class/hwmon/hwmon0"):
                return True
            return False

        def mock_listdir(path):
            norm = normalize_path(path)
            if norm == normalize_path("/sys/class/hwmon"):
                return ["hwmon0"]
            if norm == normalize_path("/sys/class/hwmon/hwmon0"):
                return ["name", "temp1_input", "temp1_label", "temp1_max", "temp1_crit"]
            return []

        mock_files = make_hwmon_paths()

        def mock_exists(path):
            return normalize_path(path) in mock_files

        def mock_glob(pattern):
            norm_pattern = normalize_path(pattern)
            if "temp*_input" in norm_pattern:
                return [normalize_path(os.path.join("/sys/class/hwmon", "hwmon0", "temp1_input"))]
            return []

        with patch("os.path.isdir", side_effect=mock_isdir):
            with patch("os.path.exists", side_effect=mock_exists):
                with patch("os.listdir", side_effect=mock_listdir):
                    with patch("builtins.open", side_effect=create_mock_open(mock_files)):
                        with patch("glob.glob", side_effect=mock_glob):
                            collector = TemperatureCollector(interval_seconds=10.0)
                            import asyncio
                            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].name == "hwmon0_temp1"
        assert result[0].label == "Package id 0"
        assert result[0].current == 50.0
        assert result[0].high == 80.0
        assert result[0].critical == 100.0
