from intrader.reasoning_pipeline import AuditShadowResult


def test_audit_result_tracks_inserted_rows() -> None:
    result = AuditShadowResult((), 0)

    assert result.audits == ()
    assert result.inserted_rows == 0
