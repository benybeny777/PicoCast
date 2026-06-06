from core.error_codes import AppError
from core.user_log import sanitize_process_log_message, user_facing_error_message


def test_sanitize_process_log_removes_multiline_traceback():
    message = (
        "Ollama判定に失敗しました。\n"
        "Traceback (most recent call last):\n"
        '  File "core/example.py", line 10, in run\n'
        "TimeoutError: timed out"
    )

    assert sanitize_process_log_message(message) == "Ollama判定に失敗しました。"


def test_sanitize_process_log_removes_inline_traceback():
    message = (
        "エラー: API呼び出し失敗 Traceback (most recent call last): "
        'File "core/example.py", line 10, in run TimeoutError'
    )

    assert sanitize_process_log_message(message) == "エラー: API呼び出し失敗"


def test_sanitize_process_log_replaces_traceback_only_message():
    message = 'Traceback (most recent call last):\n  File "core/example.py", line 10'

    assert sanitize_process_log_message(message) == "処理に失敗しました。詳細はデバッグログを確認してください。"


def test_user_facing_error_message_includes_app_error_remediation():
    error = AppError("E-PLAYLIST-TARGET", detail="対象: Long_テスト")

    message = user_facing_error_message(error)

    assert message.startswith("[E-PLAYLIST-TARGET]")
    assert "対処:" in message
    assert "Traceback" not in message


def test_web_job_log_sanitizes_traceback(monkeypatch):
    import core.metadata_db as metadata_db
    import web_app.job_manager as job_manager

    saved = []
    monkeypatch.setattr(metadata_db, "append_job_logs", lambda job_id, entries: saved.extend(entries))
    job = type("JobStub", (), {
        "job_id": "job-1",
        "profile_id": None,
        "logs": [],
        "progress_text": "",
    })()

    job_manager._log(
        job,
        "判定失敗\nTraceback (most recent call last):\n  File \"x.py\", line 1",
        "error",
    )

    assert job.logs[0]["message"] == "判定失敗"
    assert saved[0]["message"] == "判定失敗"
