"""AGENTS.md のルールを機械検査する。

既存の違反は一度に直せないため、ファイルごとの現在件数を上限として記録し、
新しい違反（件数の増加・新しいファイルでの発生）だけを止める。
直して件数が減ったら、下の上限表も同じ作業で減らすこと（減ったのに表を残すとテストが落ちる）。
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
from collections import Counter

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# `os.environ` / `getenv` の参照件数の上限。新規設定で環境変数を正本にしない（AGENTS.md「最重要運用ルール」）。
# 既存の参照はプロセス起動フラグ・NVF_MASTER_KEY・旧来の既定値読み込み。
ENV_ACCESS_LIMITS = {
    "config/config.py": 228,
    "core/character_expressions.py": 2,
    "web_app/app.py": 2,
    "core/app_shutdown.py": 1,
    "core/output_paths.py": 1,
    "core/secret_store.py": 1,
    "core/settings_store.py": 1,
}

# ログも再送出もしない except 節の件数の上限（AGENTS.md「エラーはすべて上位に伝播」「失敗時はデバッグログへ出力」）。
SILENT_EXCEPT_LIMITS = {
    "web_app/routes/api_channels.py": 9,
    "web_app/routes/api_prompt_templates.py": 9,
    "web_app/routes/api_sd_models.py": 6,
    "web_app/routes/api_bgm.py": 4,
    "workers/main.py": 4,
    "web_app/routes/api_analytics.py": 3,
    "web_app/routes/api_history.py": 3,
    "web_app/routes/api_images.py": 3,
    "web_app/app.py": 2,
    "web_app/routes/api_character_profiles.py": 2,
    "web_app/routes/api_settings.py": 2,
    "core/external_service_check.py": 1,
    "core/upload_scheduler.py": 1,
    "web_app/services/config_service.py": 1,
    "web_app/services/playlist_classifier_service.py": 1,
    "workers/output_locks.py": 1,
}

# `script.txt` への言及件数の上限。台本本文の正本は metadata.db の videos.script_content
# （AGENTS.md「Web UI 作業時の注意点」）。既存は旧フォルダ取り込みの後方互換と説明コメント。
SCRIPT_TXT_LIMITS = {
    "core/metadata_db.py": 10,
    "workers/main.py": 2,
    "core/cta_policy.py": 1,
    "web_app/services/generation_service.py": 1,
}

_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def _tracked(pattern: str) -> list[str]:
    out = subprocess.check_output(["git", "ls-files", pattern], cwd=_ROOT, text=True)
    return [p for p in out.split() if p]


def _app_sources() -> dict[str, str]:
    """テスト以外の追跡中 Python ソース。"""
    return {
        p: open(os.path.join(_ROOT, p), encoding="utf-8").read()
        for p in _tracked("*.py")
        if not p.startswith("tests/")
    }


def _handler_reports(handler: ast.ExceptHandler) -> bool:
    """except 節がログ出力か再送出を含むか。"""
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _LOG_METHODS:
            return True
    return False


def _count(predicate) -> Counter:
    counts: Counter = Counter()
    for path, src in _app_sources().items():
        n = predicate(path, src)
        if n:
            counts[path] = n
    return counts


def _env_access(_path: str, src: str) -> int:
    n = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Attribute) and node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os":
            n += 1
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "getenv":
            n += 1
    return n


def _silent_except(_path: str, src: str) -> int:
    return sum(
        1 for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.ExceptHandler) and not _handler_reports(node)
    )


def _script_txt(_path: str, src: str) -> int:
    return src.count("script.txt")


def _assert_within_limits(actual: Counter, limits: dict[str, int], rule: str) -> None:
    over = {p: (n, limits.get(p, 0)) for p, n in actual.items() if n > limits.get(p, 0)}
    stale = {p: (actual.get(p, 0), n) for p, n in limits.items() if actual.get(p, 0) < n}
    messages = []
    if over:
        messages.append(f"{rule} が増えています（実数, 上限）: {over}")
    if stale:
        messages.append(f"{rule} が減りました。上限表を実数へ下げてください（実数, 上限）: {stale}")
    assert not messages, "\n".join(messages)


@pytest.mark.parametrize(
    ("counter", "limits", "rule"),
    [
        (_env_access, ENV_ACCESS_LIMITS, "os.environ / getenv の参照"),
        (_silent_except, SILENT_EXCEPT_LIMITS, "ログも再送出もしない except 節"),
        (_script_txt, SCRIPT_TXT_LIMITS, "script.txt への言及"),
    ],
    ids=["env", "silent_except", "script_txt"],
)
def test_rule_violations_do_not_increase(counter, limits, rule):
    _assert_within_limits(_count(counter), limits, rule)


def test_no_traceback_text_in_app_code():
    """スタックトレースを文字列化して利用者向け経路へ流さない（AGENTS.md）。デバッグログは exc_info を使う。"""
    hits = [
        p for p, src in _app_sources().items()
        if re.search(r"\btraceback\.(format_exc|print_exc|format_exception)\b", src)
    ]
    assert not hits, f"traceback の文字列化が使われています: {hits}"


def test_config_constants_have_comments():
    """config/config.py の公開定数には説明コメントを付ける（AGENTS.md）。"""
    path = os.path.join(_ROOT, "config", "config.py")
    lines = open(path, encoding="utf-8").read().splitlines()
    missing = []
    for node in ast.parse("\n".join(lines)).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper() and not target.id.startswith("_"):
                if not any("#" in line for line in lines[node.lineno - 1:node.end_lineno]):
                    missing.append(target.id)
    assert not missing, f"説明コメントの無い定数: {missing}"


def test_powershell_scripts_with_non_ascii_have_bom():
    """日本語を含む .ps1 は Windows PowerShell 5.1 が誤読しないよう UTF-8 BOM 付きで保存する（AGENTS.md）。"""
    bad = []
    for p in _tracked("*.ps1"):
        data = open(os.path.join(_ROOT, p), "rb").read()
        if any(b > 0x7F for b in data) and not data.startswith(b"\xef\xbb\xbf"):
            bad.append(p)
    assert not bad, f"BOM の無い .ps1: {bad}"


def _frontmatter(path: str) -> dict[str, str]:
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"frontmatter がありません: {path}"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())


def test_claude_skill_entries_match_shared_skills():
    """`.claude/skills/` は `.agents/skills/` の同名スキルを読むだけの入口にする（AGENTS.md「作業スキル」）。"""
    shared_dir = os.path.join(_ROOT, ".agents", "skills")
    entry_dir = os.path.join(_ROOT, ".claude", "skills")
    shared = sorted(d for d in os.listdir(shared_dir) if os.path.isdir(os.path.join(shared_dir, d)))
    entries = sorted(os.listdir(entry_dir)) if os.path.isdir(entry_dir) else []
    assert shared == entries, f"共通スキルと入口が一致しません: 共通={shared} 入口={entries}"
    for name in shared:
        shared_md = os.path.join(shared_dir, name, "SKILL.md")
        entry_md = os.path.join(entry_dir, name, "SKILL.md")
        shared_meta = _frontmatter(shared_md)
        assert set(shared_meta) == {"name", "description"}, f"frontmatter は name と description だけ: {shared_md}"
        assert shared_meta["name"] == name
        assert _frontmatter(entry_md) == shared_meta, f"入口の frontmatter が正本と食い違います: {entry_md}"
        entry_text = open(entry_md, encoding="utf-8").read()
        assert f".agents/skills/{name}/SKILL.md" in entry_text, f"入口が正本を参照していません: {entry_md}"
        assert len(entry_text.splitlines()) <= 15, f"入口へ手順を複製しないでください: {entry_md}"
