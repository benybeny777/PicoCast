"""
冒頭レビュー（Ollama）の採点パース・警告表示・採点デバッグDB保存のテスト。
外部API実通信なし。
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── 採点結果のパース ──────────────────────────────────────────────────────────

def test_normalize_review_result_parses_subscores_and_fix_target():
    from core.opening_quality import _normalize_review_result

    raw = {
        "overall_score": 78,
        "publish_ok": True,
        "rewrite_recommended": True,
        "must_fix": [],
        "warnings": ["冒頭の引きがやや弱い。2行目を具体例に置き換える"],
        "scores": {"hook": 74, "title_match": 90, "tempo": 82, "clarity": 86, "loop": 78, "cta": 75},
        "fix_target": "hook",
    }
    r = _normalize_review_result(raw, "ollama", "qwen3:8b")
    assert r["overall_score"] == 78
    assert r["scores"]["hook"] == 74
    assert r["scores"]["clarity"] == 86
    assert r["fix_target"] == "hook"
    assert r["must_fix"] == []
    assert any("2行目" in w for w in r["warnings"])


def test_normalize_review_result_legacy_score_fallback():
    """旧スキーマ（score のみ）でも overall_score に反映されること。"""
    from core.opening_quality import _normalize_review_result
    r = _normalize_review_result({"score": 85}, "ollama", "qwen3:8b")
    assert r["overall_score"] == 85


def test_opening_review_prompt_checks_explanation_density():
    from core.opening_quality import _build_opening_review_prompt

    prompt = _build_opening_review_prompt(
        {"opening_lines": [], "issues": [], "scores": {}},
        "テストタイトル",
        "テスト",
        "Shorts",
        "45秒",
    )
    assert "無意味な相槌・復唱・同意" in prompt
    assert "めたんが説明役・補足役" in prompt
    assert "ずんだもんの連続説明は減点しない" in prompt


def test_final_review_prompt_rejects_thin_dialogue():
    from core.opening_quality import _build_final_review_prompt

    prompt = _build_final_review_prompt(
        title="テスト",
        thumbnail_text="テスト",
        fixed_comment="",
        script_content="",
        items=[],
        is_shorts=True,
        estimated_duration=45.0,
        local_review={"opening_lines": [], "scores": {}, "checks": {}},
        ollama_review=None,
        duration_result={},
    )
    assert "めたんの台詞の半分以上が相槌・復唱・同意" in prompt
    assert "3往復以上、具体情報が増えない押し問答" in prompt
    assert "same speaker 4 times" not in prompt


# ── 70〜79点 warning の人間向け表示 ───────────────────────────────────────────

def test_warning_text_for_70s_without_must_fix():
    from core.opening_quality import review_warning_text, review_human_status
    review = {"overall_score": 78, "must_fix": []}
    assert review_human_status(review) == "生成継続可 / 軽微改善推奨"
    assert review_warning_text(review) == "中止不要。冒頭改善余地あり"


def test_human_status_for_must_fix_is_abort_candidate():
    from core.opening_quality import review_human_status
    review = {"overall_score": 78, "must_fix": ["1行目に食べ物名がない"]}
    assert review_human_status(review) == "中止候補 / 要修正"


def test_human_status_for_high_score():
    from core.opening_quality import review_human_status
    assert review_human_status({"overall_score": 88, "must_fix": []}) == "生成継続可"


# ── review_debug の metadata.db 保存・取得 ────────────────────────────────────

def test_opening_review_debug_persisted_to_db(monkeypatch):
    import core.metadata_db as m
    db_path = os.path.join(tempfile.mkdtemp(), "metadata.db")
    monkeypatch.setattr(m, "get_db_path", lambda: db_path)
    m.initialize_db()

    data = {
        "llm_review": {
            "overall_score": 78,
            "status": "warning",
            "review_debug": {
                "model": "qwen3:8b",
                "prompt_version": "v1",
                "raw_response": '{"overall_score":78}',
                "parsed_score": 78,
                "parsed_subscores": {"hook": 74, "tempo": 82},
                "warning_text": "中止不要。冒頭改善余地あり",
                "fix_target": "hook",
                "created_at": "2026-06-01T18:00:00+09:00",
            },
        },
        "final_score": 78,
        "final_status": "warning",
        "rewrite_needed": True,
    }
    m.upsert_opening_review("Shorts_テスト", data)

    debug = m.get_opening_review_debug("Shorts_テスト")
    assert debug is not None
    assert debug["model"] == "qwen3:8b"
    assert debug["parsed_subscores"]["hook"] == 74
    assert debug["fix_target"] == "hook"
    assert debug["raw_response"] == '{"overall_score":78}'

    # opening_score 本体も保存されていること
    with m.ManagedConnection() as conn:
        row = conn.execute(
            "SELECT opening_score FROM script_quality WHERE local_id=?", ("Shorts_テスト",)
        ).fetchone()
    assert row["opening_score"] == 78


def test_get_opening_review_debug_missing_returns_none(monkeypatch):
    import core.metadata_db as m
    db_path = os.path.join(tempfile.mkdtemp(), "metadata.db")
    monkeypatch.setattr(m, "get_db_path", lambda: db_path)
    m.initialize_db()
    assert m.get_opening_review_debug("存在しないID") is None
