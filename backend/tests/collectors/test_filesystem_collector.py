"""Tests for Filesystem collector edge cases."""

from unittest.mock import MagicMock, mock_open, patch

from app.collectors.filesystem import FilesystemCollector


def create_mock_open(file_contents: dict):
    """Create a mock open that returns different content based on file path."""
    def mock_open_func(path, *args, **kwargs):
        if path in file_contents:
            return mock_open(read_data=file_contents[path])(path, *args, **kwargs)
        return mock_open(read_data="")(path, *args, **kwargs)
    return mock_open_func


def make_statvfs_mock(f_blocks=10000000, f_frsize=4096, f_bavail=5000000, f_bfree=6000000, f_files=1000000, f_favail=500000):
    """Create a properly configured statvfs mock."""
    mock = MagicMock()
    mock.f_blocks = f_blocks
    mock.f_frsize = f_frsize
    mock.f_bavail = f_bavail
    mock.f_bfree = f_bfree
    mock.f_files = f_files
    mock.f_favail = f_favail
    return mock


def patch_statvfs(mock_statvfs):
    """Patch os.statvfs at the module level, adding it if it doesn't exist (Windows)."""
    return patch.dict("os.__dict__", {"statvfs": mock_statvfs})


class TestFilesystemCollector:
    """Test Filesystem collector edge cases."""

    def test_valid_filesystem(self):
        """Test valid filesystem mount."""
        collector = FilesystemCollector(interval_seconds=30.0)
        collector._use_psutil = False  # Disable psutil for this test

        file_contents = {
            "/proc/mounts": "/dev/sda1 / ext4 rw,relatime 0 0\n",
        }
        mock_statvfs = make_statvfs_mock()

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch_statvfs(lambda _: mock_statvfs):
                import asyncio
                result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].mount_point == "/"
        assert result[0].device == "/dev/sda1"
        assert result[0].fstype == "ext4"
        assert result[0].total == 10000000 * 4096
        assert result[0].available == 5000000 * 4096
        assert result[0].utilization_pct > 0
        assert result[0].inodes_total == 1000000
        assert result[0].inodes_free == 500000
        assert result[0].inodes_used == 500000

    def test_inaccessible_filesystem(self):
        """Test inaccessible filesystem (permission error)."""
        collector = FilesystemCollector(interval_seconds=30.0)
        collector._use_psutil = False  # Disable psutil for this test

        file_contents = {
            "/proc/mounts": "/dev/sda1 / ext4 rw,relatime 0 0\n",
        }

        mock_statvfs = MagicMock(side_effect=PermissionError())

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch_statvfs(mock_statvfs):
                import asyncio
                result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_missing_mount(self):
        """Test handling of missing /proc/mounts."""
        collector = FilesystemCollector(interval_seconds=30.0)

        def mock_open_func(path, *args, **kwargs):
            if path == "/proc/mounts":
                raise FileNotFoundError()
            return mock_open(read_data="")(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0

    def test_virtual_filesystems_filtered(self):
        """Test that virtual filesystems are filtered out."""
        collector = FilesystemCollector(interval_seconds=30.0)
        collector._use_psutil = False  # Disable psutil for this test

        file_contents = {
            "/proc/mounts": (
                "/dev/sda1 / ext4 rw,relatime 0 0\n"
                "proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0\n"
                "sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0\n"
                "tmpfs /run tmpfs rw,nosuid,nodev,relatime 0 0\n"
                "devtmpfs /dev devtmpfs rw,nosuid,relatime,size=1024k 0 0\n"
                "cgroup2 /sys/fs/cgroup cgroup2 rw,nosuid,nodev,noexec,relatime 0 0\n"
            ),
        }
        mock_statvfs = make_statvfs_mock()

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch_statvfs(lambda _: mock_statvfs):
                import asyncio
                result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].mount_point == "/"

    def test_inode_info_unavailable(self):
        """Test when inode information is unavailable."""
        collector = FilesystemCollector(interval_seconds=30.0)
        collector._use_psutil = False  # Disable psutil for this test

        file_contents = {
            "/proc/mounts": "/dev/sda1 / ext4 rw,relatime 0 0\n",
        }
        mock_statvfs = make_statvfs_mock(f_files=0, f_favail=0)

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch_statvfs(lambda _: mock_statvfs):
                import asyncio
                result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].inodes_total == 0
        assert result[0].inodes_free == 0
        assert result[0].inodes_used == 0

    def test_psutil_fallback(self):
        """Test psutil fallback when statvfs fails."""
        collector = FilesystemCollector(interval_seconds=30.0)
        collector._use_psutil = True
        collector._psutil = MagicMock()

        file_contents = {
            "/proc/mounts": "/dev/sda1 / ext4 rw,relatime 0 0\n",
        }
        mock_usage = MagicMock()
        mock_usage.total = 40000000000
        mock_usage.used = 20000000000
        mock_usage.free = 20000000000
        collector._psutil.disk_usage.return_value = mock_usage

        # Make os.statvfs raise an error to trigger psutil fallback
        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            with patch_statvfs(MagicMock(side_effect=OSError("statvfs failed"))):
                import asyncio
                result = asyncio.run(collector._collect())

        assert len(result) == 1
        assert result[0].total == 40000000000
        assert result[0].used == 20000000000
        assert result[0].available == 20000000000
        assert result[0].utilization_pct == 50.0

    def test_malformed_mounts_line(self):
        """Test handling of malformed mount line."""
        collector = FilesystemCollector(interval_seconds=30.0)

        file_contents = {
            "/proc/mounts": "malformed line\n",
        }

        with patch("builtins.open", side_effect=create_mock_open(file_contents)):
            import asyncio
            result = asyncio.run(collector._collect())

        assert len(result) == 0
