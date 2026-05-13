"""
tests/test_kpi_initial.py

Hand-written baseline tests for the initial 3 KPI features.
These represent the test suite BEFORE the agent runs.

After running the agent, test_generated_kpi.py will cover the new features.

Paper reference: Section 5.1 — "Initially, three feature nodes and their
corresponding test cases are present in the KG."
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from kpi_app.kpi import (
    calculate_cell_availability,
    check_rsrp_signal,
    check_call_drop_rate,
)


# ── Feature 1: Cell Availability ──────────────────────────────────────────────

class TestCellAvailability:

    def test_full_availability(self):
        """Cell with no downtime should be 100% available."""
        result = calculate_cell_availability(
            total_time_minutes=1440,
            downtime_minutes=0
        )
        assert result == 100.0

    def test_typical_availability(self):
        """1 hour downtime in a day should give ~93.75%."""
        result = calculate_cell_availability(
            total_time_minutes=1440,
            downtime_minutes=90
        )
        assert abs(result - 93.75) < 0.01

    def test_zero_total_time_raises(self):
        """Zero total time should raise ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            calculate_cell_availability(
                total_time_minutes=0,
                downtime_minutes=0
            )

    def test_negative_downtime_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            calculate_cell_availability(
                total_time_minutes=100,
                downtime_minutes=-10
            )

    def test_downtime_exceeds_total_raises(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            calculate_cell_availability(
                total_time_minutes=100,
                downtime_minutes=150
            )

    def test_five_nines_availability(self):
        """Five nines = 99.999% availability."""
        total = 365 * 24 * 60  # minutes in a year
        downtime = total * 0.00001
        result = calculate_cell_availability(total, downtime)
        assert result > 99.99


# ── Feature 2: RSRP Signal Quality ───────────────────────────────────────────

class TestRSRPSignal:

    def test_excellent_signal(self):
        result = check_rsrp_signal(-75.0)
        assert result["quality"] == "excellent"
        assert result["acceptable"] is True

    def test_good_signal(self):
        result = check_rsrp_signal(-85.0)
        assert result["quality"] == "good"
        assert result["acceptable"] is True

    def test_fair_signal(self):
        result = check_rsrp_signal(-95.0)
        assert result["quality"] == "fair"
        assert result["acceptable"] is True

    def test_poor_signal(self):
        result = check_rsrp_signal(-105.0)
        assert result["quality"] == "poor"
        assert result["acceptable"] is False

    def test_no_signal(self):
        result = check_rsrp_signal(-130.0)
        assert result["quality"] == "no_signal"
        assert result["acceptable"] is False

    def test_boundary_excellent_good(self):
        """Exactly at -90 dBm boundary should be 'good'."""
        result = check_rsrp_signal(-90.0)
        assert result["quality"] == "good"

    def test_boundary_poor_threshold(self):
        """Exactly at -110 dBm boundary should be 'poor'."""
        result = check_rsrp_signal(-110.0)
        assert result["quality"] == "poor"
        assert result["acceptable"] is False

    def test_result_contains_value(self):
        rsrp = -88.5
        result = check_rsrp_signal(rsrp)
        assert result["value"] == rsrp


# ── Feature 3: Call Drop Rate ─────────────────────────────────────────────────

class TestCallDropRate:

    def test_within_sla(self):
        result = check_call_drop_rate(
            dropped_calls=10,
            total_calls=1000
        )
        assert result["within_sla"] is True
        assert abs(result["drop_rate"] - 1.0) < 0.001

    def test_exceeds_sla(self):
        result = check_call_drop_rate(
            dropped_calls=50,
            total_calls=1000
        )
        assert result["within_sla"] is False
        assert result["drop_rate"] == 5.0

    def test_exactly_at_threshold(self):
        """Exactly at 2.0% threshold should be within SLA."""
        result = check_call_drop_rate(
            dropped_calls=20,
            total_calls=1000,
            threshold_percent=2.0
        )
        assert result["within_sla"] is True

    def test_zero_drops(self):
        result = check_call_drop_rate(dropped_calls=0, total_calls=500)
        assert result["drop_rate"] == 0.0
        assert result["within_sla"] is True

    def test_custom_threshold(self):
        result = check_call_drop_rate(
            dropped_calls=30,
            total_calls=1000,
            threshold_percent=5.0
        )
        assert result["within_sla"] is True

    def test_zero_total_calls_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            check_call_drop_rate(dropped_calls=0, total_calls=0)

    def test_drops_exceed_total_raises(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            check_call_drop_rate(dropped_calls=100, total_calls=50)

    def test_result_structure(self):
        result = check_call_drop_rate(dropped_calls=5, total_calls=100)
        assert "drop_rate" in result
        assert "threshold" in result
        assert "within_sla" in result
        assert "message" in result
