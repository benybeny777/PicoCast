"""
背景画像生成APIエラー（特に 503 API混雑）の分類・記録・非フォールバックのテスト。
外部API実通信なし。
"""
import os
import sys
import tempfile

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── HTTPステータス分類 ────────────────────────────────────────────────────────

def test_classify_image_api_error_categories():
    from core.image_generator import classify_image_api_error

    class _Coded(Exception):
        def __init__(self, msg, code):
            super().__init__(msg)
            self.code = code

    assert classify_image_api_error(_Coded("high demand", 503)) == ("api_busy", 503)
    assert classify_image_api_error(_Coded("denied", 403)) == ("auth", 403)
    assert classify_image_api_error(_Coded("rate", 429)) == ("quota", 429)
    # メッセージ埋め込みからの抽出
    assert classify_image_api_error(Exception("503 UNAVAILABLE")) == ("api_busy", 503)
    assert classify_image_api_error(Exception("401 UNAUTHENTICATED")) == ("auth", 401)
    assert classify_image_api_error(Exception("something weird")) == ("generic", None)


def test_image_generation_error_retry_recommended():
    from core.image_generator import ImageGenerationError
    assert ImageGenerationError("x", category="api_busy").retry_recommended is True
    assert ImageGenerationError("x", category="quota").retry_recommended is True
    assert ImageGenerationError("x", category="auth").retry_recommended is False
    assert ImageGenerationError("x", category="generic").retry_recommended is False


# ── generate_background が 503 で ImageGenerationError を上げ、フォールバックしない ──

class _FakeModels:
    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        raise self._exc


class _FakeClient:
    def __init__(self, exc):
        self.models = _FakeModels(exc)

    def close(self):
        pass


def _nanobanana_generator():
    """キー検証を通さずに nanobanana モードの ImageGenerator を組み立てる。"""
    from core.image_generator import ImageGenerator
    ig = ImageGenerator(width=1080, height=1920, background_engine="sd_webui")
    ig.background_engine = "nanobanana"
    return ig


def test_generate_background_503_raises_api_busy_without_fallback(tmp_path):
    from core.image_generator import ImageGenerationError

    class _Err(Exception):
        def __init__(self):
            super().__init__("503 UNAVAILABLE high demand")
            self.code = 503

    ig = _nanobanana_generator()
    ig.client = _FakeClient(_Err())

    with pytest.raises(ImageGenerationError) as ei:
        ig.generate_background("テスト背景", target_dir=str(tmp_path), raw=True)

    err = ei.value
    assert err.category == "api_busy"
    assert err.status_code == 503
    assert err.model  # モデル名が入る
    assert err.retry_recommended is True
    # 自動フォールバック禁止: generate_content は1回だけ（別モデル/別バックエンドへ切替しない）
    assert ig.client.models.calls == 1


def test_generate_background_failure_keeps_existing_backgrounds(tmp_path):
    """1枚失敗しても、既に生成済みの背景ファイルは破棄しない。"""
    from core.image_generator import ImageGenerationError

    existing = tmp_path / "bg_001_001.png"
    existing.write_bytes(b"already-generated")

    class _Err(Exception):
        def __init__(self):
            super().__init__("503 UNAVAILABLE")
            self.code = 503

    ig = _nanobanana_generator()
    ig.client = _FakeClient(_Err())

    with pytest.raises(ImageGenerationError):
        ig.generate_background("テスト背景", target_dir=str(tmp_path), fname="bg_002_001.png", raw=True)

    # 既存背景は残っている / 失敗分のファイルは作られていない
    assert existing.exists()
    assert existing.read_bytes() == b"already-generated"
    assert not (tmp_path / "bg_002_001.png").exists()


# ── 失敗記録の DB 保存（_meta JSON は作らない） ───────────────────────────────

def test_image_generation_failure_persisted_to_db(monkeypatch):
    import core.metadata_db as m
    db_path = os.path.join(tempfile.mkdtemp(), "metadata.db")
    monkeypatch.setattr(m, "get_db_path", lambda: db_path)
    m.initialize_db()

    m.record_image_generation_failure("Shorts_天津飯", {
        "failed_index": 4,
        "total_backgrounds": 8,
        "model": "gemini-3.1-flash-image-preview",
        "backend": "nanobanana",
        "status_code": 503,
        "category": "api_busy",
        "error_message": "503 UNAVAILABLE high demand",
        "prompt": "背景プロンプト",
        "retry_recommended": True,
    })

    failures = m.get_image_generation_failures("Shorts_天津飯")
    assert len(failures) == 1
    f = failures[0]
    assert f["failed_index"] == 4
    assert f["total_backgrounds"] == 8
    assert f["category"] == "api_busy"
    assert f["status_code"] == 503
    assert f["retry_recommended"] == 1
    assert f["failed_at"]

    # 再生成開始時のクリアで消える
    m.clear_image_generation_failures("Shorts_天津飯")
    assert m.get_image_generation_failures("Shorts_天津飯") == []


def test_clear_single_failure_index(monkeypatch):
    """指定背景番号だけ失敗記録をクリアできること（その背景の再生成成功時に使う）。"""
    import core.metadata_db as m
    db_path = os.path.join(tempfile.mkdtemp(), "metadata.db")
    monkeypatch.setattr(m, "get_db_path", lambda: db_path)
    m.initialize_db()
    for idx in (4, 6):
        m.record_image_generation_failure("Shorts_x", {
            "failed_index": idx, "total_backgrounds": 8, "model": "g", "backend": "nanobanana",
            "status_code": 503, "category": "api_busy", "error_code": "E-IMG-BUSY",
            "error_message": "503", "prompt": "p", "retry_recommended": True,
        })
    m.clear_image_generation_failure("Shorts_x", 4)
    remaining = [f["failed_index"] for f in m.get_image_generation_failures("Shorts_x")]
    assert remaining == [6]
