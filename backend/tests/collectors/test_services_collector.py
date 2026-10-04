"""Tests for Services collector edge cases."""

from unittest.mock import MagicMock, patch

from app.collectors.base import CollectorStatus
from app.collectors.services import ServicesCollector


class TestServicesCollector:
    """Test Services collector edge cases."""

    def test_dbus_unavailable(self):
        """Test D-Bus unavailable (non-Linux or no systemd)."""
        collector = ServicesCollector(interval_seconds=10.0)

        import asyncio
        result = asyncio.run(collector.collect())

        assert result.status == CollectorStatus.DEGRADED
        assert result.data is None
        assert "D-Bus unavailable" in result.error

    def test_dbus_error(self):
        """Test D-Bus connection error."""
        collector = ServicesCollector(interval_seconds=10.0)

        mock_dbus = MagicMock()
        mock_dbus.SystemBus.side_effect = Exception("Connection refused")

        with patch.dict("sys.modules", {"dbus": mock_dbus}):
            import asyncio
            result = asyncio.run(collector.collect())

        assert result.status == CollectorStatus.DEGRADED
        assert result.data is None
        assert "D-Bus unavailable" in result.error

    def test_valid_service_enumeration(self):
        """Test valid service enumeration via D-Bus."""
        collector = ServicesCollector(interval_seconds=10.0)

        mock_dbus = MagicMock()
        mock_systemd = MagicMock()
        mock_bus = MagicMock()
        mock_unit_obj = MagicMock()
        mock_props = MagicMock()

        mock_dbus.SystemBus.return_value = mock_bus
        mock_bus.get_object.return_value = mock_unit_obj
        mock_dbus.Interface.return_value = mock_props

        mock_systemd.ListUnits.return_value = [
            ("sshd.service", "OpenSSH Server", "loaded", "active", "running", "/usr/lib/systemd/system/sshd.service"),
            ("nginx.service", "Nginx Web Server", "loaded", "active", "running", "/usr/lib/systemd/system/nginx.service"),
            ("invalid.timer", "Timer Unit", "loaded", "active", "waiting", "/usr/lib/systemd/system/invalid.timer"),
        ]

        mock_systemd.GetUnit.side_effect = [
            "/org/freedesktop/systemd1/unit/sshd_2eservice",
            "/org/freedesktop/systemd1/unit/nginx_2eservice",
        ]

        def get_all_props(interface):
            if interface == "org.freedesktop.systemd1.Unit":
                return {
                    "MainPID": 1234,
                    "ActiveEnterTimestamp": 1000000000000000,
                    "InactiveEnterTimestamp": 0,
                }
            elif interface == "org.freedesktop.systemd1.Service":
                return {"LoadState": "loaded"}
            return {}

        mock_props.GetAll.side_effect = get_all_props

        with patch.dict("sys.modules", {"dbus": mock_dbus}):
            collector._dbus = mock_dbus
            collector._systemd = mock_systemd
            collector._use_dbus = True

            import asyncio
            result = asyncio.run(collector.collect())

        assert result.status == CollectorStatus.RUNNING
        assert result.data is not None
        assert len(result.data) == 2
        assert result.data[0].name == "sshd.service"
        assert result.data[0].active_state == "active"
        assert result.data[0].sub_state == "running"
        assert result.data[0].main_pid == 1234
        assert result.data[0].unit_file_state == "loaded"

    def test_non_service_units_filtered(self):
        """Test that non-.service units are filtered out."""
        collector = ServicesCollector(interval_seconds=10.0)

        mock_dbus = MagicMock()
        mock_systemd = MagicMock()

        mock_systemd.ListUnits.return_value = [
            ("sshd.service", "SSH", "loaded", "active", "running", "/path"),
            ("systemd-tmpfiles.timer", "Timer", "loaded", "active", "waiting", "/path"),
            ("network.target", "Target", "loaded", "active", "active", "/path"),
            ("docker.socket", "Socket", "loaded", "active", "listening", "/path"),
            ("invalid.service", "Invalid Service", "loaded", "failed", "failed", "/path"),
        ]

        mock_systemd.GetUnit.return_value = "/org/freedesktop/systemd1/unit/sshd_2eservice"
        mock_props = MagicMock()
        mock_props.GetAll.return_value = {"MainPID": 0, "LoadState": "loaded"}
        mock_dbus.Interface.return_value = mock_props
        mock_dbus.SystemBus.return_value = MagicMock()

        with patch.dict("sys.modules", {"dbus": mock_dbus}):
            collector._dbus = mock_dbus
            collector._systemd = mock_systemd
            collector._use_dbus = True

            import asyncio
            result = asyncio.run(collector.collect())

        assert result.status == CollectorStatus.RUNNING
        assert len(result.data) == 2
        names = [s.name for s in result.data]
        assert "sshd.service" in names
        assert "invalid.service" in names
        assert "systemd-tmpfiles.timer" not in names
        assert "network.target" not in names
        assert "docker.socket" not in names

    def test_service_state_parsing(self):
        """Test various service state combinations."""
        collector = ServicesCollector(interval_seconds=10.0)

        mock_dbus = MagicMock()
        mock_systemd = MagicMock()

        mock_systemd.ListUnits.return_value = [
            ("active.service", "Active", "loaded", "active", "running", "/path"),
            ("inactive.service", "Inactive", "loaded", "inactive", "dead", "/path"),
            ("failed.service", "Failed", "loaded", "failed", "failed", "/path"),
            ("activating.service", "Activating", "loaded", "activating", "auto-restart", "/path"),
        ]

        mock_systemd.GetUnit.return_value = "/org/freedesktop/systemd1/unit/active_2eservice"
        mock_props = MagicMock()
        mock_props.GetAll.return_value = {"MainPID": 1234, "LoadState": "loaded"}
        mock_dbus.Interface.return_value = mock_props
        mock_dbus.SystemBus.return_value = MagicMock()

        with patch.dict("sys.modules", {"dbus": mock_dbus}):
            collector._dbus = mock_dbus
            collector._systemd = mock_systemd
            collector._use_dbus = True

            import asyncio
            result = asyncio.run(collector.collect())

        assert result.status == CollectorStatus.RUNNING
        assert len(result.data) == 4

        states = {s.name: (s.active_state, s.sub_state) for s in result.data}
        assert states["active.service"] == ("active", "running")
        assert states["inactive.service"] == ("inactive", "dead")
        assert states["failed.service"] == ("failed", "failed")
        assert states["activating.service"] == ("activating", "auto-restart")

    def test_state_change_tracking(self):
        """Test service state change tracking."""
        collector = ServicesCollector(interval_seconds=10.0)

        mock_dbus = MagicMock()
        mock_systemd = MagicMock()

        mock_systemd.ListUnits.return_value = [
            ("test.service", "Test", "loaded", "inactive", "dead", "/path"),
        ]
        mock_systemd.GetUnit.return_value = "/path"
        mock_props = MagicMock()
        mock_props.GetAll.return_value = {"MainPID": 0, "LoadState": "loaded"}
        mock_dbus.Interface.return_value = mock_props
        mock_dbus.SystemBus.return_value = MagicMock()

        with patch.dict("sys.modules", {"dbus": mock_dbus}):
            collector._dbus = mock_dbus
            collector._systemd = mock_systemd
            collector._use_dbus = True

            import asyncio
            result1 = asyncio.run(collector.collect())

        mock_systemd.ListUnits.return_value = [
            ("test.service", "Test", "loaded", "active", "running", "/path"),
        ]
        mock_props.GetAll.return_value = {"MainPID": 5678, "LoadState": "loaded", "ActiveEnterTimestamp": 2000000000000000}

        with patch.dict("sys.modules", {"dbus": mock_dbus}):
            result2 = asyncio.run(collector.collect())

        assert result1.status == CollectorStatus.RUNNING
        assert result2.status == CollectorStatus.RUNNING
        assert result1.data[0].active_state == "inactive"
        assert result2.data[0].active_state == "active"
        assert result2.data[0].main_pid == 5678
