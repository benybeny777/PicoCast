import pytest


def test_classify_playlist_category_accepts_exact_candidate(monkeypatch):
    import core.genre_playlist_classifier as gpc

    request_args = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"category":"食べ物カテゴリ","reason":"食品の歴史が中心"}'}

    monkeypatch.setattr("core.opening_quality.ensure_ollama_server", lambda: None)
    def fake_post(*args, **kwargs):
        request_args.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(gpc.requests, "post", fake_post)

    result = gpc.classify_playlist_category(
        title="チョコレートの歴史",
        description="",
        script_text="チョコレートは昔、飲み物でした。",
        categories=("食べ物カテゴリ", "都市伝説カテゴリ"),
    )

    assert result["category"] == "食べ物カテゴリ"
    assert "食品" in result["reason"]
    assert request_args["json"]["think"] is False
    assert request_args["json"]["options"]["num_predict"] == gpc.cfg.OLLAMA_PLAYLIST_NUM_PREDICT
    assert request_args["timeout"] == gpc.cfg.OLLAMA_PLAYLIST_TIMEOUT_SEC


def test_classify_playlist_category_rejects_unknown_candidate(monkeypatch):
    import core.genre_playlist_classifier as gpc
    from core.error_codes import AppError

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"category":"勝手に作ったカテゴリ","reason":"近そう"}'}

    monkeypatch.setattr("core.opening_quality.ensure_ollama_server", lambda: None)
    monkeypatch.setattr(gpc.requests, "post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(AppError) as exc:
        gpc.classify_playlist_category(
            title="テスト",
            categories=("食べ物カテゴリ",),
        )

    assert exc.value.code == "E-PLAYLIST-CLASSIFY"


def test_classify_playlist_category_reports_timeout(monkeypatch):
    import core.genre_playlist_classifier as gpc
    from core.error_codes import AppError

    monkeypatch.setattr("core.opening_quality.ensure_ollama_server", lambda: None)

    def raise_timeout(*args, **kwargs):
        raise gpc.requests.exceptions.ReadTimeout("timed out")

    monkeypatch.setattr(gpc.requests, "post", raise_timeout)

    with pytest.raises(AppError) as exc:
        gpc.classify_playlist_category(
            title="八尺様とはどんな怪談なのか",
            categories=("日本の怪談",),
        )

    assert exc.value.code == "E-PLAYLIST-CLASSIFY"
    assert "秒以内に完了しませんでした" in str(exc.value)
