"""Tests for Disk collector edge cases."""

from unittest.mock import mock_open, patch

from app.collectors.disk import DiskCollector


def create_mock_open(file_contents: dict):
    """Create a mock open that returns different content based on file path."""
    def mock_open_func(path, *args, **kwargs):
        if path in file_contents:
            return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
        return mock_open(read_data="")(path, *args, **kwargs)
    return mock_open_func


class TestDiskCollector:
    """Test Disk collector edge cases."""

    def test_normal_counter_delta(self):
        """Test normal disk counter delta calculation."""
        collector = DiskCollector(interval_seconds=5.0)
        collector._prev_data = {
            "sda": (1000000, 2000000, 1000, 2000, 100.0),
        }

        file_contents = {
            "/proc/diskstats": "8 0 sda 2000 100 500000 100 3000 150 600000 200 0 0 0\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].device == "sda"
        assert result[0].read_bytes > 1000000
        assert result[0].write_bytes > 2000000
        assert result[0].read_throughput > 0
        assert result[0].write_throughput > 0
        assert result[0].iops > 0

    def test_counter_reset(self):
        """Test handling of counter reset (values decrease)."""
        collector = DiskCollector(interval_seconds=5.0)
        collector._prev_data = {
            "sda": (1000000, 2000000, 1000, 2000, 100.0),
        }

        file_contents = {
            "/proc/diskstats": "8 0 sda 1000 50 200000 50 1500 75 300000 100 0 0 0\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].read_throughput >= 0
        assert result[0].write_throughput >= 0
        assert result[0].iops >= 0

    def test_disappearing_block_device(self):
        """Test cleanup of devices that no longer exist."""
        collector = DiskCollector(interval_seconds=5.0)
        collector._prev_data = {
            "sda": (1000000, 2000000, 1000, 2000, 100.0),
            "sdb": (500000, 1000000, 500, 1000, 100.0),
        }

        file_contents = {
            "/proc/diskstats": "8 0 sda 2000 100 500000 100 3000 150 600000 200 0 0 0\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].device == "sda"
        assert "sdb" not in collector._prev_data

    def test_malformed_diskstats(self):
        """Test handling of malformed /proc/diskstats."""
        collector = DiskCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/diskstats": "8 0 sda 2000\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_missing_diskstats(self):
        """Test handling of missing /proc/diskstats."""
        collector = DiskCollector(interval_seconds=5.0)

        def mock_open_func(path, *args, **kwargs):
            if path == "/proc/diskstats":
                raise FileNotFoundError()
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_loop_and_ram_devices_filtered(self):
        """Test that loop and ram devices are filtered out."""
        collector = DiskCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/diskstats": (
                "8 0 sda 2000 100 500000 100 3000 150 600000 200 0 0 0\n"
                "7 0 loop0 100 50 200000 50 150 75 300000 100 0 0 0\n"
                "1 0 ram0 1000 50 200000 50 1500 75 300000 100 0 0 0\n"
            ),
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].device == "sda"

    def test_first_run_no_delta(self):
        """Test first run with no previous data."""
        collector = DiskCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/diskstats": "8 0 sda 2000 100 500000 100 3000 150 600000 200 0 0 0\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].read_throughput == 0.0
        assert result[0].write_throughput == 0.0
        assert result[0].iops == 0.0
