"""読み違いの可能性の検出（VOICEVOX の kana と辞書の読みの比較）のテスト。実際の VOICEVOX は呼ばない。"""
import time
from types import SimpleNamespace

import pytest

from core import reading_dictionary_store as store
from core.reading_check import Finding, ReadingChecker, clean_voicevox_kana, pronunciation_key


@pytest.fixture(autouse=True)
def _own_dictionary_db(monkeypatch, tmp_path):
    """辞書・検出結果はテストごとに別の settings.db にする（登録したものが次のテストへ残らないように）。"""
    import core.settings_store as settings_store
    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))


@pytest.fixture(scope="module")
def checker():
    return ReadingChecker()


@pytest.mark.parametrize(
    ("text", "kana", "expected"),
    [
        # 漢字の語で読みが食い違う → 出す
        ("辛いのだ。", "カ'ライノダ", [("辛い", "つらい", "からい")]),
        ("今日は生物の話", "キョ'ーワ/ナマモノノ/ハナシ", [("生物", "せいぶつ", "なまもの")]),
        # 長音・助詞（は→ワ、へ→エ）の表記の違いだけ → 出さない
        ("東京へ行くのだ！", "トーキョーエ/イ'クノダ", []),
        ("先生は思うのだ", "センセ'ーワ/オモ'ウノダ", []),
        ("3つの方法", "ミッツノ/ホ'ーホー", []),
        # 英字は辞書の読みが無いので比べない（前後の漢字語を誤って出さない）
        ("VOICEVOXで東京", "ボイスボ'ックスデ/トーキョー", []),
        # かなだけの語は VOICEVOX がそのまま読むので出さない
        ("ずんだもちなのだ", "ズンダモ'チナノダ", []),
    ],
)
def test_compare(checker, text, kana, expected):
    found = [(f.word, f.expected_reading, f.voicevox_reading) for f in checker.compare(text, kana)]
    assert found == expected


def test_pronunciation_key_keeps_length_and_merges_long_vowels():
    assert clean_voicevox_kana("ト'ーキョー/_スル？") == "トーキョースル"
    assert pronunciation_key("トウキョウ") == pronunciation_key("トーキョー")
    assert pronunciation_key("センセイ") == pronunciation_key("センセー")
    assert len(pronunciation_key("トウキョウ")) == len("トウキョウ")


def _finding(word="辛い", voiced="からい", expected="つらい"):
    return Finding(word, expected, voiced, f"{word}のだ")


def test_record_list_and_count():
    assert store.record_findings([_finding()], "動画A") == 1
    assert store.record_findings([_finding()], "動画B") == 1
    [row] = [r for r in store.list_findings() if r["word"] == "辛い"]
    assert row["seen_count"] == 2 and row["source"] == "動画B"


def test_accept_registers_dictionary_and_clears():
    store.record_findings([_finding("生物", "なまもの", "せいぶつ")], "動画")
    store.accept_finding("生物", "せいぶつ")
    assert store.load_dict("base")["生物"] == "せいぶつ"
    assert not [r for r in store.list_findings() if r["word"] == "生物"]


def test_dismissed_stays_hidden_when_seen_again():
    finding = _finding("方", "かた", "ほう")
    store.record_findings([finding], "動画")
    assert store.dismiss_finding("方", "かた")
    assert store.record_findings([finding], "動画") == 0
    assert not [r for r in store.list_findings() if r["word"] == "方"]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NVF_DISABLE_JOB_RUNNER", "1")
    import core.metadata_db as m
    db_path = str(tmp_path / "metadata.db")
    monkeypatch.setattr(m, "get_db_path", lambda: db_path)
    m.initialize_db()
    from fastapi.testclient import TestClient
    from web_app.app import app
    with TestClient(app) as c:
        yield c


def _wait(client, job_id):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("success", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError("ジョブが終わりません")


def _fake_voicevox(monkeypatch, kana_by_text, *, up=True):
    import core.audio_backends as audio_backends
    from core.voicevox import VoicevoxAPI

    monkeypatch.setattr(audio_backends, "resolve_audio_speaker",
                        lambda profile_id, character, emotion="ノーマル": SimpleNamespace(backend="voicevox", speaker_id=3))
    monkeypatch.setattr(VoicevoxAPI, "check_connection", lambda self: up)
    monkeypatch.setattr(VoicevoxAPI, "audio_query_only", lambda self, text, speaker_id, **k: ({}, kana_by_text[text]))


def test_script_check_finds_misreading_without_synthesis(client, monkeypatch):
    # 元の文（漢字のまま）を VOICEVOX へ渡して読みを取る
    _fake_voicevox(monkeypatch, {"辛いのだ。": "カ'ライノダ", "東京へ行く！": "トーキョーエ/イ'ク"})
    script = "ずんだもん(ノーマル): 辛いのだ。東京へ行く！\n背景: 夜の街"
    job = _wait(client, client.post("/api/reading-check", json={"script": script}).json()["job_id"])
    assert job["status"] == "success"
    assert job["result"]["checked"] == 2
    assert job["result"]["findings"] == [
        {"word": "辛い", "voicevox_reading": "からい", "expected_reading": "つらい", "text": "辛いのだ。"}
    ]
    listed = client.get("/api/reading-check/findings").json()["findings"]
    assert any(f["word"] == "辛い" for f in listed)
    assert client.post("/api/reading-check/findings/accept", json={"word": "辛い", "reading": "からい"}).status_code == 200
    assert store.load_dict("base")["辛い"] == "からい"


def test_script_check_requires_voicevox(client, monkeypatch):
    _fake_voicevox(monkeypatch, {}, up=False)
    job = _wait(client, client.post("/api/reading-check", json={"script": "ずんだもん(ノーマル): 辛いのだ"}).json()["job_id"])
    assert job["status"] == "failed" and "E-VOICEVOX-DOWN" in job["error"]


def test_empty_script_and_unknown_dismiss(client):
    assert client.post("/api/reading-check", json={"script": " "}).status_code == 400
    assert client.post("/api/reading-check/findings/dismiss", json={"word": "無い", "voicevox_reading": "ない"}).status_code == 404


def test_words_fixed_by_base_dictionary_are_not_reported(monkeypatch):
    from core.reading_check import check_and_record

    store.upsert_entry("base", "辛", "から")
    found = check_and_record([("辛いのだ。", "カ'ライノダ"), ("今日は生物の話", "キョ'ーワ/ナマモノノ/ハナシ")], "動画")
    assert [f.word for f in found] == ["生物"]
