"""Tests for Processes collector edge cases."""

from unittest.mock import MagicMock, mock_open, patch

from app.collectors.processes import ProcessesCollector


def create_mock_open(file_contents: dict):
    """Create a mock open that returns different content based on file path."""
    def mock_open_func(path, *args, **kwargs):
        if path in file_contents:
            return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
        return mock_open(read_data="")(path, *args, **kwargs)
    return mock_open_func


class MockPsutilExceptions:
    """Mock psutil exception classes."""
    class NoSuchProcess(Exception):
        def __init__(self, pid):
            self.pid = pid
            super().__init__(f"Process {pid} not found")

    class AccessDenied(Exception):
        def __init__(self, pid):
            self.pid = pid
            super().__init__(f"Access denied to process {pid}")

    class ZombieProcess(Exception):
        def __init__(self, pid):
            self.pid = pid
            super().__init__(f"Process {pid} is zombie")


def get_mock_pwd():
    """Get a mock pwd module."""
    mock_pwd = MagicMock()
    mock_pwd.getpwuid.return_value = MagicMock(pw_name="testuser")
    return mock_pwd


class TestProcessesCollector:
    """Test Processes collector edge cases."""

    def test_normal_process(self):
        """Test normal process collection."""
        collector = ProcessesCollector(interval_seconds=10.0)

        file_contents = {
            "/proc/1234/stat": "1234 (test_process) S 1 1 1 1 1 1 1 1 1 1 100 200 10 5 0 1 0 0 1000000 100000 100 100 0 0 0 0 0 0 0 0 0 0\n",
            "/proc/1234/cmdline": "test_process\x00arg1\x00arg2\x00",
            "/proc/1234/status": "Uid:\t1000\t1000\t1000\t1000\n",
        }

        with patch("os.listdir", return_value=["1234"]):
            with patch("builtins.open", side_effect=create_mock_open(file_contents)):
                with patch("os.readlink", return_value="/usr/bin/test_process"):
                    with patch("os.cpu_count", return_value=4):
                        with patch("app.collectors.processes.ProcessesCollector._get_boot_time", return_value=0.0):
                            with patch.dict("sys.modules", {"pwd": get_mock_pwd()}):
                                import asyncio
                                result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].pid == 1234
        assert result[0].name == "test_process"
        assert result[0].exe == "/usr/bin/test_process"
        assert result[0].cmdline == ["test_process", "arg1", "arg2"]
        assert result[0].username == "testuser"
        assert result[0].status == "S"
        assert result[0].rss > 0
        assert result[0].vms > 0

    def test_process_disappears_between_reads(self):
        """Test process that disappears between PID listing and stat read."""
        collector = ProcessesCollector(interval_seconds=10.0)

        with patch("os.listdir", return_value=["1234"]):
            def mock_open_func(path, *args, **kwargs):
                if path == "/proc/1234/stat":
                    raise FileNotFoundError()
                return mock_open(read_data="")(path, *args, **kwargs)

            with patch("builtins.open", side_effect=mock_open_func):
                import asyncio
                result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_permission_error(self):
        """Test PermissionError when reading process files."""
        collector = ProcessesCollector(interval_seconds=10.0)

        with patch("os.listdir", return_value=["1234"]):
            def mock_open_func(path, *args, **kwargs):
                if path == "/proc/1234/stat":
                    raise PermissionError()
                return mock_open(read_data="")(path, *args, **kwargs)

            with patch("builtins.open", side_effect=mock_open_func):
                import asyncio
                result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_nosuchprocess_psutil(self):
        """Test psutil NoSuchProcess exception handling."""
        collector = ProcessesCollector(interval_seconds=10.0)
        collector._use_psutil = True
        mock_exceptions = MockPsutilExceptions()
        collector._psutil = MagicMock()
        collector._psutil.NoSuchProcess = mock_exceptions.NoSuchProcess
        collector._psutil.AccessDenied = mock_exceptions.AccessDenied
        collector._psutil.ZombieProcess = mock_exceptions.ZombieProcess
        collector._psutil.Process.side_effect = mock_exceptions.NoSuchProcess(1234)

        with patch("os.listdir", return_value=["1234"]):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_access_denied_psutil(self):
        """Test psutil AccessDenied exception handling."""
        collector = ProcessesCollector(interval_seconds=10.0)
        collector._use_psutil = True
        mock_exceptions = MockPsutilExceptions()
        collector._psutil = MagicMock()
        collector._psutil.NoSuchProcess = mock_exceptions.NoSuchProcess
        collector._psutil.AccessDenied = mock_exceptions.AccessDenied
        collector._psutil.ZombieProcess = mock_exceptions.ZombieProcess
        collector._psutil.Process.side_effect = mock_exceptions.AccessDenied(1234)

        with patch("os.listdir", return_value=["1234"]):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_zombie_process_psutil(self):
        """Test psutil ZombieProcess exception handling."""
        collector = ProcessesCollector(interval_seconds=10.0)
        collector._use_psutil = True
        mock_exceptions = MockPsutilExceptions()
        collector._psutil = MagicMock()
        collector._psutil.NoSuchProcess = mock_exceptions.NoSuchProcess
        collector._psutil.AccessDenied = mock_exceptions.AccessDenied
        collector._psutil.ZombieProcess = mock_exceptions.ZombieProcess
        collector._psutil.Process.side_effect = mock_exceptions.ZombieProcess(1234)

        with patch("os.listdir", return_value=["1234"]):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_pid_reuse_protection(self):
        """Test PID reuse detection via start_time tracking."""
        collector = ProcessesCollector(interval_seconds=10.0)
        collector._prev_cpu_times = {
            1234: (100.0, 50.0, 1000.0),
        }

        file_contents = {
            "/proc/1234/stat": "1234 (new_process) S 1 1 1 1 1 1 1 1 1 1 200 300 10 5 0 1 0 0 2000000 200000 100 100 0 0 0 0 0 0 0 0 0 0\n",
            "/proc/1234/cmdline": "new_process\x00",
            "/proc/1234/status": "Uid:\t1000\t1000\t1000\t1000\n",
        }

        with patch("os.listdir", return_value=["1234"]):
            with patch("builtins.open", side_effect=create_mock_open(file_contents)):
                with patch("os.readlink", return_value="/usr/bin/new_process"):
                    with patch("os.cpu_count", return_value=4):
                        with patch("app.collectors.processes.ProcessesCollector._get_boot_time", return_value=0.0):
                            with patch.dict("sys.modules", {"pwd": get_mock_pwd()}):
                                import asyncio
                                result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].name == "new_process"
        assert result[0].cpu_percent == 0.0

    def test_cpu_percentage_calculation(self):
        """Test CPU percentage calculation using monotonic time."""
        collector = ProcessesCollector(interval_seconds=10.0)
        collector._prev_cpu_times = {
            1234: (100.0, 50.0, 1000.0),
        }

        file_contents = {
            "/proc/1234/stat": "1234 (test_process) S 1 1 1 1 1 1 1 1 1 1 200 300 10 5 0 1 0 0 1000000 100000 100 100 0 0 0 0 0 0 0 0 0 0\n",
            "/proc/1234/cmdline": "test_process\x00",
            "/proc/1234/status": "Uid:\t1000\t1000\t1000\t1000\n",
        }

        with patch("os.listdir", return_value=["1234"]):
            with patch("builtins.open", side_effect=create_mock_open(file_contents)):
                with patch("os.readlink", return_value="/usr/bin/test_process"):
                    with patch("os.cpu_count", return_value=4):
                        with patch("app.collectors.processes.ProcessesCollector._get_boot_time", return_value=0.0):
                            with patch.dict("sys.modules", {"pwd": get_mock_pwd()}):
                                with patch("time.monotonic", return_value=1010.0):
                                    import asyncio
                                    result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert 0.0 <= result[0].cpu_percent <= 400.0

    def test_malformed_proc_stat(self):
        """Test handling of malformed /proc/[pid]/stat."""
        collector = ProcessesCollector(interval_seconds=10.0)

        file_contents = {
            "/proc/1234/stat": "1234 (test) S 1 1\n",
        }

        with patch("os.listdir", return_value=["1234"]):
            with patch("builtins.open", side_effect=create_mock_open(file_contents)):
                import asyncio
                result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_missing_proc_directory(self):
        """Test handling of missing /proc directory."""
        collector = ProcessesCollector(interval_seconds=10.0)

        with patch("os.listdir", side_effect=FileNotFoundError()):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_command_name_fallback(self):
        """Test fallback to cmdline when exe not available."""
        collector = ProcessesCollector(interval_seconds=10.0)

        file_contents = {
            "/proc/1234/stat": "1234 (test_process) S 1 1 1 1 1 1 1 1 1 1 100 200 10 5 0 1 0 0 1000000 100000 100 100 0 0 0 0 0 0 0 0 0 0\n",
            "/proc/1234/cmdline": "fallback_cmd\x00arg1\x00",
            "/proc/1234/status": "Uid:\t1000\t1000\t1000\t1000\n",
        }

        with patch("os.listdir", return_value=["1234"]):
            with patch("builtins.open", side_effect=create_mock_open(file_contents)):
                with patch("os.readlink", side_effect=FileNotFoundError()):
                    with patch("os.cpu_count", return_value=4):
                        with patch("app.collectors.processes.ProcessesCollector._get_boot_time", return_value=0.0):
                            with patch.dict("sys.modules", {"pwd": get_mock_pwd()}):
                                import asyncio
                                result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].name == "fallback_cmd"
