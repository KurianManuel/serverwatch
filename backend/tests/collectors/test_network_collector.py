"""Tests for Network collector edge cases."""

from unittest.mock import mock_open, patch

from app.collectors.network import NetworkCollector


def create_mock_open(file_contents: dict):
    """Create a mock open that returns different content based on file path."""
    def mock_open_func(path, *args, **kwargs):
        if path in file_contents:
            return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
        return mock_open(read_data="")(path, *args, **kwargs)
    return mock_open_func


class TestNetworkCollector:
    """Test Network collector edge cases."""

    def test_normal_counter_delta(self):
        """Test normal network counter delta calculation."""
        collector = NetworkCollector(interval_seconds=5.0)
        collector._prev_data = {
            "eth0": (1000000, 2000000, 1000, 2000, 10, 20, 5, 5, 100.0),
        }

        file_contents = {
            "/proc/net/dev": (
                "Inter-|   Receive                                                |  Transmit\n"
                " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
                "  eth0: 2000000 2000 15 8 0 0 0 0 3000000 3000 25 10 0 0 0 0\n"
            ),
            "/sys/class/net/eth0/operstate": "up\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].name == "eth0"
        assert result[0].state == "up"
        assert result[0].rx_bytes == 2000000
        assert result[0].tx_bytes == 3000000
        assert result[0].throughput_rx > 0
        assert result[0].throughput_tx > 0

    def test_counter_reset(self):
        """Test handling of counter reset (values decrease)."""
        collector = NetworkCollector(interval_seconds=5.0)
        collector._prev_data = {
            "eth0": (1000000, 2000000, 1000, 2000, 10, 20, 5, 5, 100.0),
        }

        file_contents = {
            "/proc/net/dev": (
                "Inter-|   Receive                                                |  Transmit\n"
                " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
                "  eth0: 500000 500 5 3 0 0 0 0 1000000 1000 10 5 0 0 0 0\n"
            ),
            "/sys/class/net/eth0/operstate": "up\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].throughput_rx >= 0
        assert result[0].throughput_tx >= 0

    def test_interface_disappearance(self):
        """Test cleanup of interfaces that no longer exist."""
        collector = NetworkCollector(interval_seconds=5.0)
        collector._prev_data = {
            "eth0": (1000000, 2000000, 1000, 2000, 10, 20, 5, 5, 100.0),
            "eth1": (500000, 1000000, 500, 1000, 5, 10, 3, 3, 100.0),
        }

        file_contents = {
            "/proc/net/dev": (
                "Inter-|   Receive                                                |  Transmit\n"
                " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
                "  eth0: 2000000 2000 15 8 0 0 0 0 3000000 3000 25 10 0 0 0 0\n"
            ),
            "/sys/class/net/eth0/operstate": "up\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].name == "eth0"
        assert "eth1" not in collector._prev_data

    def test_missing_operstate(self):
        """Test fallback when operstate file is missing."""
        collector = NetworkCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/net/dev": (
                "Inter-|   Receive                                                |  Transmit\n"
                " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
                "  eth0: 2000000 2000 15 8 0 0 0 0 3000000 3000 25 10 0 0 0 0\n"
            ),
        }

        def mock_open_func(path, *args, **kwargs):
            if path == "/proc/net/dev":
                return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
            if path == "/sys/class/net/eth0/operstate":
                raise FileNotFoundError()
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].state == "up"

    def test_down_interface(self):
        """Test interface with no traffic (down)."""
        collector = NetworkCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/net/dev": (
                "Inter-|   Receive                                                |  Transmit\n"
                " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
                "  eth0: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"
            ),
        }

        def mock_open_func(path, *args, **kwargs):
            if path == "/proc/net/dev":
                return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
            if path == "/sys/class/net/eth0/operstate":
                raise FileNotFoundError()
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].state == "down"

    def test_malformed_netdev(self):
        """Test handling of malformed /proc/net/dev."""
        collector = NetworkCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/net/dev": "malformed line\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_missing_netdev(self):
        """Test handling of missing /proc/net/dev."""
        collector = NetworkCollector(interval_seconds=5.0)

        def mock_open_func(path, *args, **kwargs):
            if path == "/proc/net/dev":
                raise FileNotFoundError()
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_first_run_no_delta(self):
        """Test first run with no previous data."""
        collector = NetworkCollector(interval_seconds=5.0)

        file_contents = {
            "/proc/net/dev": (
                "Inter-|   Receive                                                |  Transmit\n"
                " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
                "  eth0: 2000000 2000 15 8 0 0 0 0 3000000 3000 25 10 0 0 0 0\n"
            ),
            "/sys/class/net/eth0/operstate": "up\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].throughput_rx == 0.0
        assert result[0].throughput_tx == 0.0
