"""固定入力を現行Python版へ通し、Rust移植の比較契約を検証する。"""
from __future__ import annotations

import argparse
import gc
from datetime import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def evaluate(corpus):
    if corpus.get("contract_version") != 1:
        raise ValueError("オラクル入力の契約版は1が必要です")
    identifiers = [case["id"] for case in corpus["cases"]]
    if any(not value for value in identifiers) or len(identifiers) != len(set(identifiers)):
        raise ValueError("オラクル入力のidが空または重複しています")
    from config import config
    from core.parser import ScriptParser
    from core.reading_normalizer import ReadingNormalizer
    from core import analytics_score, channel_profile, reading_dictionary_store, upload_scheduler
    from core import youtube_metadata

    output = {"contract_version": 1, "cases": []}
    for case in corpus["cases"]:
        kind = case["kind"]
        data = case["input"]
        if kind == "reading":
            dictionaries = {"base": data["base"], "user": data["user"]}
            with (
                patch.object(config, "VOICE_READING_MODE", data["mode"]),
                patch.object(reading_dictionary_store, "load_all", return_value=dictionaries),
                patch.object(reading_dictionary_store, "load_candidates", return_value={}),
            ):
                result = ReadingNormalizer().normalize_batch(data["texts"])
        elif kind == "script":
            result = ScriptParser.parse_string(data["text"])
        elif kind == "metadata":
            profile = SimpleNamespace(genre_profile="oracle", default_hashtags=data["hashtags"])
            genre = {"default_tags": data["default_tags"], "seo_sentence_shorts": data["seo"]}
            with (
                patch.object(channel_profile, "require_active_profile", return_value=profile),
                patch("core.prompt_profile_loader.load_genre_profile_config", return_value=genre),
                patch("core.prompt_profile_loader.get_default_video_description", return_value=""),
            ):
                result = youtube_metadata.optimize_upload_metadata(
                    data["title"], data["description"], data["tags"], is_shorts=True,
                    script_text=data["script"],
                )
        elif kind == "schedule":
            schedule = SimpleNamespace(
                timezone_name=data["timezone"], shorts_slot_hours=data["shorts"],
                long_slot_hours=data["long"],
            )
            with patch.object(upload_scheduler, "_active_schedule", return_value=schedule):
                result = [value.isoformat() for value in upload_scheduler._assign_slots_from_used(
                    data["count"], data["format"], set(data["used"]), datetime.fromisoformat(data["now"]),
                )]
        elif kind in ("score", "expansion"):
            result = analytics_score.score_items(data["videos"])
        else:
            raise ValueError(f"未対応のオラクル種別: {kind}")
        output["cases"].append({"id": case["id"], "kind": kind, "output": result})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-json", action="store_true", help="初回記録の候補を標準出力へ出す。既存基準は変更しない")
    args = parser.parse_args()
    from tools.oracle_environment import deny_network, isolate
    environment, _ = isolate()
    guard = deny_network()
    try:
        path = ROOT / "tests" / "oracle"
        corpus = json.loads((path / "inputs" / "v1.json").read_text(encoding="utf-8"))
        actual = evaluate(corpus)
        text = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.emit_json:
            print(text, end="")
            return 0
        expected = json.loads((path / "expected" / "v1.json").read_text(encoding="utf-8"))
        # JSON表現へ揃え、Python固有のtupleを比較契約へ持ち込まない。
        actual = json.loads(text)
        if actual != expected:
            wanted = {case["id"]: case for case in expected["cases"]}
            got = {case["id"]: case for case in actual["cases"]}
            changed = [key for key in sorted(wanted.keys() | got.keys()) if wanted.get(key) != got.get(key)]
            print("オラクル不一致: " + ", ".join(changed), file=sys.stderr)
            return 1
        print(f"旧版オラクル: {len(actual['cases'])} ケース一致（実API通信なし）")
        return 0
    finally:
        guard.close()
        gc.collect()
        environment.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
