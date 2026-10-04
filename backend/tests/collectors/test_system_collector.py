"""Tests for System collector edge cases."""

from unittest.mock import mock_open, patch

from app.collectors.system import SystemCollector, SystemInfoData


def create_mock_open(file_contents: dict):
    """Create a mock open that returns different content based on file path."""
    def mock_open_func(path, *args, **kwargs):
        if path in file_contents:
            return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
        return mock_open(read_data="")(path, *args, **kwargs)
    return mock_open_func


class TestSystemCollector:
    """Test System collector edge cases."""

    def test_valid_system_information(self):
        """Test valid system information collection."""
        collector = SystemCollector(interval_seconds=3600.0)

        file_contents = {
            "/proc/cpuinfo": (
                "processor\t: 0\n"
                "vendor_id\t: GenuineIntel\n"
                "model name\t: Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz\n"
                "physical id\t: 0\n"
                "core id\t\t: 0\n"
                "processor\t: 1\n"
                "vendor_id\t: GenuineIntel\n"
                "model name\t: Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz\n"
                "physical id\t: 0\n"
                "core id\t\t: 1\n"
            ),
            "/proc/meminfo": "MemTotal:       32768000 kB\n",
            "/proc/stat": "btime 1700000000\n",
            "/etc/os-release": 'PRETTY_NAME="Ubuntu 22.04.3 LTS"\nVERSION_ID="22.04"\n',
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="5.15.0-91-generic"):
                    with patch("platform.machine", return_value="x86_64"):
                        with patch("socket.gethostname", return_value="test-server"):
                            with patch("os.cpu_count", return_value=8):
                                import asyncio
                                result = asyncio.run(collector._collect())

        assert isinstance(result, SystemInfoData)
        assert result.hostname == "test-server"
        assert result.os_name == "Ubuntu 22.04.3 LTS"
        assert result.os_version == "22.04"
        assert result.kernel_version == "5.15.0-91-generic"
        assert result.architecture == "x86_64"
        assert result.boot_time == 1700000000.0
        assert "Intel" in result.cpu_model
        assert result.cpu_cores_logical == 8
        assert result.cpu_cores_physical >= 1
        assert result.total_memory == 32768000 * 1024

    def test_missing_proc_cpuinfo(self):
        """Test handling of missing /proc/cpuinfo."""
        collector = SystemCollector(interval_seconds=3600.0)

        file_contents = {
            "/proc/meminfo": "MemTotal:       32768000 kB\n",
            "/proc/stat": "btime 1700000000\n",
            "/etc/os-release": 'PRETTY_NAME="Ubuntu 22.04"\nVERSION_ID="22.04"\n',
        }

        def mock_open_func(path, *args, **kwargs):
            if path == "/proc/cpuinfo":
                raise FileNotFoundError()
            if path in file_contents:
                return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="5.15.0-91-generic"):
                    with patch("platform.machine", return_value="x86_64"):
                        with patch("socket.gethostname", return_value="test-server"):
                            with patch("os.cpu_count", return_value=8):
                                import asyncio
                                result = asyncio.run(collector._collect())

        assert result.cpu_model != ""
        assert result.cpu_cores_physical >= 0
        assert result.total_memory == 32768000 * 1024

    def test_missing_proc_meminfo(self):
        """Test handling of missing /proc/meminfo."""
        collector = SystemCollector(interval_seconds=3600.0)

        file_contents = {
            "/proc/cpuinfo": "model name\t: Intel CPU\n",
            "/proc/stat": "btime 1700000000\n",
            "/etc/os-release": 'PRETTY_NAME="Ubuntu 22.04"\nVERSION_ID="22.04"\n',
        }

        def mock_open_func(path, *args, **kwargs):
            if path == "/proc/meminfo":
                raise FileNotFoundError()
            if path in file_contents:
                return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="5.15.0-91-generic"):
                    with patch("platform.machine", return_value="x86_64"):
                        with patch("socket.gethostname", return_value="test-server"):
                            with patch("os.cpu_count", return_value=8):
                                import asyncio
                                result = asyncio.run(collector._collect())

        assert result.total_memory == 0

    def test_missing_etc_os_release(self):
        """Test handling of missing /etc/os-release."""
        collector = SystemCollector(interval_seconds=3600.0)

        file_contents = {
            "/proc/cpuinfo": "model name\t: Intel CPU\n",
            "/proc/meminfo": "MemTotal:       32768000 kB\n",
            "/proc/stat": "btime 1700000000\n",
        }

        def mock_open_func(path, *args, **kwargs):
            if path == "/etc/os-release":
                raise FileNotFoundError()
            if path in file_contents:
                return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="5.15.0-91-generic"):
                    with patch("platform.machine", return_value="x86_64"):
                        with patch("socket.gethostname", return_value="test-server"):
                            with patch("os.cpu_count", return_value=8):
                                import asyncio
                                result = asyncio.run(collector._collect())

        assert result.os_name == "Linux"
        assert result.os_version == "5.15.0-91-generic"

    def test_missing_proc_stat_btime(self):
        """Test handling of missing btime in /proc/stat."""
        collector = SystemCollector(interval_seconds=3600.0)

        file_contents = {
            "/proc/cpuinfo": "model name\t: Intel CPU\n",
            "/proc/meminfo": "MemTotal:       32768000 kB\n",
            "/proc/stat": "cpu  100 200 300 400\n",
            "/etc/os-release": 'PRETTY_NAME="Ubuntu 22.04"\nVERSION_ID="22.04"\n',
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="5.15.0-91-generic"):
                    with patch("platform.machine", return_value="x86_64"):
                        with patch("socket.gethostname", return_value="test-server"):
                            with patch("os.cpu_count", return_value=8):
                                import asyncio
                                result = asyncio.run(collector._collect())

        assert result.boot_time == 0.0

    def test_partial_information_availability(self):
        """Test with only some information sources available."""
        collector = SystemCollector(interval_seconds=3600.0)

        file_contents = {
            "/etc/os-release": 'PRETTY_NAME="Custom Linux"\nVERSION_ID="1.0"\n',
        }

        def mock_open_func(path, *args, **kwargs):
            if path in file_contents:
                return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
            raise FileNotFoundError()

        with patch("builtins.open", side_effect=mock_open_func):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="6.0.0"):
                    with patch("platform.machine", return_value="aarch64"):
                        with patch("socket.gethostname", return_value="embedded-device"):
                            with patch("os.cpu_count", return_value=4):
                                import asyncio
                                result = asyncio.run(collector._collect())

        assert result.hostname == "embedded-device"
        assert result.os_name == "Custom Linux"
        assert result.os_version == "1.0"
        assert result.architecture == "aarch64"
        assert result.cpu_cores_logical == 4
        assert result.total_memory == 0

    def test_only_collects_once(self):
        """Test that system info is only collected once."""
        collector = SystemCollector(interval_seconds=3600.0)

        file_contents = {
            "/proc/cpuinfo": "model name\t: Intel CPU\n",
            "/proc/meminfo": "MemTotal:       32768000 kB\n",
            "/proc/stat": "btime 1700000000\n",
            "/etc/os-release": 'PRETTY_NAME="Ubuntu 22.04"\nVERSION_ID="22.04"\n',
        }

        call_count = [0]

        def mock_open_func(path, *args, **kwargs):
            call_count[0] += 1
            if path in file_contents:
                return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="5.15.0"):
                    with patch("platform.machine", return_value="x86_64"):
                        with patch("socket.gethostname", return_value="test"):
                            with patch("os.cpu_count", return_value=8):
                                import asyncio
                                result1 = asyncio.run(collector._collect())
                                result2 = asyncio.run(collector._collect())

        assert result1 is result2
