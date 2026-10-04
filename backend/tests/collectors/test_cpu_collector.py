"""Tests for CPU collector edge cases."""

import os
import tempfile
from unittest.mock import mock_open, patch

from app.collectors.cpu import CPUCollector, CPUData


def create_mock_open(file_contents: dict):
    """Create a mock open that returns different content based on file path."""
    def mock_open_func(path, *args, **kwargs):
        if path in file_contents:
            return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
        return mock_open(read_data="")(path, *args, **kwargs)
    return mock_open_func


class TestCPUCollector:
    """Test CPU collector edge cases."""

    def test_normal_counter_delta(self):
        """Test normal CPU counter delta calculation."""
        collector = CPUCollector(interval_seconds=5.0)
        collector._prev_total = 10000.0
        collector._prev_idle = 8000.0

        file_contents = {
            "/proc/stat": "cpu  2000 500 3000 12000 500 100 200 50 0 0\n",
            "/proc/loadavg": "0.5 0.3 0.2\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch("os.cpu_count", return_value=4):
                import asyncio
                result = asyncio.run(collector._collect())

        assert result.total_utilization > 0.0
        assert result.total_utilization <= 100.0
        assert result.cpu_count == 4

    def test_counter_reset(self):
        """Test handling of counter reset (values decrease)."""
        collector = CPUCollector(interval_seconds=5.0)
        collector._prev_total = 10000.0
        collector._prev_idle = 8000.0

        file_contents = {
            "/proc/stat": "cpu  500 100 600 4000 100 20 40 10 0 0\n",
            "/proc/loadavg": "0.5 0.3 0.2\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch("os.cpu_count", return_value=4):
                import asyncio
                result = asyncio.run(collector._collect())

        assert result.total_utilization >= 0.0

    def test_malformed_proc_stat(self):
        """Test handling of malformed /proc/stat."""
        collector = CPUCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/stat": "cpu  2000 500\n",
            "/proc/loadavg": "0.5 0.3 0.2\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert isinstance(result, CPUData)
        assert result.total_utilization == 0.0

    def test_missing_proc_stat(self):
        """Test handling of missing /proc/stat."""
        collector = CPUCollector(interval_seconds=5.0)

        def mock_open_func(path, *args, **kwargs):
            if path == "/proc/stat":
                raise FileNotFoundError()
            if path == "/proc/loadavg":
                return mock_open(read_data="0.5 0.3 0.2")(path, *args, **kwargs)
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            import asyncio
            result = asyncio.run(collector._collect())

        assert isinstance(result, CPUData)
        assert result.total_utilization == 0.0

    def test_per_core_calculation(self):
        """Test per-core utilization calculation."""
        collector = CPUCollector(interval_seconds=5.0)
        collector._prev_per_core = [(5000.0, 4000.0), (3000.0, 2500.0)]

        file_contents = {
            "/proc/stat": (
                "cpu  5000 1000 3000 15000 500 100 200 50 0 0\n"
                "cpu0 2500 500 1500 7500 250 50 100 25 0 0\n"
                "cpu1 2500 500 1500 7500 250 50 100 25 0 0\n"
            ),
            "/proc/loadavg": "0.5 0.3 0.2\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch("os.cpu_count", return_value=2):
                import asyncio
                result = asyncio.run(collector._collect())

        assert len(result.per_core) == 2
        assert all(0.0 <= util <= 100.0 for util in result.per_core)

    def test_load_average_parsing(self):
        """Test load average parsing from /proc/loadavg."""
        collector = CPUCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/stat": "cpu  2000 500 3000 12000 500 100 200 50 0 0\n",
            "/proc/loadavg": "1.5 0.8 0.3 2/123 456\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch("os.cpu_count", return_value=4):
                import asyncio
                result = asyncio.run(collector._collect())

        assert result.load_average == (1.5, 0.8, 0.3)

    def test_malformed_loadavg(self):
        """Test handling of malformed /proc/loadavg."""
        collector = CPUCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/stat": "cpu  2000 500 3000 12000 500 100 200 50 0 0\n",
            "/proc/loadavg": "malformed\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch("os.cpu_count", return_value=4):
                import asyncio
                result = asyncio.run(collector._collect())

        assert result.load_average == (0.0, 0.0, 0.0)

    def test_first_run_no_delta(self):
        """Test first run with no previous data."""
        collector = CPUCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/stat": "cpu  2000 500 3000 12000 500 100 200 50 0 0\n",
            "/proc/loadavg": "0.5 0.3 0.2\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch("os.cpu_count", return_value=4):
                import asyncio
                result = asyncio.run(collector._collect())

        assert result.total_utilization == 0.0
        assert collector._prev_total is not None


class TestCPUCollectorIntegration:
    """Integration-style tests using temp files."""

    def test_with_temp_proc_stat(self):
        """Test using actual temp file for /proc/stat."""
        collector = CPUCollector(interval_seconds=5.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            stat_file = os.path.join(tmpdir, "stat")
            with open(stat_file, "w") as f:
                f.write("cpu  2000 500 3000 12000 500 100 200 50 0 0\n")

            def mock_open_func(path, *args, **kwargs):
                if path == "/proc/stat":
                    return open(stat_file, *args, **kwargs)
                if path == "/proc/loadavg":
                    return mock_open(read_data="0.5 0.3 0.2")(path, *args, **kwargs)
                return mock_open(read_data="")(path, *args, **kwargs)

            with patch("builtins.open", side_effect=mock_open_func):
                with patch("os.cpu_count", return_value=4):
                    import asyncio
                    result = asyncio.run(collector._collect())

        assert isinstance(result, CPUData)
