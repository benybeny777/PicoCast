import json
import os
import gc
import re
import subprocess
import wave
import logging
from dataclasses import dataclass

from config import (
    FFMPEG_BIN,
    NATIVE_AUDIO_LOUDNORM_ENABLED,
    NATIVE_AUDIO_LOUDNORM_I,
    NATIVE_AUDIO_LOUDNORM_LRA,
    NATIVE_AUDIO_LOUDNORM_TP,
    NATIVE_BACKGROUND_TRANSITION,
    NATIVE_BACKGROUND_TRANSITION_SEC,
    NATIVE_BG_ZOOM_MAX,
    CHARACTER_UPPER_BODY_LONG_Y_OFFSET,
    CHARACTER_UPPER_BODY_MODE,
    CHARACTER_UPPER_BODY_SCALE,
    CHARACTER_UPPER_BODY_SHORTS_SCALE,
    CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET,
    CHARACTER_EXPRESSION_PNGS,
    NATIVE_CHARACTER_HEIGHT_LONG,
    NATIVE_CHARACTER_HEIGHT_SHORTS,
    NATIVE_CHARACTER_BOTTOM_MARGIN_LONG,
    NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS,
    NATIVE_CHARACTER_SIDE_MARGIN_LONG,
    NATIVE_CHARACTER_SIDE_MARGIN_SHORTS,
    NATIVE_ENABLE_BG_KEN_BURNS,
    NATIVE_ENABLE_BLINK,
    NATIVE_ENABLE_CHARACTER_BOUNCE,
    NATIVE_ENABLE_LIPSYNC,
    NATIVE_ENABLE_MOTION_EFFECTS,
    NATIVE_ENABLE_POP_TELOP,
    NATIVE_ENABLE_SHAKE,
    NATIVE_FFMPEG_CQ,
    NATIVE_FFMPEG_CRF,
    NATIVE_FFMPEG_ENCODER,
    NATIVE_FFMPEG_PRESET,
    NATIVE_FFMPEG_TIMEOUT_SEC,
    NATIVE_MAX_ICON_COUNT_SHORTS,
    TRIAL_WATERMARK_TEXT,
    TRIAL_WATERMARK_FONT_SCALE,
    TRIAL_WATERMARK_FONT_MIN_PX,
    NATIVE_MAX_SHAKE_COUNT_SHORTS,
    NATIVE_RENDER_CHARACTERS,
    NATIVE_SHORTS_CHARACTER_SCALE,
    NATIVE_SUBTITLE_FONT,
    NATIVE_SUBTITLE_FONT_SCALE,
    NATIVE_SUBTITLE_ALIGNMENT_LONG,
    NATIVE_SUBTITLE_ALIGNMENT_SHORTS,
    NATIVE_SUBTITLE_BOX_OPACITY_SHORTS,
    NATIVE_SUBTITLE_BOX_SHORTS,
    NATIVE_SUBTITLE_MARGIN_V_LONG,
    NATIVE_SUBTITLE_BOX_LINE_HEIGHT,
    NATIVE_SUBTITLE_FONT_SIZE_LONG,
    NATIVE_SUBTITLE_FONT_SIZE_SHORTS,
    NATIVE_SUBTITLE_MARGIN_V_SHORTS,
    NATIVE_SUBTITLE_OFFSET_SEC,
    NATIVE_SUBTITLE_OUTER_STROKE_WIDTH,
    NATIVE_SUBTITLE_PADDING_Y,
    NATIVE_SUBTITLE_STROKE_WIDTH,
    NATIVE_SUBTITLE_WRAP_CHARS_LONG,
    NATIVE_SUBTITLE_WRAP_CHARS_SHORTS,
    NATIVE_SUBTITLE_Y_OFFSET_LONG,
    NATIVE_SUBTITLE_Y_OFFSET_SHORTS,
    VIDEO_FPS,
    THUMBNAIL_HOLD_FRAMES_SHORTS,
    NATIVE_INTER_DIALOGUE_GAP_SEC,
    NATIVE_SHAKE_AMP_X,
    NATIVE_SHAKE_AMP_Y,
    NATIVE_CHARACTER_BOUNCE_SEC,
    NATIVE_TELOP_POP_START_SEC,
    NATIVE_TELOP_POP_MAX_SEC,
)
from core.bgm_store import resolve_bgm_selection
from core.media_probe import media_duration_sec
from core.native_character_assets import CharacterVariantSet, character_variant_key, load_character_variants
from core.parser import ScriptParser


CaptionChunk = tuple[str, str, str | None]


@dataclass
class SegmentEffect:
    telop: str | None = None
    shake: bool = False
    icon: str | None = None


@dataclass
class NativeRenderResult:
    output_path: str
    duration_sec: float
    audio_duration_sec: float
    audio_count: int
    background_count: int


def _safe_output_stem(output_dir: str) -> str:
    stem = os.path.basename(os.path.abspath(output_dir)).strip() or "video"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem)
    stem = re.sub(r"\s+", "_", stem).strip(" ._")
    return (stem or "video")[:80]


def _native_output_path(output_dir: str) -> str:
    return os.path.join(output_dir, f"{_safe_output_stem(output_dir)}_native.mp4")


def _drawtext_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _trial_watermark_filter(width: int, height: int) -> str | None:
    """Trial エディションのときだけ右下透かしの drawtext フィルタ文字列を返す。

    それ以外（透かし不要なエディション）は None を返す。最終出力エンコードの
    `-vf` / `-filter_complex` に畳み込んで使うことで、透かし用の追加エンコード
    パスを発生させない。
    """
    from core.license_manager import should_watermark
    if not should_watermark():
        return None
    text = _drawtext_escape(TRIAL_WATERMARK_TEXT)
    font_size = max(TRIAL_WATERMARK_FONT_MIN_PX, int(min(width, height) * TRIAL_WATERMARK_FONT_SCALE))
    return (
        "drawtext="
        f"text='{text}':"
        f"x=w-tw-24:y=h-th-24:fontsize={font_size}:"
        "fontcolor=white@0.72:box=1:boxcolor=black@0.35:boxborderw=8"
)

_logger = logging.getLogger(__name__)


def _clear_native_work_dir(work_dir: str) -> None:
    if not os.path.isdir(work_dir):
        return
    for name in os.listdir(work_dir):
        if (
            name.startswith("segment_")
            or name.startswith("subtitle_")
            or name in {"audio_concat.txt", "segment_concat.txt", "video_with_narration.mp4"}
        ):
            path = os.path.join(work_dir, name)
            try:
                os.remove(path)
            except OSError:
                _logger.warning("native作業ファイルの削除に失敗しました: path=%s", path, exc_info=True)
                pass


def _ffmpeg_missing_error(exc: FileNotFoundError) -> RuntimeError:
    """ffmpeg バイナリ未検出を、対処手順を含む明確なエラーに変換する。

    表示経路に依存せず str() に対処が出るよう with_fix 整形済み文言を使う。
    """
    from core.error_codes import format_error
    err = RuntimeError(format_error("E-FFMPEG-MISSING", detail=str(FFMPEG_BIN), with_fix=True))
    err.__cause__ = exc
    return err


def _run_ffmpeg(args: list[str]) -> None:
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    run_args = _ffmpeg_noninteractive_args(args)
    try:
        proc = subprocess.run(
            run_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            timeout=NATIVE_FFMPEG_TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        raise _ffmpeg_missing_error(exc)
    except subprocess.TimeoutExpired as exc:
        tail = _subprocess_tail(exc.stderr or exc.stdout)
        raise TimeoutError(f"ffmpeg timed out after {NATIVE_FFMPEG_TIMEOUT_SEC:g}秒\n{tail}") from exc
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").splitlines()[-20:])
        raise RuntimeError(f"ffmpeg failed ({proc.returncode})\n{tail}")


def _run_ffmpeg_capture(args: list[str]) -> subprocess.CompletedProcess:
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    run_args = _ffmpeg_noninteractive_args(args)
    try:
        return subprocess.run(
            run_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            timeout=NATIVE_FFMPEG_TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        raise _ffmpeg_missing_error(exc)


def _ffmpeg_noninteractive_args(args: list[str]) -> list[str]:
    if not args:
        return args
    if "-nostdin" in args:
        return args
    return [args[0], "-nostdin", *args[1:]]


def _subprocess_tail(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    return "\n".join(str(output).splitlines()[-20:])


def _wav_duration(path: str) -> float:
    with wave.open(path, "rb") as wr:
        return wr.getnframes() / float(wr.getframerate())


def _native_loudnorm_filter() -> str:
    return (
        f"loudnorm=I={NATIVE_AUDIO_LOUDNORM_I:g}:"
        f"TP={NATIVE_AUDIO_LOUDNORM_TP:g}:"
        f"LRA={NATIVE_AUDIO_LOUDNORM_LRA:g}"
    )


def _duration_status(sec: float) -> tuple[str, str]:
    """Shorts尺評価の (status_key, 表示ラベル) を返す。"""
    if 38 <= sec <= 50:
        return "ideal", "✅ 理想"
    if 35 <= sec < 38:
        return "ok_but_short", "⚠ やや短い"
    if 50 < sec <= 55:
        return "ok_but_long", "⚠ OKだけど長め"
    if (32 <= sec < 35) or (55 < sec <= 58):
        return "warning", "🔶 警告"
    return "needs_review", "❌ 要確認"


def _save_render_info(output_dir: str, info: dict) -> None:
    from core.metadata_db import upsert_render_info, initialize_db, is_initialized
    if not is_initialized():
        initialize_db()
    local_id = os.path.basename(os.path.abspath(output_dir))
    upsert_render_info(local_id, info)


def _audio_analysis_summary(path: str) -> str:
    if not path or not os.path.exists(path):
        return "音量解析対象が見つかりません"
    proc = None
    try:
        proc = _run_ffmpeg_capture([
            FFMPEG_BIN,
            "-hide_banner",
            "-nostats",
            "-i", path,
            "-filter_complex", "ebur128=peak=true",
            "-f", "null",
            "-",
        ])
        text = proc.stderr or proc.stdout or ""
        summary_lines = []
        capture = False
        in_true_peak = False
        for line in text.splitlines():
            stripped = line.strip()
            if "Summary:" in stripped:
                capture = True
                in_true_peak = False
                summary_lines = ["Summary:"]
                continue
            if capture and stripped:
                summary_lines.append(stripped)
                if stripped == "True peak:":
                    in_true_peak = True
                elif in_true_peak and stripped.startswith("Peak:"):
                    break
        if proc.returncode != 0:
            tail = "\n".join(text.splitlines()[-8:])
            return f"音量解析失敗 ({proc.returncode}): {tail}"
        return "\n".join(summary_lines[-12:]) if summary_lines else "音量解析結果を取得できませんでした"
    except Exception as e:
        _logger.warning("音量解析に失敗しました: path=%s", path, exc_info=True)
        return f"音量解析失敗: {e}"
    finally:
        proc = None


def _concat_escape(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")


def _subtitles_filter_path(path: str) -> str:
    """ffmpeg subtitles フィルターの filename 引数用パスエスケープ。

    subtitles=filename='<result>':original_size=WxH の形式で使用する想定。
    Windows / macOS 両対応。

    エスケープ処理（適用順）:
      1. 絶対パスに変換し、バックスラッシュをスラッシュに統一
      2. Windows ドライブレター（例: C:/）のコロンを \\: にエスケープ
         ※ ffmpeg フィルターオプション内でコロンはオプションセパレータとして
           扱われるため、ドライブレターのコロンを先に分離して個別にエスケープ
      3. ドライブレター以降に残るバックスラッシュを \\\\ にエスケープ
         （ドライブレターと一括置換しないことで二重エスケープバグを防ぐ）
      4. シングルクォートを \\' にエスケープ
         ※ filename='...' の外側クォートを壊さないため
      5. [ ] を \\[ \\] にエスケープ（ffmpeg フィルターグラフの特殊文字）

    注意: ffmpeg 8.x 以降では positional 引数解析が変わったため、
    必ず filename= キーワードと original_size= を明示することで
    パスを image size として誤解釈されるバグを回避する。
    """
    # 絶対パスへ変換、バックスラッシュをスラッシュに統一
    text = os.path.abspath(path).replace("\\", "/")

    # Windows ドライブレターのコロンだけを先に分離してエスケープ
    # 例: "C:/foo/bar" → drive_prefix="C\:", rest="/foo/bar"
    # ここで分離することで、この後の \\ 置換がドライブレターを二重エスケープしない
    drive_prefix = ""
    m = re.match(r"^([A-Za-z]):(/.*)$", text)
    if m:
        drive_prefix = m.group(1) + "\\:"
        text = m.group(2)  # "/foo/bar" のみ残す

    # 残存バックスラッシュ（通常ゼロのはずだが UNC パス等の念のためのガード）
    text = text.replace("\\", "\\\\")
    # シングルクォートエスケープ（filename='...' の外側クォートを破壊しない）
    text = text.replace("'", "\\'")
    # ffmpeg フィルターグラフ内の角括弧エスケープ
    text = text.replace("[", "\\[").replace("]", "\\]")

    return drive_prefix + text


def _ass_escape(text: str) -> str:
    text = str(text or "").replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return text.replace("\n", r"\N")


def _wrap_subtitle(text: str, max_chars: int) -> str:
    """字幕を max_chars 文字ごとに改行（\\n）で折り返す。
    句読点（、。！？…）が直前にあれば優先的にそこで折り返す。
    戻り値の \\n は _ass_escape() で \\N に変換される。
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    min_tail = max(2, max_chars // 3)  # 折り返し後の2行目が短すぎる場合は句読点折り返しを使わない
    lines: list[str] = []
    while len(text) > max_chars:
        break_pos = max_chars
        for punct in "、。！？…":
            pos = text.rfind(punct, 0, max_chars + 1)
            if pos > max_chars // 2 and len(text) - (pos + 1) >= min_tail:
                break_pos = pos + 1
                break
        lines.append(text[:break_pos])
        text = text[break_pos:]
    if text:
        lines.append(text)
    return "\n".join(lines)


def _ass_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _split_at_punctuation(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?])", str(text or ""))
    return [p.strip() for p in parts if p.strip()] or ([str(text).strip()] if str(text).strip() else [])


def _caption_style(character: str) -> str:
    text = str(character or "").lower()
    if "めたん" in text or "metan" in text or "四国" in text:
        return "Metan"
    if "ずんだ" in text or "zunda" in text:
        return "Zundamon"
    if "霊夢" in text or "reimu" in text:
        return "Reimu"
    if "魔理沙" in text or "marisa" in text:
        return "Marisa"
    return "Default"


def _audio_stem_key(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", str(text or ""))[:20].strip()


def _dialogue_captions(script_text: str) -> list[CaptionChunk]:
    try:
        items = ScriptParser.parse_string(script_text or "")
    except Exception:
        _logger.warning("字幕用台本パースに失敗しました", exc_info=True)
        return []
    captions: list[CaptionChunk] = []
    for item in items:
        if item.get("type") == "dialogue":
            style = _caption_style(item.get("character", ""))
            expression = item.get("expression")
            captions.extend((text, style, expression) for text in _split_at_punctuation(item.get("text", "")))
    return captions


def _dialogue_caption_events(script_text: str) -> list[tuple[CaptionChunk, str | None]]:
    try:
        items = ScriptParser.parse_string(script_text or "")
    except Exception:
        _logger.warning("字幕イベント用台本パースに失敗しました", exc_info=True)
        return []
    events: list[tuple[CaptionChunk, str | None]] = []
    pending_telops: list[str] = []
    for item in items:
        item_type = item.get("type")
        if item_type == "telop":
            text = str(item.get("text", "")).strip()
            if text:
                pending_telops.append(text)
            continue
        if item_type != "dialogue":
            continue
        style = _caption_style(item.get("character", ""))
        expression = item.get("expression")
        telop = " / ".join(pending_telops[:2]) if pending_telops else None
        pending_telops.clear()
        parts = _split_at_punctuation(item.get("text", ""))
        for part_idx, text in enumerate(parts):
            events.append(((text, style, expression), telop if part_idx == 0 else None))
    return events


def _captions_for_audio_files(script_text: str, audio_files: list[str]) -> list[CaptionChunk]:
    script_captions = _dialogue_captions(script_text)
    result: list[CaptionChunk] = []
    search_from = 0
    for audio_path in audio_files:
        audio_text = _audio_caption(audio_path)
        audio_key = _audio_stem_key(audio_text)
        matched = None
        for idx in range(search_from, len(script_captions)):
            script_text, style, expression = script_captions[idx]
            if _audio_stem_key(script_text) == audio_key:
                matched = (script_text, style, expression)
                search_from = idx + 1
                break
        if matched is None:
            matched = (audio_text, "Default", None)
        result.append(matched)
    return result


def _effects_for_audio_files(script_text: str, audio_files: list[str], is_shorts: bool) -> list[SegmentEffect]:
    events = _dialogue_caption_events(script_text)
    result: list[SegmentEffect] = []
    search_from = 0
    shake_count = 0
    icon_count = 0
    for audio_path in audio_files:
        audio_text = _audio_caption(audio_path)
        audio_key = _audio_stem_key(audio_text)
        matched: tuple[CaptionChunk, str | None] | None = None
        for idx in range(search_from, len(events)):
            caption, telop = events[idx]
            if _audio_stem_key(caption[0]) == audio_key:
                matched = (caption, telop)
                search_from = idx + 1
                break
        caption, telop = matched if matched is not None else ((audio_text, "Default", None), None)
        text, style, _expression = caption
        if not is_shorts:
            telop = None
        should_shake = bool(is_shorts and _is_reaction_for_motion(text, style, _expression))
        icon = _reaction_icon(text, style, _expression) if is_shorts else None
        if should_shake and shake_count < max(0, NATIVE_MAX_SHAKE_COUNT_SHORTS):
            shake_count += 1
        else:
            should_shake = False
        if icon and icon_count < max(0, NATIVE_MAX_ICON_COUNT_SHORTS):
            icon_count += 1
        else:
            icon = None
        result.append(SegmentEffect(telop=telop, shake=should_shake, icon=icon))
    return result


def _is_reaction_for_motion(text: str, style: str, expression: str | None = None) -> bool:
    if expression in ("驚き", "焦り", "ドン引き", "困惑", "呆れ", "怒り"):
        return True
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    has_trigger = bool(re.search(r"[!！?？]|ヤバ|やば|えっ|ええ|マジ|まじ|嘘|うそ", compact))
    if not has_trigger:
        return False
    if len(compact) > 22:
        return False
    return style == "Metan" or "？" in compact or "?" in compact


def _reaction_icon(text: str, style: str, expression: str | None = None) -> str | None:
    if expression in ("驚き", "ドン引き"):
        return "!?" if style == "Metan" else "！"
    if expression in ("困惑", "疑問"):
        return "？"
    if expression in ("焦り", "怒り"):
        return "!" if style == "Metan" else "！"
    if expression == "呆れ":
        return None  # 揺れのみ・アイコンなし
    compact = re.sub(r"\s+", "", str(text or ""))
    has_question = "？" in compact or "?" in compact
    has_exclaim = "！" in compact or "!" in compact or re.search(r"ヤバ|やば|えっ|マジ|まじ", compact)
    if style == "Zundamon" and has_question:
        return "？"
    if style == "Metan" and has_question and has_exclaim:
        return "!?"
    if style == "Metan" and has_exclaim:
        return "!"
    if style == "Metan" and has_question:
        return "？"
    return None


def _audio_caption(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    parts = stem.split("_", 2)
    if len(parts) >= 3:
        return parts[2].strip()
    return stem.strip()


def _write_concat_list(path: str, files: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for file_path in files:
            f.write(f"file '{_concat_escape(file_path)}'\n")


def _write_image_list(path: str, image_durations: list[tuple[str, float]]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for image_path, duration in image_durations:
            f.write(f"file '{_concat_escape(image_path)}'\n")
            f.write(f"duration {max(0.2, duration):.3f}\n")
        if image_durations:
            f.write(f"file '{_concat_escape(image_durations[-1][0])}'\n")


def _background_for_audio(audio_path: str, bg_files: list[str]) -> str:
    try:
        bg_idx = int(os.path.basename(audio_path).split("_", 1)[0])
    except Exception:
        _logger.debug("音声ファイル名から背景番号を解析できませんでした: path=%s", audio_path, exc_info=True)
        bg_idx = 1
    return bg_files[min(max(bg_idx - 1, 0), len(bg_files) - 1)]


def _thumbnail_path(output_dir: str) -> str | None:
    candidates = [
        os.path.join(output_dir, "thumbnails", "thumbnail.png"),
        os.path.join(output_dir, "thumbnail.png"),
    ]
    existing = [path for path in candidates if os.path.exists(path)]
    if not existing:
        return None
    existing.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return existing[0]


def _video_encode_args(encoder_override: str | None = None) -> list[str]:
    encoder = str(encoder_override or NATIVE_FFMPEG_ENCODER or "libx264").strip()
    preset = str(NATIVE_FFMPEG_PRESET or "").strip()
    if encoder == "libx264":
        args = ["-c:v", "libx264"]
        if preset:
            args.extend(["-preset", preset])
        if str(NATIVE_FFMPEG_CRF).strip():
            args.extend(["-crf", str(NATIVE_FFMPEG_CRF).strip()])
        return args

    args = ["-c:v", encoder]
    if preset:
        args.extend(["-preset", preset])
    if encoder in {"h264_nvenc", "hevc_nvenc"}:
        args.extend(["-rc", "vbr", "-cq", str(NATIVE_FFMPEG_CQ).strip() or "23", "-b:v", "0"])
    elif str(NATIVE_FFMPEG_CRF).strip():
        args.extend(["-crf", str(NATIVE_FFMPEG_CRF).strip()])
    return args


def _segment_encode_args() -> list[list[str]]:
    primary = _video_encode_args()
    encoder = str(NATIVE_FFMPEG_ENCODER or "").strip()
    if encoder and encoder != "libx264":
        fallback = ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(NATIVE_FFMPEG_CRF).strip() or "20"]
        return [primary, fallback]
    return [primary]


def _encode_thumbnail_frame_segment(
    thumbnail_path: str,
    segment_path: str,
    width: int,
    height: int,
    duration: float,
    progress_callback=None,
) -> None:
    segment_duration = max(1 / VIDEO_FPS, duration)
    filter_complex = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[vout]"
    encode_candidates = _segment_encode_args()
    last_error = None
    for enc_idx, encode_args in enumerate(encode_candidates):
        try:
            _run_ffmpeg([
                FFMPEG_BIN, "-y",
                "-loop", "1", "-t", f"{segment_duration:.6f}", "-i", thumbnail_path,
                "-f", "lavfi", "-t", f"{segment_duration:.6f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-filter_complex", filter_complex,
                "-map", "[vout]", "-map", "1:a",
                "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p",
                *encode_args,
                "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-shortest", segment_path,
            ])
            if enc_idx > 0 and progress_callback:
                progress_callback("⚠ GPUエンコードに失敗したため libx264 で続行しました", "warning")
            return
        except Exception as e:
            last_error = e
            if enc_idx == 0 and len(encode_candidates) > 1:
                continue
            raise
    if last_error:
        raise last_error


def _script_character_names(script_text: str) -> set[str]:
    try:
        items = ScriptParser.parse_string(script_text or "")
    except Exception:
        _logger.error("native立ち絵用の台本パースに失敗しました", exc_info=True)
        raise
    return {str(item.get("character") or "").strip() for item in items if item.get("type") == "dialogue"}


def _character_inputs(width: int, height: int, script_text: str = "") -> list[CharacterVariantSet]:
    if not NATIVE_RENDER_CHARACTERS:
        return []
    used_names = _script_character_names(script_text)
    variants = [item for item in load_character_variants() if item.base and os.path.exists(item.base)]
    try:
        from core.channel_profile import get_active_profile
        from core.character_profile_store import list_characters
        from core.path_refs import resolve_path_ref
        profile = get_active_profile()
        if profile:
            known = {item.jp_name or item.name for item in variants}
            for character in list_characters(profile.profile_id):
                path = resolve_path_ref(character.portrait_png_path)
                if not path or not os.path.exists(path) or character.character_name in known:
                    continue
                key = character_variant_key(character.character_name)
                variants.append(CharacterVariantSet(key, path, path, path, path, path, path, {}, character.character_name))
                known.add(character.character_name)
    except Exception:
        _logger.error("キャラクター立ち絵設定の読み込みに失敗しました", exc_info=True)
        raise
    if not used_names:
        return variants
    return [item for item in variants if (item.jp_name or item.name) in used_names]


def _character_position(name: str, portrait: bool = False, index: int = 0, total: int = 2) -> str:
    side = NATIVE_CHARACTER_SIDE_MARGIN_SHORTS if portrait else NATIVE_CHARACTER_SIDE_MARGIN_LONG
    bottom = NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS if portrait else NATIVE_CHARACTER_BOTTOM_MARGIN_LONG
    if CHARACTER_UPPER_BODY_MODE:
        y_offset = CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET if portrait else CHARACTER_UPPER_BODY_LONG_Y_OFFSET
        bottom = bottom - y_offset
    y = f"H-h+{-bottom}" if bottom < 0 else f"H-h-{bottom}"
    if total <= 1:
        return f"(W-w)/2:{y}"
    if total > 2:
        return f"{side}+{index}*(W-w-{side * 2})/{max(1, total - 1)}:{y}"
    x_zunda = str(side)
    x_metan = f"W-w+{-side}" if side < 0 else f"W-w-{side}"
    return f"{x_zunda}:{y}" if index == 0 or name == "zundamon" else f"{x_metan}:{y}"


def _speaker_name(style: str) -> str | None:
    if style == "Zundamon":
        return "zundamon"
    if style == "Metan":
        return "metan"
    if style == "Reimu":
        return character_variant_key("霊夢")
    if style == "Marisa":
        return character_variant_key("魔理沙")
    return None


def _speaker_jp_name(speaking: str | None) -> str | None:
    if speaking == "zundamon":
        return "ずんだもん"
    if speaking == "metan":
        return "四国めたん"
    if speaking == character_variant_key("霊夢"):
        return "霊夢"
    if speaking == character_variant_key("魔理沙"):
        return "魔理沙"
    return None


def _known_expressions(speaking: str | None) -> set[str]:
    jp_name = _speaker_jp_name(speaking)
    if not jp_name:
        return set()
    return set(CHARACTER_EXPRESSION_PNGS.get(jp_name, {}).keys())


def _expression_fallback_reason(characters: list[CharacterVariantSet], speaking: str | None, expression: str | None) -> str | None:
    expression = str(expression or "").strip()
    if not expression or not speaking:
        return None
    known = _known_expressions(speaking)
    if expression not in known:
        return "unknown"
    character = next((item for item in characters if item.name == speaking), None)
    if not character or not character.expressions.get(expression):
        return "missing_asset"
    return None


def _character_base_path(character: CharacterVariantSet, speaking: str | None, expression: str | None) -> str | None:
    if character.name == speaking and expression:
        return character.base_for_expression(expression)
    return character.base


def _using_expression_png(character: CharacterVariantSet, speaking: str | None, expression: str | None) -> bool:
    """話者キャラが表情PNG（通常ベースではなく expression 指定）で描画される場合 True。
    表情PNG使用中は口パク・まばたきオーバーレイを両方無効化（二重口・二重目防止）。"""
    if character.name != speaking or not expression:
        return False
    path = character.expressions.get(str(expression).strip())
    return bool(path and os.path.exists(path))


def _background_transition_enabled(prev_bg_path: str | None, current_bg_path: str | None, duration: float) -> bool:
    if str(NATIVE_BACKGROUND_TRANSITION or "").strip().lower() in ("", "none", "off", "0", "false"):
        return False
    if not prev_bg_path or not current_bg_path:
        return False
    if os.path.abspath(prev_bg_path) == os.path.abspath(current_bg_path):
        return False
    return duration > 0.25 and NATIVE_BACKGROUND_TRANSITION_SEC > 0


def _background_transition_sec(duration: float) -> float:
    return min(float(NATIVE_BACKGROUND_TRANSITION_SEC), max(0.05, float(duration) * 0.45))


def _background_fill_filter(input_label: str, output_label: str, width: int, height: int) -> str:
    return f"{input_label}scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1{output_label}"


def _background_motion_filter(input_label: str, output_label: str, width: int, height: int, duration: float, segment_index: int) -> str:
    zoom_max = max(1.0, min(1.08, float(NATIVE_BG_ZOOM_MAX or 1.0)))
    duration = max(0.1, float(duration or 0.1))
    progress = f"min(t/{duration:.3f}\\,1)"
    base_scale = f"max({width}/iw\\,{height}/ih)"
    zoom = f"(1+{zoom_max - 1.0:.5f}*{progress})"
    scale_w = f"trunc(iw*{base_scale}*{zoom}/2)*2"
    scale_h = f"trunc(ih*{base_scale}*{zoom}/2)*2"
    variants = [
        (f"(iw-ow)*{progress}", f"(ih-oh)/2"),
        (f"(iw-ow)*(1-{progress})", f"(ih-oh)/2"),
        (f"(iw-ow)/2", f"(ih-oh)*{progress}"),
        (f"(iw-ow)/2", f"(ih-oh)*(1-{progress})"),
        (f"(iw-ow)*{progress}", f"(ih-oh)*(1-{progress})"),
        (f"(iw-ow)*(1-{progress})", f"(ih-oh)*{progress}"),
    ]
    x_expr, y_expr = variants[segment_index % len(variants)]
    return (
        f"{input_label}scale=w='{scale_w}':h='{scale_h}':eval=frame,"
        f"crop={width}:{height}:x='{x_expr}':y='{y_expr}',setsar=1{output_label}"
    )


def _blink_enable_expr(duration: float, character_name: str, speaking: str | None) -> str | None:
    duration = max(0.1, float(duration or 0.1))
    if speaking != character_name:
        return None
    blink_len = min(0.24, max(0.12, duration * 0.28))
    blink_start = max(0.04, min(duration * 0.45, duration - blink_len - 0.03))
    blink_end = min(duration, blink_start + blink_len)
    return f"between(t,{blink_start:.3f},{blink_end:.3f})"


def _character_scale_filter(input_index: int, output_label: str, scaled_char_h: int, bounce: bool) -> str:
    if not bounce:
        return f"[{input_index}:v]scale=-1:{scaled_char_h}{output_label}"
    bounce_sec = NATIVE_CHARACTER_BOUNCE_SEC
    scale_expr = (
        f"if(lte(t\\,{bounce_sec:.3f})\\,"
        f"{scaled_char_h}*(1+0.04*sin(PI*t/{bounce_sec:.3f}))\\,{scaled_char_h})"
    )
    return f"[{input_index}:v]scale=w=-1:h='{scale_expr}':eval=frame{output_label}"


def _maybe_shake_filter(input_label: str, output_label: str, width: int, height: int, enabled: bool) -> str:
    if not enabled:
        return f"{input_label}copy{output_label}"
    amp_x = NATIVE_SHAKE_AMP_X
    amp_y = NATIVE_SHAKE_AMP_Y
    pad = max(amp_x, amp_y) * 4
    return (
        f"{input_label}scale={width + pad}:{height + pad},"
        f"crop={width}:{height}:x='{pad // 2}+{amp_x}*sin(2*PI*t*24)':"
        f"y='{pad // 2}+{amp_y}*sin(2*PI*t*27)'{output_label}"
    )


def _segment_filter(
    width: int,
    height: int,
    ass_path: str,
    characters: list[CharacterVariantSet],
    speaking: str | None,
    expression: str | None,
    duration: float,
    has_background_transition: bool = False,
    segment_index: int = 0,
    effect: SegmentEffect | None = None,
    enable_motion_effects: bool = True,
) -> str:
    portrait = height > width
    char_h = NATIVE_CHARACTER_HEIGHT_SHORTS if portrait else NATIVE_CHARACTER_HEIGHT_LONG
    effects_on = bool(enable_motion_effects and NATIVE_ENABLE_MOTION_EFFECTS and portrait)
    bg_motion = bool(effects_on and NATIVE_ENABLE_BG_KEN_BURNS)
    bounce_on = bool(effects_on and NATIVE_ENABLE_CHARACTER_BOUNCE)
    shake_on = bool(effects_on and NATIVE_ENABLE_SHAKE and effect and effect.shake)
    bg_filter = _background_motion_filter("[0:v]", "[bg_current]", width, height, duration, segment_index) if bg_motion else _background_fill_filter("[0:v]", "[bg_current]", width, height)
    chains = [bg_filter]
    input_index = 2
    if has_background_transition:
        transition_sec = _background_transition_sec(duration)
        expr = f"if(lte(T\\,{transition_sec:.3f})\\,A*(1-T/{transition_sec:.3f})+B*(T/{transition_sec:.3f})\\,B)"
        chains.append(_background_fill_filter(f"[{input_index}:v]", "[bg_prev]", width, height))
        chains.append(f"[bg_prev][bg_current]blend=all_expr='{expr}'[base0]")
        input_index += 1
    else:
        chains.append("[bg_current]copy[base0]")
    current = "base0"
    overlay_num = 1
    if CHARACTER_UPPER_BODY_MODE:
        char_scale = CHARACTER_UPPER_BODY_SHORTS_SCALE if portrait else CHARACTER_UPPER_BODY_SCALE
    elif portrait:
        char_scale = NATIVE_SHORTS_CHARACTER_SCALE
    else:
        char_scale = 1.0
    scaled_char_h = int(round(char_h * char_scale))
    total_characters = len(characters)
    for char_idx, character in enumerate(characters):
        position = _character_position(character.name, portrait=portrait, index=char_idx, total=total_characters)
        char_bounce = bool(bounce_on and speaking == character.name)
        overlay_suffix = ":eval=frame" if char_bounce else ""
        chains.append(_character_scale_filter(input_index, f"[{character.name}_base]", scaled_char_h, char_bounce))
        chains.append(f"[{current}][{character.name}_base]overlay={position}{overlay_suffix}[base{overlay_num}]")
        current = f"base{overlay_num}"
        overlay_num += 1
        input_index += 1

        expr_png_active = _using_expression_png(character, speaking, expression)
        if NATIVE_ENABLE_LIPSYNC and speaking == character.name and not expr_png_active:
            if character.mouth_half and os.path.exists(character.mouth_half):
                chains.append(_character_scale_filter(input_index, f"[{character.name}_mouth_half]", scaled_char_h, char_bounce))
                chains.append(
                    f"[{current}][{character.name}_mouth_half]overlay={position}:"
                    f"enable='between(mod(t,0.24),0.12,0.20)'{overlay_suffix}[base{overlay_num}]"
                )
                current = f"base{overlay_num}"
                overlay_num += 1
                input_index += 1
            if character.mouth_open and os.path.exists(character.mouth_open):
                chains.append(_character_scale_filter(input_index, f"[{character.name}_mouth_open]", scaled_char_h, char_bounce))
                chains.append(
                    f"[{current}][{character.name}_mouth_open]overlay={position}:"
                    f"enable='between(mod(t,0.24),0.00,0.12)'{overlay_suffix}[base{overlay_num}]"
                )
                current = f"base{overlay_num}"
                overlay_num += 1
                input_index += 1

        blink_expr = _blink_enable_expr(duration, character.name, speaking)
        if NATIVE_ENABLE_BLINK and blink_expr and not expr_png_active and character.eye_closed and os.path.exists(character.eye_closed):
            chains.append(_character_scale_filter(input_index, f"[{character.name}_eye_closed]", scaled_char_h, char_bounce))
            chains.append(
                f"[{current}][{character.name}_eye_closed]overlay={position}:"
                f"enable='{blink_expr}'{overlay_suffix}[base{overlay_num}]"
            )
            current = f"base{overlay_num}"
            overlay_num += 1
            input_index += 1
    if shake_on:
        chains.append(_maybe_shake_filter(f"[{current}]", "[motion_shake]", width, height, True))
        current = "motion_shake"
    chains.append(f"[{current}]subtitles=filename='{_subtitles_filter_path(ass_path)}':original_size={width}x{height}[vout]")
    return ";".join(chains)


def _segment_character_inputs(duration: float, characters: list[CharacterVariantSet], speaking: str | None, expression: str | None) -> list[str]:
    args: list[str] = []
    for character in characters:
        paths = [_character_base_path(character, speaking, expression)]
        expr_png_active = _using_expression_png(character, speaking, expression)
        if NATIVE_ENABLE_LIPSYNC and speaking == character.name and not expr_png_active:
            paths.extend([character.mouth_half, character.mouth_open])
        if NATIVE_ENABLE_BLINK and _blink_enable_expr(duration, character.name, speaking) and not expr_png_active:
            paths.append(character.eye_closed)
        for path in paths:
            if path and os.path.exists(path):
                args.extend(["-loop", "1", "-t", f"{max(0.1, duration):.3f}", "-i", path])
    return args


def _write_subtitles(
    path: str,
    chunks: list[CaptionChunk],
    audio_durations: list[float],
    width: int,
    height: int,
    offset_sec: float = 0.0,
    telop: str | None = None,
    icon: str | None = None,
) -> None:
    font_size = int(round((NATIVE_SUBTITLE_FONT_SIZE_SHORTS if height >= 1600 else NATIVE_SUBTITLE_FONT_SIZE_LONG) * float(NATIVE_SUBTITLE_FONT_SCALE or 1.0)))
    margin_v = NATIVE_SUBTITLE_MARGIN_V_SHORTS if height >= 1600 else NATIVE_SUBTITLE_MARGIN_V_LONG
    alignment = NATIVE_SUBTITLE_ALIGNMENT_SHORTS if height >= 1600 else NATIVE_SUBTITLE_ALIGNMENT_LONG
    y_offset = NATIVE_SUBTITLE_Y_OFFSET_SHORTS if height >= 1600 else NATIVE_SUBTITLE_Y_OFFSET_LONG
    font_name = str(NATIVE_SUBTITLE_FONT or "Meiryo").replace(",", " ")
    box_enabled = bool(NATIVE_SUBTITLE_BOX_SHORTS) if height >= 1600 else False
    box_opacity = max(0.0, min(1.0, float(NATIVE_SUBTITLE_BOX_OPACITY_SHORTS or 0.0)))
    box_alpha = int(round((1.0 - box_opacity) * 255))
    box_color = f"&H{box_alpha:02X}000000"
    style_body = (
        "{name},{font_name},{font_size},{primary},&H00FFFFFF,{outline_color},&H80000000,"
        "1,0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},{alignment},70,70,{margin_v},1"
    )
    inner_outline_colors = {
        "Default": "&H00000000",
        "Zundamon": "&H002B9C26",
        "Metan": "&H009137BE",
    }
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: SubtitleBox,Arial,1,{box_color},&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        f"Style: PopTelopOuter,{font_name},{max(font_size + 8, 72)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{NATIVE_SUBTITLE_OUTER_STROKE_WIDTH + 2},2,5,60,60,0,1",
        f"Style: PopTelop,{font_name},{max(font_size + 8, 72)},&H00FFF7D6,&H00FFFFFF,&H002B2B2B,&H80000000,1,0,0,0,100,100,0,0,1,{NATIVE_SUBTITLE_STROKE_WIDTH},0,5,60,60,0,1",
        f"Style: ReactionIcon,{font_name},{max(font_size + 22, 96)},&H00FFF7D6,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{NATIVE_SUBTITLE_OUTER_STROKE_WIDTH},2,5,40,40,0,1",
    ]
    for name, inner_outline in inner_outline_colors.items():
        lines.append(
            "Style: " + style_body.format(
                name=f"{name}Outer",
                font_name=font_name,
                font_size=font_size,
                primary="&H00FFFFFF",
                outline_color="&H00000000",
                outline_width=NATIVE_SUBTITLE_OUTER_STROKE_WIDTH,
                shadow_depth=2,
                margin_v=margin_v,
                alignment=alignment,
            )
        )
        lines.append(
            "Style: " + style_body.format(
                name=name,
                font_name=font_name,
                font_size=font_size,
                primary="&H00FFFFFF",
                outline_color=inner_outline,
                outline_width=NATIVE_SUBTITLE_STROKE_WIDTH,
                shadow_depth=0,
                margin_v=margin_v,
                alignment=alignment,
            )
        )
    lines.extend([
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    wrap_chars = NATIVE_SUBTITLE_WRAP_CHARS_SHORTS if height >= 1600 else NATIVE_SUBTITLE_WRAP_CHARS_LONG
    t = 0.0
    for idx, dur in enumerate(audio_durations):
        text, style, _expression = chunks[idx] if idx < len(chunks) else ("", "Default", None)
        if text:
            start = max(0.0, t + offset_sec)
            end = max(start + 0.1, t + max(0.1, dur) + offset_sec)
            style_name = style if style in inner_outline_colors else "Default"
            wrapped_text = _wrap_subtitle(text, wrap_chars)
            line_count = wrapped_text.count("\n") + 1
            escaped_text = _ass_escape(wrapped_text)
            text_y = height // 2 + int(y_offset)
            override = f"{{\\pos({width // 2},{text_y})}}" if alignment == 5 and y_offset else ""
            if box_enabled and alignment == 5:
                box_w = int(width * 0.88)
                box_h = int(font_size * (NATIVE_SUBTITLE_BOX_LINE_HEIGHT + (line_count - 1) * 1.2)) + NATIVE_SUBTITLE_PADDING_Y * 2
                box_path = f"m {-box_w // 2} {-box_h // 2} l {box_w // 2} {-box_h // 2} {box_w // 2} {box_h // 2} {-box_w // 2} {box_h // 2}"
                lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},SubtitleBox,,0,0,0,,{{\\pos({width // 2},{text_y})\\p1}}{box_path}{{\\p0}}")
            lines.append(f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},{style_name}Outer,,0,0,0,,{override}{escaped_text}")
            lines.append(f"Dialogue: 2,{_ass_time(start)},{_ass_time(end)},{style_name},,0,0,0,,{override}{escaped_text}")
        t += max(0.0, dur) + NATIVE_INTER_DIALOGUE_GAP_SEC
    segment_duration = sum(max(0.0, dur) for dur in audio_durations)
    if telop and NATIVE_ENABLE_MOTION_EFFECTS and NATIVE_ENABLE_POP_TELOP:
        start = NATIVE_TELOP_POP_START_SEC
        end = min(max(0.85, segment_duration), NATIVE_TELOP_POP_MAX_SEC)
        if end > start + 0.1:
            telop_y = int(height * (0.29 if height > width else 0.22))
            escaped_telop = _ass_escape(telop)
            pop = (
                f"{{\\an5\\pos({width // 2},{telop_y})\\fscx72\\fscy72\\alpha&H20&"
                f"\\t(0,180,\\fscx112\\fscy112\\alpha&H00&)\\t(180,330,\\fscx100\\fscy100)"
                f"\\fad(40,120)}}"
            )
            lines.append(f"Dialogue: 5,{_ass_time(start)},{_ass_time(end)},PopTelopOuter,,0,0,0,,{pop}{escaped_telop}")
            lines.append(f"Dialogue: 6,{_ass_time(start)},{_ass_time(end)},PopTelop,,0,0,0,,{pop}{escaped_telop}")
    if icon and NATIVE_ENABLE_MOTION_EFFECTS:
        start = 0.02
        end = min(max(0.55, segment_duration), 0.95)
        if end > start + 0.1:
            icon_x = int(width * 0.70)
            icon_y = int(height * (0.23 if height > width else 0.20))
            pop = (
                f"{{\\an5\\pos({icon_x},{icon_y})\\fscx60\\fscy60\\alpha&H20&"
                f"\\t(0,150,\\fscx115\\fscy115\\alpha&H00&)\\t(150,260,\\fscx100\\fscy100)"
                f"\\fad(20,120)}}"
            )
            lines.append(f"Dialogue: 7,{_ass_time(start)},{_ass_time(end)},ReactionIcon,,0,0,0,,{pop}{_ass_escape(icon)}")
    with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write("\n".join(lines))


def _video_size(output_dir: str, script_text: str) -> tuple[int, int]:
    from config import config as _cfg
    base_name = os.path.basename(output_dir).lower()
    if base_name.startswith(_cfg.FOLDER_PREFIX_SHORTS.lower()) or base_name.startswith(("short_", "shorts_")):
        return 1080, 1920
    try:
        items = ScriptParser.parse_string(script_text or "")
        format_val = ""
        screen_format = ""
        for it in items:
            if it.get("type") == "video_format":
                format_val = str(it.get("text", "")).strip()
            elif it.get("type") == "screen_format":
                screen_format = str(it.get("text", "")).strip()
        fmt_lower = format_val.lower()
        if "shorts" in fmt_lower or "ショート" in format_val:
            return 1080, 1920
        if "ネタ会議" in format_val:
            # ネタ会議Long → 横、ネタ会議Shorts/ネタ会議 → 縦（デフォルト）
            if "long" in fmt_lower or "ロング" in format_val:
                return 1920, 1080
            if "横" in screen_format or "wide" in screen_format.lower():
                return 1920, 1080
            return 1080, 1920
    except Exception as _e:
        _logger.error("台本から画面サイズを推定できませんでした", exc_info=True)
        raise RuntimeError(f"Error: {_e}") from _e
    return 1920, 1080


class RenderCancelled(Exception):
    """レンダーがキャンセル要求により中断されたことを表す。"""


def render_native(
    output_dir: str,
    progress_callback=None,
    voice_speed_intro: float | None = None,
    voice_speed_body: float | None = None,
    estimated_duration_sec: float | None = None,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
    cancel_event=None,
) -> NativeRenderResult:
    """生成済み音声・背景アセットからネイティブMP4を生成する。"""
    output_dir = os.path.abspath(output_dir)
    audio_dir = os.path.join(output_dir, "audio")
    bg_dir = os.path.join(output_dir, "backgrounds")
    # 台本本文は metadata.db (videos.script_content) を正本として取得する。
    from core.metadata_db import get_script_content
    local_id = os.path.basename(output_dir.rstrip("/\\"))
    script_text = get_script_content(local_id)
    if not script_text:
        from core.error_codes import format_error
        raise FileNotFoundError(format_error("E-SCRIPT-MISSING", local_id))
    if not os.path.isdir(audio_dir):
        raise FileNotFoundError(f"audio フォルダが見つかりません: {audio_dir}")
    if not os.path.isdir(bg_dir):
        raise FileNotFoundError(f"backgrounds フォルダが見つかりません: {bg_dir}")

    audio_files = sorted(os.path.join(audio_dir, f) for f in os.listdir(audio_dir) if f.lower().endswith(".wav"))
    bg_files = sorted(os.path.join(bg_dir, f) for f in os.listdir(bg_dir) if f.lower().startswith("bg_") and f.lower().endswith(".png"))
    if not audio_files:
        raise FileNotFoundError("音声WAVがありません")
    if not bg_files:
        raise FileNotFoundError("背景PNGがありません")

    work_dir = os.path.join(output_dir, "_native_test")
    os.makedirs(work_dir, exist_ok=True)
    _clear_native_work_dir(work_dir)
    audio_list = os.path.join(work_dir, "audio_concat.txt")
    segment_list = os.path.join(work_dir, "segment_concat.txt")
    video_path = os.path.join(work_dir, "video_with_narration.mp4")
    output_path = _native_output_path(output_dir)
    bgm_selection = resolve_bgm_selection(
        bgm_mode=bgm_mode,
        bgm_id=bgm_id,
        bgm_volume_db=bgm_volume_db,
    )

    durations = [_wav_duration(path) for path in audio_files]
    total_audio = sum(durations)

    _encoder_name = str(NATIVE_FFMPEG_ENCODER or "h264_nvenc").strip() or "h264_nvenc"
    if progress_callback:
        progress_callback(f"🎞 native MP4: 音声{len(audio_files)}件 / 背景{len(bg_files)}枚を結合します")
        progress_callback(f"   🎬 エンコーダ: {_encoder_name}")

    width, height = _video_size(output_dir, script_text)
    characters = _character_inputs(width, height, script_text)
    script_captions_raw = _dialogue_captions(script_text)
    script_caption_count = len(script_captions_raw)
    script_char_count = sum(len(text) for text, _style, _expression in script_captions_raw)
    if script_caption_count != len(audio_files):
        missing = script_caption_count - len(audio_files)
        raise RuntimeError(
            f"字幕数とWAV数が一致しません（台本由来{script_caption_count}件 / WAV{len(audio_files)}件 / 差分{missing:+d}）。"
            "音声生成失敗の可能性があるため、欠けた音声を修正してから再実行してください。"
        )
    captions = _captions_for_audio_files(script_text, audio_files)
    is_shorts = height > width
    effects = _effects_for_audio_files(script_text, audio_files, is_shorts)

    segment_paths: list[str] = []
    if is_shorts:
        thumb_path = _thumbnail_path(output_dir)
        if thumb_path:
            thumb_segment_path = os.path.join(work_dir, "segment_0000_thumbnail.mp4")
            thumb_hold_sec = THUMBNAIL_HOLD_FRAMES_SHORTS / VIDEO_FPS
            _encode_thumbnail_frame_segment(thumb_path, thumb_segment_path, width, height, thumb_hold_sec, progress_callback)
            segment_paths.append(thumb_segment_path)
            if progress_callback:
                progress_callback(
                    f"   🖼 先頭サムネイル挿入: {os.path.basename(thumb_path)}"
                    f" ({THUMBNAIL_HOLD_FRAMES_SHORTS}フレーム / {thumb_hold_sec:.3f}秒)"
                )
    prev_bg_path: str | None = None
    warned_expression_fallbacks: set[tuple[str | None, str | None, str]] = set()
    motion_fallback_count = 0
    for idx, (audio_path, duration, caption, effect) in enumerate(zip(audio_files, durations, captions, effects), start=1):
        # セグメント境界でキャンセル要求を確認する（実行中ffmpegは現セグメント完了後に停止）
        if cancel_event is not None and cancel_event.is_set():
            raise RenderCancelled("レンダーをキャンセルしました")
        bg_path = _background_for_audio(audio_path, bg_files)
        ass_path = os.path.join(work_dir, f"subtitle_{idx:04d}.ass")
        segment_path = os.path.join(work_dir, f"segment_{idx:04d}.mp4")
        _write_subtitles(
            ass_path,
            [caption],
            [duration],
            width,
            height,
            offset_sec=NATIVE_SUBTITLE_OFFSET_SEC,
            telop=effect.telop,
            icon=effect.icon,
        )
        _caption_text, caption_style, expression = caption
        speaking = _speaker_name(caption_style)
        fallback_reason = _expression_fallback_reason(characters, speaking, expression)
        if fallback_reason and progress_callback:
            key = (speaking, expression, fallback_reason)
            if key not in warned_expression_fallbacks:
                warned_expression_fallbacks.add(key)
                if fallback_reason == "unknown":
                    progress_callback(f"⚠ native表情指定が未知です: {speaking or 'unknown'}[{expression}] → 既定表情を使用")
                else:
                    progress_callback(f"⚠ native表情素材がありません: {speaking or 'unknown'}[{expression}] → 既定表情を使用")
        has_bg_transition = _background_transition_enabled(prev_bg_path, bg_path, duration)
        filter_complex = _segment_filter(
            width,
            height,
            ass_path,
            characters,
            speaking,
            expression,
            duration,
            has_bg_transition,
            segment_index=idx - 1,
            effect=effect,
            enable_motion_effects=True,
        )
        inputs = [FFMPEG_BIN, "-y", "-loop", "1", "-t", f"{max(0.1, duration):.3f}", "-i", bg_path, "-i", audio_path]
        if has_bg_transition and prev_bg_path:
            inputs.extend(["-loop", "1", "-t", f"{max(0.1, duration):.3f}", "-i", prev_bg_path])
        inputs.extend(_segment_character_inputs(duration, characters, speaking, expression))
        last_error = None
        encode_candidates = _segment_encode_args()
        try:
            for enc_idx, encode_args in enumerate(encode_candidates):
                try:
                    _run_ffmpeg([
                        *inputs,
                        "-filter_complex", filter_complex,
                        "-map", "[vout]", "-map", "1:a",
                        "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p",
                        *encode_args,
                        "-c:a", "aac", "-ar", "48000", "-ac", "2",
                        "-shortest", segment_path,
                    ])
                    if enc_idx > 0 and progress_callback:
                        progress_callback("⚠ GPUエンコードに失敗したため libx264 で続行しました", "warning")
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if enc_idx == 0 and len(encode_candidates) > 1:
                        _logger.warning("GPUエンコードに失敗したため次のエンコード候補へ切り替えます", exc_info=True)
                        continue
                    raise
        except Exception as effect_error:
            if not (NATIVE_ENABLE_MOTION_EFFECTS and is_shorts):
                raise
            _logger.warning("軽量エフェクト付きsegmentレンダーに失敗したため静的レンダーへ切り替えます: segment=%s", idx, exc_info=True)
            motion_fallback_count += 1
            if progress_callback:
                progress_callback(f"⚠ segment {idx}: 軽量エフェクトに失敗したため静的レンダーで続行します")
            _write_subtitles(ass_path, [caption], [duration], width, height, offset_sec=NATIVE_SUBTITLE_OFFSET_SEC)
            filter_complex = _segment_filter(
                width,
                height,
                ass_path,
                characters,
                speaking,
                expression,
                duration,
                has_bg_transition,
                segment_index=idx - 1,
                effect=SegmentEffect(),
                enable_motion_effects=False,
            )
            last_error = None
            for enc_idx, encode_args in enumerate(encode_candidates):
                try:
                    _run_ffmpeg([
                        *inputs,
                        "-filter_complex", filter_complex,
                        "-map", "[vout]", "-map", "1:a",
                        "-r", str(VIDEO_FPS), "-pix_fmt", "yuv420p",
                        *encode_args,
                        "-c:a", "aac", "-ar", "48000", "-ac", "2",
                        "-shortest", segment_path,
                    ])
                    if enc_idx > 0 and progress_callback:
                        progress_callback("⚠ GPUエンコードに失敗したため libx264 で続行しました", "warning")
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if enc_idx == 0 and len(encode_candidates) > 1:
                        _logger.warning("静的segmentのGPUエンコードに失敗したため次の候補へ切り替えます", exc_info=True)
                        continue
                    raise RuntimeError(f"エフェクトなし再レンダーにも失敗しました: {e}") from effect_error
        if last_error:
            raise last_error
        segment_paths.append(segment_path)
        if progress_callback:
            progress_callback(f"   🎞 segment {idx}/{len(audio_files)} 完了")
        prev_bg_path = bg_path
        del filter_complex, inputs, encode_candidates, last_error

    _write_concat_list(segment_list, segment_paths)
    if progress_callback:
        progress_callback(f"🔗 セグメントを結合中... ({len(segment_paths)}件)")
    _run_ffmpeg([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", segment_list, "-c", "copy", video_path])

    loudnorm_filter = _native_loudnorm_filter()
    # Trial エディションは最終エンコードへ透かしを畳み込む（別パスの再エンコードを避ける）
    watermark = _trial_watermark_filter(width, height)
    wm_note = " + Trial透かし" if watermark else ""
    if bgm_selection["bgm_mode"] != "none":
        if progress_callback:
            progress_callback(f"🔊 BGMミックス・最終エンコード中...{wm_note} ({bgm_selection['bgm_display_name']})")
        audio_filter = (
            f"[0:a]volume=1.0[a0];[1:a]volume={float(bgm_selection['bgm_volume_db']):.1f}dB[a1];"
            "[a0][a1]amix=inputs=2:duration=first:dropout_transition=0"
        )
        if NATIVE_AUDIO_LOUDNORM_ENABLED:
            audio_filter += f"[mixed];[mixed]{loudnorm_filter}[a]"
        else:
            audio_filter += "[a]"
        if watermark:
            filter_complex = f"[0:v]{watermark}[vout];{audio_filter}"
            video_map = ["-map", "[vout]"]
            video_codec = [*_video_encode_args(), "-pix_fmt", "yuv420p"]
        else:
            filter_complex = audio_filter
            video_map = ["-map", "0:v"]
            video_codec = ["-c:v", "copy"]
        bgm_input_args = ["-stream_loop", "-1"] if bgm_selection["bgm_loop_enabled"] else []
        _run_ffmpeg([
            FFMPEG_BIN, "-y", "-i", video_path, *bgm_input_args, "-i", bgm_selection["bgm_file_path"],
            "-filter_complex", filter_complex,
            *video_map, "-map", "[a]", *video_codec, "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", output_path,
        ])
    else:
        if watermark:
            video_args = ["-vf", watermark, *_video_encode_args(), "-pix_fmt", "yuv420p"]
        else:
            video_args = ["-c:v", "copy"]
        if NATIVE_AUDIO_LOUDNORM_ENABLED:
            if progress_callback:
                progress_callback(f"🔊 音量正規化・最終エンコード中...{wm_note}")
            _run_ffmpeg([
                FFMPEG_BIN, "-y", "-i", video_path,
                "-map", "0:v", "-map", "0:a",
                *video_args, "-af", loudnorm_filter,
                "-c:a", "aac", "-ar", "48000", "-ac", "2",
                output_path,
            ])
        else:
            if progress_callback:
                progress_callback(f"📦 最終出力中...{wm_note}")
            if watermark:
                _run_ffmpeg([
                    FFMPEG_BIN, "-y", "-i", video_path,
                    *video_args, "-c:a", "copy", output_path,
                ])
            else:
                _run_ffmpeg([FFMPEG_BIN, "-y", "-i", video_path, "-c", "copy", output_path])

    actual_duration = media_duration_sec(output_path) or total_audio
    is_shorts = height > width
    dur_key, dur_label = _duration_status(actual_duration)
    if progress_callback:
        progress_callback(f"✅ native MP4出力: {output_path}")
        if estimated_duration_sec is not None:
            diff = actual_duration - estimated_duration_sec
            progress_callback(
                f"📏 native実尺: {actual_duration:.1f}秒"
                f" / 推定尺: {estimated_duration_sec:.1f}秒"
                f" / 差分: {diff:+.1f}秒"
            )
        if is_shorts:
            progress_callback(f"📏 native実尺評価: {actual_duration:.1f}秒 {dur_label}")
        if NATIVE_RENDER_CHARACTERS and is_shorts:
            char_scale = CHARACTER_UPPER_BODY_SHORTS_SCALE if CHARACTER_UPPER_BODY_MODE else NATIVE_SHORTS_CHARACTER_SCALE
            progress_callback(f"🧍 nativeキャラ倍率: {char_scale:g}")
        if is_shorts:
            motion_status = "enabled" if NATIVE_ENABLE_MOTION_EFFECTS else "disabled"
            progress_callback(f"✨ native軽量エフェクト: {motion_status} / fallback_segments={motion_fallback_count}")
        if NATIVE_AUDIO_LOUDNORM_ENABLED:
            progress_callback(
                "🔊 native audio loudnorm: "
                f"I={NATIVE_AUDIO_LOUDNORM_I:g} / TP={NATIVE_AUDIO_LOUDNORM_TP:g} / LRA={NATIVE_AUDIO_LOUDNORM_LRA:g}"
            )
        else:
            progress_callback("🔊 native audio loudnorm: disabled")
        progress_callback(f"🔊 native audio ebur128:\n{_audio_analysis_summary(output_path)}")

    _save_render_info(output_dir, {
        "render_engine": "native",
        "estimated_duration_sec": estimated_duration_sec,
        "actual_duration_sec": round(actual_duration, 2),
        "actual_duration_status": dur_key,
        "loudnorm_enabled": bool(NATIVE_AUDIO_LOUDNORM_ENABLED),
        "loudnorm_i": NATIVE_AUDIO_LOUDNORM_I,
        "loudnorm_tp": NATIVE_AUDIO_LOUDNORM_TP,
        "loudnorm_lra": NATIVE_AUDIO_LOUDNORM_LRA,
        "motion_effects_enabled": bool(NATIVE_ENABLE_MOTION_EFFECTS and is_shorts),
        "motion_effects_fallback_segments": motion_fallback_count,
        **bgm_selection,
    })

    if progress_callback:
        # silence計測（セグメント間のNATIVE_INTER_DIALOGUE_GAP_SEC合計）
        silence_total = NATIVE_INTER_DIALOGUE_GAP_SEC * max(0, len(durations) - 1)
        median_silence = NATIVE_INTER_DIALOGUE_GAP_SEC
        max_silence = NATIVE_INTER_DIALOGUE_GAP_SEC  # 現状全セグメント同一値

        cps = script_char_count / total_audio if total_audio > 0 else 0.0
        if cps < 6.0:
            speed_verdict = "ゆっくり・聞きやすい"
        elif cps < 7.5:
            speed_verdict = "Shorts向きで良い"
        elif cps < 8.5:
            speed_verdict = "速めだが許容"
        else:
            speed_verdict = "早口注意"

        from config import (
            NATIVE_SHORTS_CHARS_MUST_FIX_MIN,
            NATIVE_SHORTS_LINES_IDEAL_MAX,
            NATIVE_SHORTS_LINES_IDEAL_MIN,
            NATIVE_SHORTS_LINES_MUST_FIX,
            NATIVE_SHORTS_LINES_WARNING,
            NATIVE_SHORTS_TARGET_CHARS_MAX,
            NATIVE_SHORTS_TARGET_CHARS_MIN,
        )
        line_ok = NATIVE_SHORTS_LINES_IDEAL_MIN <= script_caption_count <= NATIVE_SHORTS_LINES_IDEAL_MAX
        chars_ok = NATIVE_SHORTS_TARGET_CHARS_MIN <= script_char_count <= NATIVE_SHORTS_TARGET_CHARS_MAX
        if script_caption_count >= NATIVE_SHORTS_LINES_MUST_FIX:
            volume_verdict = f"must_fix（{script_caption_count}行以上）"
        elif script_caption_count < NATIVE_SHORTS_LINES_IDEAL_MIN or script_char_count < NATIVE_SHORTS_CHARS_MUST_FIX_MIN:
            volume_verdict = (
                f"台本量不足（{script_caption_count}行/{script_char_count}字 / "
                f"最低: {NATIVE_SHORTS_LINES_IDEAL_MIN}行・{NATIVE_SHORTS_CHARS_MUST_FIX_MIN}字 / "
                f"目標: {NATIVE_SHORTS_TARGET_CHARS_MIN}〜{NATIVE_SHORTS_TARGET_CHARS_MAX}字）"
            )
        elif line_ok and chars_ok:
            volume_verdict = "OK"
        elif script_caption_count < NATIVE_SHORTS_LINES_WARNING:
            volume_verdict = "OK（行数または文字数がやや多め）"
        else:
            volume_verdict = f"warning（{script_caption_count}行）"

        intro_spd = f"{voice_speed_intro:.2f}" if voice_speed_intro is not None else "不明"
        body_spd = f"{voice_speed_body:.2f}" if voice_speed_body is not None else "不明"

        progress_callback(
            f"📊 render_engine: native\n"
            f"   voice_speed_intro: {intro_spd} / voice_speed_body: {body_spd}\n"
            f"   dialogue_lines: {script_caption_count} / script_chars: {script_char_count}\n"
            f"   audio_duration_total: {total_audio:.1f}秒 / silence_total: {silence_total:.2f}秒\n"
            f"   median_silence: {median_silence:.2f}秒 / max_silence: {max_silence:.2f}秒\n"
            f"   speech_chars_per_sec: {cps:.2f} / final_video_duration: {actual_duration:.1f}秒\n"
            f"   速度判定: {speed_verdict} / 台本量判定: {volume_verdict}"
        )
    result = NativeRenderResult(
        output_path=output_path,
        duration_sec=actual_duration,
        audio_duration_sec=total_audio,
        audio_count=len(audio_files),
        background_count=len(bg_files),
    )
    del characters, captions, durations, audio_files, bg_files, segment_paths
    gc.collect()
    return result
