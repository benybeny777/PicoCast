"""Python 3.12 切替後だけに使う、隔離された実サンプル受入。"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import importlib.metadata
import json
import logging
import math
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "temp" / "python312-sample" / "artifacts"
ENDPOINTS = {"http://127.0.0.1:11434", "http://127.0.0.1:50021"}
SPEAKERS = (("ずんだもん", "zundamon", 3), ("四国めたん", "metan", 2))
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["lines"],
    "properties": {"lines": {
        "type": "array", "minItems": 2, "maxItems": 2,
        "items": {"type": "object", "additionalProperties": False,
                  "required": ["character", "text"], "properties": {
                      "character": {"type": "string", "enum": [item[0] for item in SPEAKERS]},
                      "text": {"type": "string", "minLength": 1, "maxLength": 40}}}}},
}
_logger = logging.getLogger("python312_sample")


def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("正の有限値を指定してください")
    return result


def validate_lines(value):
    if not isinstance(value, dict) or set(value) != {"lines"}:
        raise ValueError("応答は lines だけを持つ JSON が必要です")
    lines = value["lines"]
    if not isinstance(lines, list) or len(lines) != len(SPEAKERS):
        raise ValueError("応答の台詞数が2ではありません")
    for line, (name, _key, _speaker) in zip(lines, SPEAKERS):
        if not isinstance(line, dict) or set(line) != {"character", "text"} or line["character"] != name:
            raise ValueError("話者または応答の構造が不正です")
        text = line["text"]
        if not isinstance(text, str) or not 1 <= len(text) <= 40 or not text.strip():
            raise ValueError("台詞の文字数が不正です")
        if text != text.strip() or re.search(r'[\x00-\x1f\x7f\\/:*?"<>|\[\]]', text):
            raise ValueError("台詞に改行・制御文字・予約記号があります")
    return lines


def create_run_directory(root, fixture):
    requested = Path(root)
    if not requested.is_absolute() or os.path.normcase(os.path.abspath(requested)) != os.path.normcase(str(ARTIFACTS)):
        raise ValueError("出力先は temp/python312-sample/artifacts の絶対パスだけを指定してください")
    for path in (ARTIFACTS, *ARTIFACTS.parents):
        if path == ROOT:
            break
        if path.is_symlink() or os.path.isjunction(path):
            raise ValueError("専用出力領域にリンク・ジャンクションは使用できません")
    requested.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="fixture-" if fixture else "run-", dir=requested))


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def local_transport(timeout, allow_connections):
    """既存 API の HTTP 境界だけに、実 Session と接続制限を注入する。"""
    import requests
    session = requests.Session()
    session.trust_env = False
    original_connect = socket.socket.connect

    def connect(connection, address):
        if not allow_connections or not isinstance(address, tuple) or address[:2] not in {
            ("127.0.0.1", 11434), ("127.0.0.1", 50021)
        }:
            raise RuntimeError("サンプル検証で許可されていない接続です")
        return original_connect(connection, address)

    def request(method, url, **kwargs):
        parsed = urlsplit(url)
        if f"{parsed.scheme}://{parsed.netloc}" not in ENDPOINTS or parsed.username or parsed.password:
            raise ValueError("接続先は固定した127.0.0.1だけを許可します")
        if parsed.path not in {"/api/tags", "/api/version", "/api/generate", "/version", "/audio_query", "/synthesis"}:
            raise ValueError("許可されていない API です")
        kwargs["timeout"] = timeout
        kwargs["allow_redirects"] = False
        response = session.request(method, url, **kwargs)
        if response.status_code != 200:
            status = response.status_code
            response.close()
            raise RuntimeError(f"ローカル API が HTTP {status} を返しました")
        return response

    guard = ExitStack()
    guard.enter_context(session)
    guard.enter_context(patch.object(socket.socket, "connect", connect))
    guard.enter_context(patch.object(socket.socket, "connect_ex", lambda *_args: (_ for _ in ()).throw(
        RuntimeError("サンプル検証で connect_ex は許可されていません"))))
    return guard, request


def binary_output(binary, arguments, timeout):
    result = subprocess.run([str(binary), *arguments], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, check=True)
    return result.stdout


def fixture_images(directory, font_file):
    from PIL import Image, ImageDraw, ImageFont
    from core.native_character_assets import CharacterVariantSet
    font = ImageFont.truetype(str(font_file), 28)
    if not any(value in font.getname()[0] for value in ("Yu Gothic", "游ゴシック")):
        raise ValueError("インストール済み Yu Gothic のフォント実体を指定してください")
    backgrounds = directory / "backgrounds"
    backgrounds.mkdir()
    with Image.new("RGB", (1920, 1080), "#193149") as image:
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 80, 1840, 1000), outline="#6dc5ca", width=8)
        draw.text((120, 120), "Python 3.12 ローカル動作確認", fill="white", font=font)
        image.save(backgrounds / "bg_0001.png")
    characters = directory / "characters"
    characters.mkdir()
    variants = []
    for index, (name, key, _speaker) in enumerate(SPEAKERS):
        path = characters / f"{key}.png"
        with Image.new("RGBA", (360, 720)) as image:
            draw = ImageDraw.Draw(image)
            color = ("#a6df75", "#f2abd4")[index]
            draw.ellipse((70, 30, 290, 250), fill=color)
            draw.rounded_rectangle((35, 240, 325, 715), radius=50, fill=color)
            draw.ellipse((125, 120, 140, 140), fill="black")
            draw.ellipse((220, 120, 235, 140), fill="black")
            draw.arc((140, 155, 220, 195), 0, 180, fill="black", width=5)
            draw.text((45, 330), name, fill="black", font=font)
            image.save(path)
        value = str(path)
        variants.append(CharacterVariantSet(key, value, value, value, value, value, value, {}, name))
    return variants


def prepare_script(directory, response):
    from core.parser import ScriptParser
    from core import metadata_db, native_renderer
    lines = validate_lines(response)
    script = "動画形式: Long\n" + "\n".join(
        f"{line['character']}(ノーマル): {line['text']}" for line in lines)
    parsed = [line for line in ScriptParser.parse_string(script) if line["type"] == "dialogue"]
    if [(line["character"], line["text"]) for line in parsed] != [
        (line["character"], line["text"]) for line in lines
    ] or len(native_renderer._dialogue_captions(script)) != 2:
        raise ValueError("旧パーサーの台詞または字幕分割が2台詞と一致しません")
    metadata_db.save_script_content(directory.name, str(directory), script, video_type="long")
    if metadata_db.get_script_content(directory.name) != script:
        raise ValueError("専用 metadata.db の台本往復が一致しません")
    return parsed


def run(args, directory):
    from tools.oracle_environment import isolate
    isolation, isolated_root = isolate(work_name="python312-sample")
    # isolate が返す所有者は処理終了まで保持し、成果物とは別の設定領域だけを終了時に解放する。
    del isolated_root
    from config import config as cfg
    cfg.FFMPEG_BIN = str(args.ffmpeg)
    cfg.NATIVE_FFMPEG_ENCODER = "libx264"
    cfg.NATIVE_FFMPEG_PRESET = "veryfast"
    cfg.NATIVE_SUBTITLE_FONT = "Yu Gothic"
    cfg.NATIVE_FFMPEG_TIMEOUT_SEC = args.render_timeout
    import config
    for name in ("FFMPEG_BIN", "NATIVE_FFMPEG_ENCODER", "NATIVE_FFMPEG_PRESET",
                 "NATIVE_SUBTITLE_FONT", "NATIVE_FFMPEG_TIMEOUT_SEC"):
        setattr(config, name, getattr(cfg, name))
    from core import channel_profile, metadata_db, native_renderer, media_probe, voicevox
    profile = SimpleNamespace(profile_id="python312-sample", output_root_abs=str(directory / "profile"))
    transport, request = local_transport(args.timeout, not args.fixture_check)
    with transport, ExitStack() as guard:
        guard.enter_context(patch.object(channel_profile, "get_active_profile", return_value=profile))
        guard.enter_context(patch.object(channel_profile, "require_active_profile", return_value=profile))
        guard.enter_context(patch.object(media_probe, "ffprobe_bin", return_value=str(args.ffprobe)))
        # 旧 API の query/synthesis 本体はそのまま使い、HTTP 送信先だけを制限する。
        guard.enter_context(patch.object(voicevox.requests, "post", side_effect=lambda url, **kw: request("POST", url, **kw)))
        variants = fixture_images(directory, args.font_file)
        guard.enter_context(patch.object(native_renderer, "load_character_variants", return_value=variants))
        try:
            if args.fixture_check:
                response = {"lines": [{"character": SPEAKERS[0][0], "text": "水は冷やすと氷になるのだ。"},
                                      {"character": SPEAKERS[1][0], "text": "身近な変化ね。"}]}
                parsed = prepare_script(directory, response)
                for invalid in ({"lines": []}, {"lines": response["lines"][::-1]},
                                {"lines": [{"character": SPEAKERS[0][0], "text": "改行\n"}, response["lines"][1]]}):
                    try:
                        validate_lines(invalid)
                    except ValueError:
                        continue
                    raise RuntimeError("不正な応答が拒否されませんでした")
                try:
                    create_run_directory(directory, True)
                except ValueError:
                    pass
                else:
                    raise RuntimeError("専用領域以外の出力が拒否されませんでした")
                if len(parsed) != 2 or (directory / "script.txt").exists():
                    raise RuntimeError("fixture の台詞数・保存形式が不正です")
                for address in (("127.0.0.1", 11434), ("192.0.2.1", 443)):
                    with socket.socket() as connection:
                        try:
                            connection.connect(address)
                        except RuntimeError:
                            continue
                        raise RuntimeError("fixture からの接続が拒否されませんでした")
                marker = directory / "no-overwrite.json"
                write_json(marker, {"original": True})
                try:
                    write_json(marker, {"original": False})
                except FileExistsError:
                    pass
                else:
                    raise RuntimeError("既存の出力が上書きされました")
                if json.loads(marker.read_text(encoding="utf-8")) != {"original": True}:
                    raise RuntimeError("既存の出力が保持されませんでした")
                return {"mode": "fixture-only", "real_acceptance": False, "line_count": len(parsed),
                        "checks": ["json-schema-boundary", "output-boundary", "real-parser",
                                   "metadata-script-roundtrip", "pillow-fixtures", "no-overwrite",
                                   "network-denied"], "network_calls": 0}

            with request("GET", "http://127.0.0.1:11434/api/tags") as result:
                installed = {item["name"] for item in result.json()["models"]}
            if args.model not in installed:
                raise ValueError("指定モデルはインストール済み一覧にありません。ダウンロードは行いません")
            with request("GET", "http://127.0.0.1:11434/api/version") as result:
                ollama_version = result.json()["version"]
            with request("GET", "http://127.0.0.1:50021/version") as result:
                voicevox_version = result.json()
            with request("POST", "http://127.0.0.1:11434/api/generate", json={
                "model": args.model, "stream": False, "format": SCHEMA,
                "prompt": "水が冷えると氷になる話を日本語の短い2台詞で作ってください。最初はずんだもんの説明、次は四国めたんの感想です。各台詞は1文だけ、20文字程度、句点は末尾だけ。character,textを持つlines配列だけのJSONを返してください。",
                "options": {"temperature": 0, "num_predict": args.max_output_tokens},
            }) as result:
                payload = result.json()
            if payload.get("done") is not True:
                raise ValueError("Ollama の生成が完了していません")
            parsed = prepare_script(directory, json.loads(payload["response"]))
            audio = directory / "audio"
            audio.mkdir()
            api = voicevox.VoicevoxAPI(base_url="http://127.0.0.1:50021")
            for index, (line, (_name, _key, speaker)) in enumerate(zip(parsed, SPEAKERS), 1):
                path = audio / f"{index:04d}_{speaker}_{line['text']}.wav"
                api.generate_audio(line["text"], speaker, str(path), post_phoneme_length=0.5)
                with wave.open(str(path), "rb") as wav:
                    if wav.getnframes() <= 0 or wav.getframerate() <= 0:
                        raise ValueError("合成した WAV が空です")
            result = native_renderer.render_native(str(directory), bgm_mode="none",
                                                   progress_callback=lambda *items: _logger.info("%s", items))
            movie = Path(result.output_path)
            if movie.parent.resolve() != directory.resolve() or not movie.is_file():
                raise ValueError("レンダー結果が専用ディレクトリにありません")
            probe = json.loads(binary_output(args.ffprobe, ["-v", "error", "-show_streams", "-show_format", "-of", "json", str(movie)], args.timeout))
            video = [item for item in probe["streams"] if item["codec_type"] == "video"]
            audio_streams = [item for item in probe["streams"] if item["codec_type"] == "audio"]
            duration = float(probe["format"]["duration"])
            if len(video) != 1 or not audio_streams or (video[0]["width"], video[0]["height"]) != (1920, 1080) or not math.isfinite(duration) or duration <= 0:
                raise ValueError("MP4 の映像・音声・解像度・尺の検証に失敗しました")
            if video[0]["codec_name"] != "h264" or result.audio_count != 2:
                raise ValueError("MP4 のコーデックまたは音声件数が不正です")
            with movie.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            return {"mode": "local-live", "real_acceptance": True, "model": args.model,
                    "versions": {"python": platform.python_version(), "ollama": ollama_version,
                                 "voicevox": voicevox_version, "pillow": importlib.metadata.version("Pillow"),
                                 "ffmpeg": binary_output(args.ffmpeg, ["-version"], args.timeout).splitlines()[0],
                                 "ffprobe": binary_output(args.ffprobe, ["-version"], args.timeout).splitlines()[0]},
                    "line_count": len(parsed), "resolution": [video[0]["width"], video[0]["height"]],
                    "duration_seconds": duration, "file_sha256": digest, "file": str(movie),
                    "encoder": "libx264", "font": "Yu Gothic", "speaker_ids": [3, 2],
                    "post_phoneme_length": 0.5}
        finally:
            metadata_db.close_all_connections()
            # isolation は atexit の共通解放処理へ渡し、実設定に接続しないまま終了する。
            _ = isolation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-check", action="store_true", help="実 API と ffmpeg を呼ばず入力・隔離だけ検査")
    parser.add_argument("--model", required=True, help="インストール済みの正確な Ollama モデル名")
    parser.add_argument("--timeout", type=positive, required=True, help="ローカル HTTP/ffprobe の最大秒数")
    parser.add_argument("--render-timeout", type=positive, required=True, help="旧レンダラーの ffmpeg 1 回の最大秒数")
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--font-file", type=Path, required=True, help="インストール済み Yu Gothic の ttc/ttf 絶対パス")
    parser.add_argument("--output-root", type=Path, required=True, help="temp/python312-sample/artifacts の絶対パス")
    args = parser.parse_args()
    if args.max_output_tokens <= 0:
        parser.error("--max-output-tokens は正の整数が必要です")
    for name in ("ffmpeg", "ffprobe", "font_file"):
        path = getattr(args, name)
        if not path.is_absolute() or not path.is_file():
            parser.error(f"--{name.replace('_', '-')} は既存ファイルの絶対パスが必要です")
    try:
        directory = create_run_directory(args.output_root, args.fixture_check)
    except (OSError, ValueError):
        parser.error("E-MIGRATION-SAMPLE: 専用出力領域を作成できません。絶対パスとリンクの有無を確認してください")
    handler = logging.FileHandler(directory / "debug.log", mode="x", encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    try:
        if sys.version_info[:2] != (3, 12):
            raise RuntimeError("この受入は切替後の Python 3.12 で実行してください")
        report = run(args, directory)
        write_json(directory / "report.json", report)
        print(json.dumps({"ok": True, "report": str(directory / "report.json"),
                          "real_acceptance": report["real_acceptance"]}, ensure_ascii=False))
        return 0
    except Exception:
        _logger.exception("E-MIGRATION-SAMPLE サンプル受入に失敗しました")
        write_json(directory / "failure.json", {"code": "E-MIGRATION-SAMPLE", "real_acceptance": False})
        print(f"E-MIGRATION-SAMPLE: サンプル受入に失敗しました。専用 debug.log を確認してください: {directory}", file=sys.stderr)
        return 1
    finally:
        handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
