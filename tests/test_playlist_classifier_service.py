import threading
from types import SimpleNamespace


def _job():
    return SimpleNamespace(
        cancel_event=threading.Event(),
        logs=[],
        progress_text="",
        job_id="test-job",
    )


def test_classifier_saves_unregistered_result(monkeypatch):
    import core.genre_playlist_classifier as classifier
    import core.metadata_db as metadata_db
    import core.playlist_resolver as playlist_resolver
    import web_app.security as security
    from web_app.services import playlist_classifier_service as service

    saved = {}
    monkeypatch.setattr(security, "find_history_dir", lambda name: f"C:/output/{name}")
    monkeypatch.setattr(playlist_resolver, "get_standard_categories", lambda: ("学校怪談", "身近な恐怖"))
    monkeypatch.setattr(metadata_db, "get_render_info", lambda name: {
        "video_title": "八尺様とはどんな怪談なのか",
        "description": "都市伝説の解説",
        "playlist_categories": [],
    })
    monkeypatch.setattr(metadata_db, "get_script_content", lambda name: "八尺様の怪談を説明する台本")
    monkeypatch.setattr(
        metadata_db,
        "update_playlist_categories",
        lambda name, categories: saved.update({"name": name, "categories": categories}),
    )
    monkeypatch.setattr(
        classifier,
        "classify_playlist_category",
        lambda **kwargs: {"category": "学校怪談", "reason": "怪談が中心"},
    )
    monkeypatch.setattr(service, "_log", lambda *args, **kwargs: None)

    result = service._run_playlist_classifier(_job(), ["Long_八尺様"], True)

    assert saved == {"name": "Long_八尺様", "categories": ["学校怪談"]}
    assert result["results"][0]["category"] == "学校怪談"
    assert result["skipped"] == 0


def test_classifier_skips_registered_when_requested(monkeypatch):
    import core.genre_playlist_classifier as classifier
    import core.metadata_db as metadata_db
    import core.playlist_resolver as playlist_resolver
    import web_app.security as security
    from web_app.services import playlist_classifier_service as service

    called = {"classifier": False}
    monkeypatch.setattr(security, "find_history_dir", lambda name: f"C:/output/{name}")
    monkeypatch.setattr(playlist_resolver, "get_standard_categories", lambda: ("学校怪談",))
    monkeypatch.setattr(metadata_db, "get_render_info", lambda name: {
        "playlist_categories": ["学校怪談"],
    })
    monkeypatch.setattr(
        classifier,
        "classify_playlist_category",
        lambda **kwargs: called.update({"classifier": True}),
    )
    monkeypatch.setattr(service, "_log", lambda *args, **kwargs: None)

    result = service._run_playlist_classifier(_job(), ["Long_八尺様"], True)

    assert called["classifier"] is False
    assert result["results"] == []
    assert result["skipped"] == 1
