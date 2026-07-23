"""Unit tests for info models."""

import dataclasses

import pytest

from archcare.utils.info_models import (
    CpuInfo,
    DiskUsageInfo,
    MemoryInfo,
    MirrorlistInfo,
    ServiceStatusInfo,
)

# ---------------------------------------------------------------------------
# ServiceStatusInfo
# ---------------------------------------------------------------------------


class TestServiceStatusInfo:
    def test_defaults(self):
        info = ServiceStatusInfo()
        assert info.loaded is False
        assert info.active == "unknown"
        assert info.running is False
        assert info.description == ""
        assert info.main_pid is None

    def test_custom(self):
        info = ServiceStatusInfo(
            loaded=True, active="active", running=True, description="test", main_pid=123
        )
        assert info.loaded is True
        assert info.active == "active"
        assert info.running is True
        assert info.description == "test"
        assert info.main_pid == 123

    def test_is_frozen(self):
        info = ServiceStatusInfo(
            loaded=True, active="active", running=True, description="test", main_pid=123
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.loaded = False  # ty:ignore[invalid-assignment]


# ---------------------------------------------------------------------------
# DiskUsageInfo
# ---------------------------------------------------------------------------


class TestDiskUsageInfo:
    def test_defaults(self):
        info = DiskUsageInfo()
        assert info.path == "/"
        assert info.total == 0
        assert info.used == 0
        assert info.free == 0
        assert info.percent == 0.0

    def test_custom(self):
        info = DiskUsageInfo(path="/home", total=100, used=50, free=50, percent=50.0)
        assert info.path == "/home"
        assert info.total == 100
        assert info.used == 50
        assert info.free == 50
        assert info.percent == 50.0

    def test_is_frozen(self):
        info = DiskUsageInfo(path="/home", total=100, used=50, free=50, percent=50.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.path = "/tmp"  # ty:ignore[invalid-assignment]


# ---------------------------------------------------------------------------
# MemoryInfo
# ---------------------------------------------------------------------------


class TestMemoryInfo:
    def test_defaults(self):
        info = MemoryInfo()
        assert info.total == 0
        assert info.used == 0
        assert info.percent == 0.0
        assert info.swap_total == 0
        assert info.swap_used == 0
        assert info.swap_percent == 0.0

    def test_custom(self):
        info = MemoryInfo(
            total=100,
            used=50,
            percent=50.0,
            swap_total=200,
            swap_used=100,
            swap_percent=50.0,
        )
        assert info.total == 100
        assert info.used == 50
        assert info.percent == 50.0
        assert info.swap_total == 200
        assert info.swap_used == 100
        assert info.swap_percent == 50.0

    def test_is_frozen(self):
        info = MemoryInfo(
            total=100,
            used=50,
            percent=50.0,
            swap_total=200,
            swap_used=100,
            swap_percent=50.0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.total = 0  # ty:ignore[invalid-assignment]


# ---------------------------------------------------------------------------
# CpuInfo
# ---------------------------------------------------------------------------


class TestCpuInfo:
    def test_defaults(self):
        info = CpuInfo()
        assert info.cores is None
        assert info.percent == 0.0
        assert info.load_avg is None

    def test_custom(self):
        info = CpuInfo(
            cores=4,
            percent=50.0,
            load_avg=(1.0, 2.0, 3.0),
        )
        assert info.cores == 4
        assert info.percent == 50.0
        assert info.load_avg == (1.0, 2.0, 3.0)

    def test_is_frozen(self):
        info = CpuInfo()
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.cores = 24  # ty:ignore[invalid-assignment]


# ---------------------------------------------------------------------------
# MirrorlistInfo
# ---------------------------------------------------------------------------


class TestMirrorlistInfo:
    def test_defaults(self):
        info = MirrorlistInfo()
        assert info.total_mirrors == 0
        assert info.protocols == set()
        assert info.last_modified is None

    def test_custom(self):
        info = MirrorlistInfo(
            total_mirrors=10,
            protocols={"http", "https"},
            last_modified="2026-01-01",
        )
        assert info.total_mirrors == 10
        assert info.protocols == {"http", "https"}
        assert info.last_modified == "2026-01-01"

    def test_is_frozen(self):
        info = MirrorlistInfo()
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.total_mirrors = 10  # ty:ignore[invalid-assignment]
