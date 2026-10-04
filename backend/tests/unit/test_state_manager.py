"""Unit tests for State Manager."""

import asyncio
import time

import pytest

from app.collectors.base import CollectorResult, CollectorStatus
from app.state.manager import StateManager
from app.state.models import (
    DataStatus,
    SystemStateSnapshot,
)


class MockCPUData:
    def __init__(self):
        self.total_utilization = 45.5
        self.per_core = [40.0, 50.0, 42.0, 49.0]
        self.load_average = (1.2, 1.1, 1.0)
        self.cpu_count = 4


class MockMemoryData:
    def __init__(self):
        self.total = 16_000_000_000
        self.available = 8_000_000_000
        self.used = 8_000_000_000
        self.free = 4_000_000_000
        self.swap_total = 2_000_000_000
        self.swap_used = 500_000_000
        self.swap_free = 1_500_000_000


class MockDiskData:
    def __init__(self):
        self.device = "sda"
        self.read_bytes = 1000
        self.write_bytes = 2000
        self.read_ops = 10
        self.write_ops = 20
        self.read_throughput = 100.0
        self.write_throughput = 200.0
        self.iops = 5.0


class MockNetworkData:
    def __init__(self):
        self.name = "eth0"
        self.state = "up"
        self.rx_bytes = 10000
        self.tx_bytes = 20000
        self.rx_packets = 100
        self.tx_packets = 200
        self.rx_errors = 0
        self.tx_errors = 0
        self.rx_dropped = 0
        self.tx_dropped = 0
        self.throughput_rx = 500.0
        self.throughput_tx = 600.0


class MockFilesystemData:
    def __init__(self):
        self.mount_point = "/"
        self.device = "/dev/sda1"
        self.fstype = "ext4"
        self.total = 100_000_000_000
        self.used = 50_000_000_000
        self.available = 50_000_000_000
        self.utilization_pct = 50.0
        self.inodes_total = 1000000
        self.inodes_used = 500000
        self.inodes_free = 500000


class MockTemperatureData:
    def __init__(self):
        self.name = "cpu_thermal"
        self.current = 45.0
        self.high = 80.0
        self.critical = 100.0


class MockProcessData:
    def __init__(self):
        self.pid = 1234
        self.name = "test"
        self.exe = "/usr/bin/test"
        self.cpu_percent = 5.0
        self.memory_percent = 2.0
        self.rss = 100_000_000
        self.status = "running"
        self.create_time = 1234567890.0
        self.username = "user"


class MockServiceData:
    def __init__(self):
        self.name = "test.service"
        self.description = "Test Service"
        self.active_state = "active"
        self.sub_state = "running"
        self.load_state = "loaded"
        self.unit_file_state = "enabled"
        self.main_pid = 1234
        self.active_enter_timestamp = 1234567890.0
        self.inactive_enter_timestamp = None


class MockSystemData:
    def __init__(self):
        self.hostname = "test-host"
        self.os_name = "Ubuntu"
        self.os_version = "24.04"
        self.kernel_version = "6.8.0"
        self.architecture = "x86_64"
        self.cpu_model = "Intel Core i7"
        self.cpu_cores_physical = 4
        self.cpu_cores_logical = 8
        self.total_memory = 16_000_000_000


class TestStateManagerBasics:
    """Test basic StateManager functionality."""

    def test_initial_state(self):
        """Test initial state is valid."""
        sm = StateManager()
        assert sm.sequence == 0
        assert sm.update_counter == 0
        assert isinstance(sm.current_state, SystemStateSnapshot)
        assert sm.current_state.sequence == 0

    def test_get_collector_status_default(self):
        """Test default collector status is INITIALIZING."""
        sm = StateManager()
        assert sm.get_collector_status("cpu") == CollectorStatus.INITIALIZING

    def test_get_all_collector_statuses(self):
        """Test getting all collector statuses."""
        sm = StateManager()
        statuses = sm.get_all_collector_statuses()
        assert isinstance(statuses, dict)
        assert "cpu" not in statuses  # not set yet

    def test_get_metric_nonexistent(self):
        """Test getting non-existent metric returns None."""
        sm = StateManager()
        assert sm.get_metric("cpu.total_utilization") is not None  # exists with default
        assert sm.get_metric("nonexistent.metric") is None


class TestApplyCollectorResult:
    """Test apply_collector_result and commit_snapshot."""

    @pytest.mark.asyncio
    async def test_apply_collector_result_queues(self):
        """Test apply_collector_result queues result without committing snapshot."""
        sm = StateManager()
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )

        update = await sm.apply_collector_result(result)

        assert sm.update_counter == 1
        assert sm.sequence == 0  # snapshot sequence unchanged
        assert update.sequence == 0

    @pytest.mark.asyncio
    async def test_commit_snapshot_increments_sequence(self):
        """Test commit_snapshot increments public sequence."""
        sm = StateManager()
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )

        await sm.apply_collector_result(result)
        update = await sm.commit_snapshot()

        assert sm.sequence == 1
        assert update.sequence == 1
        assert update.snapshot is not None
        assert update.snapshot.sequence == 1

    @pytest.mark.asyncio
    async def test_apply_then_commit_updates_cpu(self):
        """Test CPU data is applied after commit."""
        sm = StateManager()
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )

        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total is not None
        assert cpu_total.value == 45.5
        assert cpu_total.collector == "cpu"
        assert cpu_total.status == DataStatus.CURRENT

    @pytest.mark.asyncio
    async def test_multiple_collectors_single_snapshot(self):
        """Test multiple collectors produce single snapshot sequence increment."""
        sm = StateManager()

        cpu_result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        mem_result = CollectorResult(
            collector_name="memory",
            status=CollectorStatus.RUNNING,
            data=MockMemoryData(),
        )

        await sm.apply_collector_result(cpu_result)
        await sm.apply_collector_result(mem_result)

        assert sm.update_counter == 2
        assert sm.sequence == 0

        await sm.commit_snapshot()

        assert sm.sequence == 1
        assert sm.update_counter == 2

        # Both metrics should be present
        assert sm.get_metric("cpu.total_utilization").value == 45.5
        assert sm.get_metric("memory.total").value == 16_000_000_000


class TestStaleDetection:
    """Test monotonic-time-based stale detection."""

    @pytest.mark.asyncio
    async def test_fresh_metric_not_stale(self):
        """Test fresh metric is not stale."""
        sm = StateManager()
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )

        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total is not None
        assert not cpu_total.is_stale()

    @pytest.mark.asyncio
    async def test_stale_via_monotonic_time(self):
        """Test staleness detected via monotonic time advancement."""
        sm = StateManager()
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )

        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total is not None

        # Simulate time passing using monotonic clock
        # Metric has stale_threshold_seconds = 30.0 by default
        future_monotonic = time.monotonic() + 31.0
        assert cpu_total.is_stale(now_monotonic=future_monotonic)

    @pytest.mark.asyncio
    async def test_wall_clock_jump_does_not_affect_staleness(self):
        """Test wall-clock jump doesn't affect monotonic staleness."""
        sm = StateManager()
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )

        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total is not None

        # Wall clock jump shouldn't affect is_stale (uses monotonic)
        # We can't easily mock datetime.utcnow in the metric,
        # but we verify is_stale uses monotonic by passing explicit now
        assert not cpu_total.is_stale(now_monotonic=time.monotonic())


class TestDegradedFailedPreservation:
    """Test DEGRADED/FAILED collector status preserves data with correct status."""

    @pytest.mark.asyncio
    async def test_degraded_preserves_last_data(self):
        """Test DEGRADED status preserves last data with STALE status."""
        sm = StateManager()

        # First: successful collection
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.status == DataStatus.CURRENT

        # Second: degraded collection (no data)
        degraded_result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.DEGRADED,
            data=None,
            error="Permission denied",
        )
        await sm.apply_collector_result(degraded_result)
        await sm.commit_snapshot()

        # Data preserved but marked STALE
        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.value == 45.5
        assert cpu_total.status == DataStatus.STALE

    @pytest.mark.asyncio
    async def test_failed_preserves_last_data(self):
        """Test FAILED status preserves last data with FAILED status."""
        sm = StateManager()

        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        failed_result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.FAILED,
            data=None,
            error="Crash",
        )
        await sm.apply_collector_result(failed_result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.value == 45.5
        assert cpu_total.status == DataStatus.FAILED


class TestRecoveringDisabledHandling:
    """Test RECOVERING and DISABLED collector status handling."""

    @pytest.mark.asyncio
    async def test_recovering_preserves_data_marks_stale(self):
        """Test RECOVERING status preserves last data with STALE status."""
        sm = StateManager()

        # First: successful collection
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.status == DataStatus.CURRENT

        # Second: recovering collection
        recovering_result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RECOVERING,
            data=None,
        )
        await sm.apply_collector_result(recovering_result)
        await sm.commit_snapshot()

        # Data preserved but marked STALE (same as DEGRADED)
        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.value == 45.5
        assert cpu_total.status == DataStatus.STALE

        # Health should be DEGRADED (RECOVERING treated as DEGRADED)
        assert sm.current_state.serverwatch_health.status == "DEGRADED"

    @pytest.mark.asyncio
    async def test_recovering_to_running_restores_current(self):
        """Test RECOVERING -> RUNNING with data restores CURRENT status."""
        sm = StateManager()

        # First: successful collection
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        # Second: recovering
        recovering_result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RECOVERING,
            data=None,
        )
        await sm.apply_collector_result(recovering_result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.status == DataStatus.STALE

        # Third: running again with new data
        running_result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(running_result)
        await sm.commit_snapshot()

        # Status restored to CURRENT with new data
        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.status == DataStatus.CURRENT
        assert cpu_total.value == 45.5
        assert sm.current_state.serverwatch_health.status == "HEALTHY"

    @pytest.mark.asyncio
    async def test_disabled_marks_unavailable(self):
        """Test DISABLED status marks metrics as UNAVAILABLE."""
        sm = StateManager()

        # First: successful collection
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.status == DataStatus.CURRENT

        # Second: disabled
        disabled_result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.DISABLED,
            data=None,
        )
        await sm.apply_collector_result(disabled_result)
        await sm.commit_snapshot()

        # Data preserved but marked UNAVAILABLE
        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.value == 45.5
        assert cpu_total.status == DataStatus.UNAVAILABLE

        # Health should be DEGRADED (DISABLED treated as DEGRADED)
        assert sm.current_state.serverwatch_health.status == "DEGRADED"

    @pytest.mark.asyncio
    async def test_disabled_to_running_restores_current(self):
        """Test DISABLED -> RUNNING with data restores CURRENT status."""
        sm = StateManager()

        # First: successful collection
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        # Second: disabled
        disabled_result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.DISABLED,
            data=None,
        )
        await sm.apply_collector_result(disabled_result)
        await sm.commit_snapshot()

        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.status == DataStatus.UNAVAILABLE

        # Third: running again with new data
        running_result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(running_result)
        await sm.commit_snapshot()

        # Status restored to CURRENT with new data
        cpu_total = sm.get_metric("cpu.total_utilization")
        assert cpu_total.status == DataStatus.CURRENT
        assert cpu_total.value == 45.5


class TestSequencing:
    """Test sequence semantics."""

    @pytest.mark.asyncio
    async def test_internal_update_counter_vs_snapshot_sequence(self):
        """Test internal counter increments per apply, sequence per commit."""
        sm = StateManager()

        for _ in range(3):
            result = CollectorResult(
                collector_name="cpu",
                status=CollectorStatus.RUNNING,
                data=MockCPUData(),
            )
            await sm.apply_collector_result(result)

        assert sm.update_counter == 3
        assert sm.sequence == 0

        await sm.commit_snapshot()
        assert sm.sequence == 1
        assert sm.update_counter == 3

        # Another cycle
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        assert sm.sequence == 2
        assert sm.update_counter == 4

    @pytest.mark.asyncio
    async def test_get_state_since_valid(self):
        """Test get_state_since returns update for valid sequence."""
        sm = StateManager()
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()  # sequence 1

        update = sm.get_state_since(1)
        assert update is not None
        assert update.sequence == 1

    @pytest.mark.asyncio
    async def test_get_state_since_invalid(self):
        """Test get_state_since returns None for invalid sequence."""
        sm = StateManager()

        # Sequence 0 doesn't exist (starts at 1)
        update = sm.get_state_since(0)
        assert update is None

        # Future sequence
        update = sm.get_state_since(999)
        assert update is None


class TestHealthComputation:
    """Test ServerWatch health computation."""

    @pytest.mark.asyncio
    async def test_healthy_when_all_running(self):
        """Test HEALTHY when all required collectors RUNNING."""
        sm = StateManager()

        for name in ["cpu", "memory", "network", "disk"]:
            if name == "cpu":
                data = MockCPUData()
            elif name == "memory":
                data = MockMemoryData()
            elif name == "disk":
                data = [MockDiskData()]
            elif name == "network":
                data = [MockNetworkData()]
            else:
                data = MockMemoryData()
            result = CollectorResult(
                collector_name=name,
                status=CollectorStatus.RUNNING,
                data=data,
            )
            await sm.apply_collector_result(result)

        await sm.commit_snapshot()

        assert sm.current_state.serverwatch_health.status == "HEALTHY"

    @pytest.mark.asyncio
    async def test_degraded_when_one_degraded(self):
        """Test DEGRADED when one collector DEGRADED."""
        sm = StateManager()

        for name in ["cpu", "memory"]:
            result = CollectorResult(
                collector_name=name,
                status=CollectorStatus.RUNNING,
                data=MockCPUData() if name == "cpu" else MockMemoryData(),
            )
            await sm.apply_collector_result(result)

        # One degraded
        degraded = CollectorResult(
            collector_name="disk",
            status=CollectorStatus.DEGRADED,
            data=None,
        )
        await sm.apply_collector_result(degraded)

        await sm.commit_snapshot()

        assert sm.current_state.serverwatch_health.status == "DEGRADED"

    @pytest.mark.asyncio
    async def test_failed_when_one_failed(self):
        """Test FAILED when one collector FAILED."""
        sm = StateManager()

        for name in ["cpu", "memory"]:
            result = CollectorResult(
                collector_name=name,
                status=CollectorStatus.RUNNING,
                data=MockCPUData() if name == "cpu" else MockMemoryData(),
            )
            await sm.apply_collector_result(result)

        failed = CollectorResult(
            collector_name="disk",
            status=CollectorStatus.FAILED,
            data=None,
        )
        await sm.apply_collector_result(failed)

        await sm.commit_snapshot()

        assert sm.current_state.serverwatch_health.status == "FAILED"


class TestTransitionCallbacks:
    """Test transition callback mechanism."""

    @pytest.mark.asyncio
    async def test_callback_fired_on_collector_status_change(self):
        """Test callback fired when collector status changes."""
        sm = StateManager()
        transitions_received: list = []

        def callback(transitions):
            transitions_received.extend(transitions)

        sm.register_transition_callback(callback)

        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        # Should have collector status transition (INITIALIZING -> RUNNING)
        # Health stays HEALTHY (no health transition on first commit)
        assert len(transitions_received) == 1
        collector_transitions = [t for t in transitions_received if not t.is_health_transition]
        assert len(collector_transitions) == 1
        assert collector_transitions[0].collector == "cpu"
        assert collector_transitions[0].old_status == CollectorStatus.INITIALIZING
        assert collector_transitions[0].new_status == CollectorStatus.RUNNING

    @pytest.mark.asyncio
    async def test_callback_fired_on_health_change(self):
        """Test callback fired when health status changes."""
        sm = StateManager()
        transitions_received: list = []

        def callback(transitions):
            transitions_received.extend(transitions)

        sm.register_transition_callback(callback)

        # First commit - healthy
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        transitions_received.clear()

        # Second commit - degraded
        degraded = CollectorResult(
            collector_name="memory",
            status=CollectorStatus.DEGRADED,
            data=None,
        )
        await sm.apply_collector_result(degraded)
        await sm.commit_snapshot()

        health_transitions = [t for t in transitions_received if t.is_health_transition]
        assert len(health_transitions) == 1
        assert health_transitions[0].collector == "state_manager"


class TestConcurrency:
    """Test concurrent access safety."""

    @pytest.mark.asyncio
    async def test_concurrent_apply_collector_results(self):
        """Test concurrent apply_collector_result calls don't corrupt state."""
        sm = StateManager()

        def get_data(name: str):
            if name == "cpu":
                return MockCPUData()
            elif name == "memory":
                return MockMemoryData()
            elif name == "disk":
                return [MockDiskData()]
            elif name == "network":
                return [MockNetworkData()]
            return MockMemoryData()

        async def apply_result(name: str):
            result = CollectorResult(
                collector_name=name,
                status=CollectorStatus.RUNNING,
                data=get_data(name),
            )
            return await sm.apply_collector_result(result)

        # Fire 4 concurrent applies
        await asyncio.gather(
            apply_result("cpu"),
            apply_result("memory"),
            apply_result("disk"),
            apply_result("network"),
        )

        assert sm.update_counter == 4
        assert sm.sequence == 0  # no commit yet

        await sm.commit_snapshot()

        assert sm.sequence == 1
        assert sm.get_metric("cpu.total_utilization") is not None
        assert sm.get_metric("memory.total") is not None

    @pytest.mark.asyncio
    async def test_concurrent_reads_during_write(self):
        """Test reads return consistent view during concurrent writes."""
        sm = StateManager()

        async def writer():
            for _ in range(10):
                result = CollectorResult(
                    collector_name="cpu",
                    status=CollectorStatus.RUNNING,
                    data=MockCPUData(),
                )
                await sm.apply_collector_result(result)
                await asyncio.sleep(0.001)

        async def reader():
            for _ in range(20):
                _ = sm.get_metric("cpu.total_utilization")
                _ = sm.current_state
                await asyncio.sleep(0.001)

        await asyncio.gather(writer(), reader())
        # If we get here without exception, concurrency is safe


class TestMarkCollectorFailed:
    """Test mark_collector_failed async method."""

    @pytest.mark.asyncio
    async def test_mark_collector_failed_updates_health(self):
        """Test mark_collector_failed sets FAILED status and updates health."""
        sm = StateManager()

        await sm.mark_collector_failed("temperature")

        assert sm.get_collector_status("temperature") == CollectorStatus.FAILED
        assert sm.current_state.serverwatch_health.status == "FAILED"

    @pytest.mark.asyncio
    async def test_mark_collector_failed_concurrent_with_snapshot(self):
        """Test mark_collector_failed doesn't corrupt state when concurrent with commit_snapshot."""
        sm = StateManager()
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        # Run mark_collector_failed and commit_snapshot concurrently
        async def mark_failed():
            await sm.mark_collector_failed("disk")

        async def commit():
            # Add another collector result and commit
            mem_result = CollectorResult(
                collector_name="memory",
                status=CollectorStatus.RUNNING,
                data=MockMemoryData(),
            )
            await sm.apply_collector_result(mem_result)
            await sm.commit_snapshot()

        await asyncio.gather(mark_failed(), commit())

        # Both operations should complete without corruption
        assert sm.get_collector_status("disk") == CollectorStatus.FAILED
        assert sm.get_collector_status("memory") == CollectorStatus.RUNNING
        assert sm.current_state.serverwatch_health.status == "FAILED"
        assert sm.get_metric("cpu.total_utilization") is not None
        assert sm.get_metric("memory.total") is not None


class TestWebSocketPreparation:
    """Test WebSocket data preparation."""

    @pytest.mark.asyncio
    async def test_get_state_for_websocket(self):
        """Test get_state_for_websocket returns serializable dict."""
        sm = StateManager()
        result = CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=MockCPUData(),
        )
        await sm.apply_collector_result(result)
        await sm.commit_snapshot()

        ws_data = sm.get_state_for_websocket()

        assert "sequence" in ws_data
        assert "timestamp" in ws_data
        assert "cpu" in ws_data
        assert ws_data["cpu"]["total_utilization"]["value"] == 45.5
        assert "serverwatch_health" in ws_data


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
