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

TOTAL = 100
USED = 50
FREE = 50
PERCENT = 50.0

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
        MAIN_PID = 123
        info = ServiceStatusInfo(
            loaded=True, active="active", running=True, description="test", main_pid=MAIN_PID
        )
        assert info.loaded is True
        assert info.active == "active"
        assert info.running is True
        assert info.description == "test"
        assert info.main_pid == MAIN_PID

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
        info = DiskUsageInfo(path="/home", total=TOTAL, used=USED, free=FREE, percent=PERCENT)
        assert info.path == "/home"
        assert info.total == TOTAL
        assert info.used == USED
        assert info.free == FREE
        assert info.percent == PERCENT

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
        SWAP_TOTAL = 200
        SWAP_USED = 100
        SWAP_PERCENT = 50.0
        info = MemoryInfo(
            total=TOTAL,
            used=USED,
            percent=PERCENT,
            swap_total=SWAP_TOTAL,
            swap_used=SWAP_USED,
            swap_percent=SWAP_PERCENT,
        )
        assert info.total == TOTAL
        assert info.used == USED
        assert info.percent == PERCENT
        assert info.swap_total == SWAP_TOTAL
        assert info.swap_used == SWAP_USED
        assert info.swap_percent == SWAP_PERCENT

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
        CORES = 4
        info = CpuInfo(
            cores=4,
            percent=50.0,
            load_avg=(1.0, 2.0, 3.0),
        )
        assert info.cores == CORES
        assert info.percent == PERCENT
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
        TOTAL_MIRRORS = 10
        info = MirrorlistInfo(
            total_mirrors=10,
            protocols={"http", "https"},
            last_modified="2026-01-01",
        )
        assert info.total_mirrors == TOTAL_MIRRORS
        assert info.protocols == {"http", "https"}
        assert info.last_modified == "2026-01-01"

    def test_is_frozen(self):
        info = MirrorlistInfo()
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.total_mirrors = 10  # ty:ignore[invalid-assignment]
