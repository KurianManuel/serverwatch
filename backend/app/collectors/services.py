"""Systemd services collector."""

from typing import Any

from app.collectors.base import Collector


class ServiceData:
    """Service data structure."""

    def __init__(self) -> None:
        self.name: str = ""
        self.description: str = ""
        self.active_state: str = ""  # active, inactive, activating, deactivating, failed
        self.sub_state: str = ""
        self.load_state: str = ""  # loaded, not-found, error, etc.
        self.unit_file_state: str = ""  # enabled, disabled, static, etc.
        self.main_pid: int = 0
        self.active_enter_timestamp: float | None = None
        self.inactive_enter_timestamp: float | None = None


class ServicesCollector(Collector[list[ServiceData]]):
    """Systemd services collector."""

    name = "services"

    def __init__(self, interval_seconds: float = 10.0) -> None:
        super().__init__(interval_seconds)
        self._prev_states: dict[str, str] = {}
        self._use_dbus = False
        self._dbus: Any = None
        self._systemd: Any = None
        self._init_dbus()

    def _init_dbus(self) -> None:
        """Initialize D-Bus connection to systemd."""
        try:
            import dbus  # type: ignore[import-not-found]
            self._dbus = dbus
            bus = dbus.SystemBus()
            systemd = bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
            self._systemd = dbus.Interface(systemd, "org.freedesktop.systemd1.Manager")
            self._use_dbus = True
        except Exception:
            self._use_dbus = False
            self._systemd = None

    def _get_unit_properties(self, unit_name: str) -> dict[str, Any] | None:
        """Get unit properties via D-Bus."""
        if not self._use_dbus or not self._systemd:
            return None

        try:
            unit_path = self._systemd.GetUnit(unit_name)
            unit_obj = self._dbus.SystemBus().get_object("org.freedesktop.systemd1", unit_path)
            props = self._dbus.Interface(unit_obj, "org.freedesktop.DBus.Properties")
            return props.GetAll("org.freedesktop.systemd1.Unit")  # type: ignore[no-any-return]
        except Exception:
            return None

    def _get_service_properties(self, unit_name: str) -> dict[str, Any] | None:
        """Get service-specific properties via D-Bus."""
        if not self._use_dbus or not self._systemd:
            return None

        try:
            unit_path = self._systemd.GetUnit(unit_name)
            unit_obj = self._dbus.SystemBus().get_object("org.freedesktop.systemd1", unit_path)
            props = self._dbus.Interface(unit_obj, "org.freedesktop.DBus.Properties")
            return props.GetAll("org.freedesktop.systemd1.Service")  # type: ignore[no-any-return]
        except Exception:
            return None

    def _collect_via_dbus(self) -> list[ServiceData]:
        """Collect service information via D-Bus."""
        result: list[ServiceData] = []

        try:
            # List all units
            units = self._systemd.ListUnits()
            for unit in units:
                # unit is (name, description, load_state, active_state, sub_state, ...)
                if len(unit) < 5:
                    continue

                unit_name = str(unit[0])
                if not unit_name.endswith(".service"):
                    continue

                description = str(unit[1])
                load_state = str(unit[2])
                active_state = str(unit[3])
                sub_state = str(unit[4])

                # Get additional properties
                unit_props = self._get_unit_properties(unit_name)
                service_props = self._get_service_properties(unit_name)

                main_pid = 0
                active_enter_ts = None
                inactive_enter_ts = None
                unit_file_state = ""

                if unit_props:
                    main_pid = int(unit_props.get("MainPID", 0))
                    # Convert D-Bus timestamps (microseconds since epoch)
                    if "ActiveEnterTimestamp" in unit_props:
                        active_enter_ts = float(unit_props["ActiveEnterTimestamp"]) / 1_000_000
                    if "InactiveEnterTimestamp" in unit_props:
                        inactive_enter_ts = float(unit_props["InactiveEnterTimestamp"]) / 1_000_000

                if service_props:
                    # Unit file state
                    if "LoadState" in service_props:
                        unit_file_state = str(service_props["LoadState"])

                svc = ServiceData()
                svc.name = unit_name
                svc.description = description
                svc.active_state = active_state
                svc.sub_state = sub_state
                svc.load_state = load_state
                svc.unit_file_state = unit_file_state
                svc.main_pid = main_pid
                svc.active_enter_timestamp = active_enter_ts
                svc.inactive_enter_timestamp = inactive_enter_ts

                # Track state changes for event generation
                prev_active = self._prev_states.get(unit_name)
                if prev_active is not None and prev_active != active_state:
                    # State changed - could emit event in future phase
                    pass
                self._prev_states[unit_name] = active_state

                result.append(svc)
        except Exception as e:
            raise RuntimeError(f"D-Bus collection failed: {e}") from e

        return result

    async def _collect(self) -> list[ServiceData]:
        if not self._use_dbus or not self._systemd:
            raise RuntimeError("D-Bus unavailable: cannot collect systemd services")
        return self._collect_via_dbus()
