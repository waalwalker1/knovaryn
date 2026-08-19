"""Regression tests: real pipeline kill/resume (defect 4.8)."""

import pytest


@pytest.mark.skip(reason="Durable pipeline not yet implemented")
class TestRealPipelineKillResume:
    """Process-level kill and resume with checkpoint recovery."""

    async def test_worker_kill_resume(self):
        """Kill worker during generation, verify resume and no duplicate calls."""
        pytest.fail("Durable pipeline not yet implemented")

    async def test_final_output_matches_clean_run(self):
        """Clean run and recovered run must produce same output."""
        pytest.fail("Durable pipeline not yet implemented")
