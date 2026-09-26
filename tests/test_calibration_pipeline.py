import pytest

from intrader.calibration_pipeline import CalibrationPipelineError, run_calibration


class EmptyStore:
    def load_completed_shadow_bundles(self):
        return ()


def test_calibration_pipeline_reports_pending_for_insufficient_history() -> None:
    with pytest.raises(CalibrationPipelineError, match="pending"):
        run_calibration(EmptyStore())
