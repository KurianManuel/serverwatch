"""Temperature collector."""

import glob
import os

from app.collectors.base import Collector


class TemperatureSensorData:
    """Temperature sensor data structure."""

    def __init__(self) -> None:
        self.name: str = ""
        self.label: str = ""
        self.current: float = 0.0
        self.high: float | None = None
        self.critical: float | None = None
        self.unit: str = "celsius"


class TemperatureCollector(Collector[list[TemperatureSensorData]]):
    """Temperature metrics collector."""

    name = "temperature"

    def __init__(self, interval_seconds: float = 10.0) -> None:
        super().__init__(interval_seconds)
        self._sensor_paths: list[tuple[str, str, str, float | None, float | None]] = []
        self._discover_sensors()

    def _discover_sensors(self) -> None:
        """Discover available temperature sensors."""
        self._sensor_paths = []

        # Check thermal zones (/sys/class/thermal)
        thermal_base = "/sys/class/thermal"
        if os.path.isdir(thermal_base):
            for zone in sorted(os.listdir(thermal_base)):
                if not zone.startswith("thermal_zone"):
                    continue
                zone_path = os.path.join(thermal_base, zone)
                temp_file = os.path.join(zone_path, "temp")
                label_file = os.path.join(zone_path, "type")
                trip_point_files = glob.glob(os.path.join(zone_path, "trip_point_*_temp"))

                if os.path.exists(temp_file):
                    label = zone
                    if os.path.exists(label_file):
                        try:
                            with open(label_file) as f:
                                label = f.read().strip()
                        except Exception:
                            pass

                    high_thresh = None
                    critical_thresh = None

                    # Read trip points for thresholds
                    for trip_file in trip_point_files:
                        try:
                            with open(trip_file) as f:
                                temp = int(f.read().strip())
                                temp_c = temp / 1000.0
                                if "trip_point_1" in trip_file and high_thresh is None:
                                    high_thresh = temp_c
                                if "trip_point_2" in trip_file and critical_thresh is None:
                                    critical_thresh = temp_c
                        except Exception:
                            pass

                    self._sensor_paths.append((
                        zone,
                        label,
                        temp_file,
                        high_thresh,
                        critical_thresh
                    ))

        # Check hwmon sensors (/sys/class/hwmon)
        hwmon_base = "/sys/class/hwmon"
        if os.path.isdir(hwmon_base):
            for hwmon in sorted(os.listdir(hwmon_base)):
                hwmon_path = os.path.join(hwmon_base, hwmon)
                name_file = os.path.join(hwmon_path, "name")

                # Find all temp*_input files
                temp_inputs = sorted(glob.glob(os.path.join(hwmon_path, "temp*_input")))
                for temp_input in temp_inputs:
                    base_name = os.path.basename(temp_input).replace("_input", "")
                    label_file = os.path.join(hwmon_path, f"{base_name}_label")
                    max_file = os.path.join(hwmon_path, f"{base_name}_max")
                    crit_file = os.path.join(hwmon_path, f"{base_name}_crit")

                    label = base_name
                    if os.path.exists(name_file):
                        try:
                            with open(name_file) as f:
                                hwmon_name = f.read().strip()
                                label = f"{hwmon_name} {base_name}"
                        except Exception:
                            pass

                    if os.path.exists(label_file):
                        try:
                            with open(label_file) as f:
                                label = f.read().strip()
                        except Exception:
                            pass

                    high_thresh = None
                    critical_thresh = None

                    if os.path.exists(max_file):
                        try:
                            with open(max_file) as f:
                                high_thresh = int(f.read().strip()) / 1000.0
                        except Exception:
                            pass

                    if os.path.exists(crit_file):
                        try:
                            with open(crit_file) as f:
                                critical_thresh = int(f.read().strip()) / 1000.0
                        except Exception:
                            pass

                    self._sensor_paths.append((
                        f"{hwmon}_{base_name}",
                        label,
                        temp_input,
                        high_thresh,
                        critical_thresh
                    ))

    def _read_temperature(self, temp_file: str) -> float | None:
        """Read temperature from file (millidegrees C to degrees C)."""
        try:
            with open(temp_file) as f:
                temp = int(f.read().strip())
                return temp / 1000.0
        except Exception:
            return None

    async def _collect(self) -> list[TemperatureSensorData]:
        result: list[TemperatureSensorData] = []

        for sensor_name, label, temp_file, high_thresh, critical_thresh in self._sensor_paths:
            temp = self._read_temperature(temp_file)
            if temp is None:
                continue

            sensor_data = TemperatureSensorData()
            sensor_data.name = sensor_name
            sensor_data.label = label
            sensor_data.current = temp
            sensor_data.high = high_thresh
            sensor_data.critical = critical_thresh
            sensor_data.unit = "celsius"
            result.append(sensor_data)

        return result
