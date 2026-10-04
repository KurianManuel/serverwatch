"""Tests for Memory collector edge cases."""

from unittest.mock import mock_open, patch

from app.collectors.memory import MemoryCollector, MemoryData


def create_mock_open(file_contents: dict):
    """Create a mock open that returns different content based on file path."""
    def mock_open_func(path, *args, **kwargs):
        if path in file_contents:
            return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
        return mock_open(read_data="")(path, *args, **kwargs)
    return mock_open_func


class TestMemoryCollector:
    """Test Memory collector edge cases."""

    def test_valid_meminfo(self):
        """Test parsing valid /proc/meminfo."""
        collector = MemoryCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/meminfo": (
                "MemTotal:       16384000 kB\n"
                "MemFree:        4096000 kB\n"
                "MemAvailable:   8192000 kB\n"
                "Buffers:        1024000 kB\n"
                "Cached:         5120000 kB\n"
                "SwapTotal:      4194304 kB\n"
                "SwapFree:       2097152 kB\n"
            ),
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert isinstance(result, MemoryData)
        assert result.total == 16384000 * 1024
        assert result.available == 8192000 * 1024
        assert result.used == result.total - result.available
        assert result.buffers == 1024000 * 1024
        assert result.cached == 5120000 * 1024
        assert result.swap_total == 4194304 * 1024
        assert result.swap_free == 2097152 * 1024
        assert result.swap_used == result.swap_total - result.swap_free

    def test_missing_meminfo(self):
        """Test handling of missing /proc/meminfo."""
        collector = MemoryCollector(interval_seconds=5.0)

        def mock_open_func(path, *args, **kwargs):
            if path == "/proc/meminfo":
                raise FileNotFoundError()
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            import asyncio
            result = asyncio.run(collector._collect())

        assert isinstance(result, MemoryData)
        assert result.total == 0
        assert result.available == 0
        assert result.used == 0

    def test_malformed_meminfo_values(self):
        """Test handling of malformed values in /proc/meminfo - should not crash."""
        collector = MemoryCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/meminfo": (
                "MemTotal:       not_a_number kB\n"
                "MemAvailable:   8192000 kB\n"
            ),
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            # Should not raise exception - the collector catches exceptions
            result = asyncio.run(collector._collect())

        assert isinstance(result, MemoryData)

    def test_fallback_used_calculation(self):
        """Test fallback used calculation when MemAvailable missing."""
        collector = MemoryCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/meminfo": (
                "MemTotal:       16384000 kB\n"
                "MemFree:        4096000 kB\n"
                "Buffers:        1024000 kB\n"
                "Cached:         5120000 kB\n"
            ),
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert result.total == 16384000 * 1024
        expected_used = 16384000 * 1024 - 4096000 * 1024 - 1024000 * 1024 - 5120000 * 1024
        assert result.used == expected_used

    def test_no_swap(self):
        """Test system with no swap."""
        collector = MemoryCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/meminfo": (
                "MemTotal:       16384000 kB\n"
                "MemAvailable:   8192000 kB\n"
                "SwapTotal:      0 kB\n"
                "SwapFree:       0 kB\n"
            ),
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert result.swap_total == 0
        assert result.swap_used == 0
        assert result.swap_free == 0

    def test_partial_meminfo(self):
        """Test with only some meminfo fields present."""
        collector = MemoryCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/meminfo": (
                "MemTotal:       16384000 kB\n"
            ),
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert result.total == 16384000 * 1024
        assert result.available == 0
        assert result.free == 0
