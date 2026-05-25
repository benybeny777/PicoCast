import json
import os
import gc
import re
import subprocess
import wave
from dataclasses import dataclass

from config import (
    BGM_PATH,
    FFMPEG_BIN,
    NATIVE_AUDIO_LOUDNORM_ENABLED,
    NATIVE_AUDIO_LOUDNORM_I,
    NATIVE_AUDIO_LOUDNORM_LRA,
    NATIVE_AUDIO_LOUDNORM_TP,
    NATIVE_BACKGROUND_TRANSITION,
    NATIVE_BACKGROUND_TRANSITION_SEC,
    CHARACTER_UPPER_BODY_LONG_Y_OFFSET,
    CHARACTER_UPPER_BODY_MODE,
    CHARACTER_UPPER_BODY_SCALE,
    CHARACTER_UPPER_BODY_SHORTS_SCALE,
    CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET,
    CHARACTER_EXPRESSION_PNGS,
    NATIVE_BGM_VOLUME_DB,
    NATIVE_CHARACTER_HEIGHT_LONG,
    NATIVE_CHARACTER_HEIGHT_SHORTS,
    NATIVE_CHARACTER_BOTTOM_MARGIN_LONG,
    NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS,
    NATIVE_CHARACTER_SIDE_MARGIN_LONG,
    NATIVE_CHARACTER_SIDE_MARGIN_SHORTS,
    NATIVE_ENABLE_BLINK,
    NATIVE_ENABLE_LIPSYNC,
    NATIVE_FFMPEG_CQ,
    NATIVE_FFMPEG_CRF,
    NATIVE_FFMPEG_ENCODER,
    NATIVE_FFMPEG_PRESET,
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
    NATIVE_SUBTITLE_Y_OFFSET_LONG,
    NATIVE_SUBTITLE_Y_OFFSET_SHORTS,
    VIDEO_FPS,
    THUMBNAIL_HOLD_FRAMES_SHORTS,
)
from core.native_character_assets import CharacterVariantSet, load_character_variants
from core.parser import ScriptParser


INTER_DIALOGUE_GAP_SEC = 0.0
CaptionChunk = tuple[str, str, str | None]


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
                pass


def _run_ffmpeg(args: list[str]) -> None:
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        startupinfo=startupinfo,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").splitlines()[-20:])
        raise RuntimeError(f"ffmpeg failed ({proc.returncode})\n{tail}")


def _run_ffmpeg_capture(args: list[str]) -> subprocess.CompletedProcess:
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        startupinfo=startupinfo,
    )


def _ffprobe_bin() -> str:
    base = os.path.basename(str(FFMPEG_BIN or "ffmpeg")).lower()
    if base in {"ffmpeg", "ffmpeg.exe"}:
        return os.path.join(os.path.dirname(FFMPEG_BIN), "ffprobe.exe" if base.endswith(".exe") else "ffprobe") if os.path.dirname(FFMPEG_BIN) else ("ffprobe.exe" if base.endswith(".exe") else "ffprobe")
    return "ffprobe"


def media_duration_sec(path: str) -> float | None:
    if not path or not os.path.exists(path):
        return None
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        proc = subprocess.run(
            [
                _ffprobe_bin(),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
        )
        if proc.returncode != 0:
            return None
        return float((proc.stdout or "").strip())
    except Exception:
        return None


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
    """Returns (status_key, display_label) for Shorts duration evaluation."""
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
    meta_dir = os.path.join(output_dir, "_meta")
    os.makedirs(meta_dir, exist_ok=True)
    path = os.path.join(meta_dir, "render_info.json")
    existing: dict = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.update(info)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


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
        return f"音量解析失敗: {e}"
    finally:
        proc = None


def _concat_escape(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")


def _filter_escape_path(path: str) -> str:
    text = os.path.abspath(path).replace("\\", "/")
    text = re.sub(r"^([A-Za-z]):", r"\1\\:", text)
    return text.replace("'", r"\'")


def _ass_escape(text: str) -> str:
    text = str(text or "").replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return text.replace("\n", r"\N")


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
    return "Default"


def _audio_stem_key(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", str(text or ""))[:20].strip()


def _dialogue_captions(script_path: str) -> list[CaptionChunk]:
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            items = ScriptParser.parse_string(f.read())
    except Exception:
        return []
    captions: list[CaptionChunk] = []
    for item in items:
        if item.get("type") == "dialogue":
            style = _caption_style(item.get("character", ""))
            expression = item.get("expression")
            captions.extend((text, style, expression) for text in _split_at_punctuation(item.get("text", "")))
    return captions


def _captions_for_audio_files(script_path: str, audio_files: list[str]) -> list[CaptionChunk]:
    script_captions = _dialogue_captions(script_path)
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
                progress_callback("⚠ GPUエンコードに失敗したため libx264 で続行しました")
            return
        except Exception as e:
            last_error = e
            if enc_idx == 0 and len(encode_candidates) > 1:
                continue
            raise
    if last_error:
        raise last_error


def _character_inputs(width: int, height: int) -> list[CharacterVariantSet]:
    if not NATIVE_RENDER_CHARACTERS:
        return []
    return [item for item in load_character_variants() if item.base and os.path.exists(item.base)]


def _character_position(name: str, portrait: bool = False) -> str:
    side = NATIVE_CHARACTER_SIDE_MARGIN_SHORTS if portrait else NATIVE_CHARACTER_SIDE_MARGIN_LONG
    bottom = NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS if portrait else NATIVE_CHARACTER_BOTTOM_MARGIN_LONG
    if CHARACTER_UPPER_BODY_MODE:
        y_offset = CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET if portrait else CHARACTER_UPPER_BODY_LONG_Y_OFFSET
        bottom = bottom - y_offset
    y = f"H-h+{-bottom}" if bottom < 0 else f"H-h-{bottom}"
    x_zunda = str(side)
    x_metan = f"W-w+{-side}" if side < 0 else f"W-w-{side}"
    return f"{x_zunda}:{y}" if name == "zundamon" else f"{x_metan}:{y}"


def _speaker_name(style: str) -> str | None:
    if style == "Zundamon":
        return "zundamon"
    if style == "Metan":
        return "metan"
    return None


def _speaker_jp_name(speaking: str | None) -> str | None:
    if speaking == "zundamon":
        return "ずんだもん"
    if speaking == "metan":
        return "四国めたん"
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
    """True when the speaking character is rendered with an expression PNG (not the regular base).
    Both lipsync mouth and blink overlays are suppressed to avoid double-mouth/eye glitches."""
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


def _blink_enable_expr(duration: float, character_name: str, speaking: str | None) -> str | None:
    duration = max(0.1, float(duration or 0.1))
    if speaking != character_name:
        return None
    blink_len = min(0.24, max(0.12, duration * 0.28))
    blink_start = max(0.04, min(duration * 0.45, duration - blink_len - 0.03))
    blink_end = min(duration, blink_start + blink_len)
    return f"between(t,{blink_start:.3f},{blink_end:.3f})"


def _segment_filter(
    width: int,
    height: int,
    ass_path: str,
    characters: list[CharacterVariantSet],
    speaking: str | None,
    expression: str | None,
    duration: float,
    has_background_transition: bool = False,
) -> str:
    portrait = height > width
    char_h = NATIVE_CHARACTER_HEIGHT_SHORTS if portrait else NATIVE_CHARACTER_HEIGHT_LONG
    chains = [f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[bg_current]"]
    input_index = 2
    if has_background_transition:
        transition_sec = _background_transition_sec(duration)
        expr = f"if(lte(T\\,{transition_sec:.3f})\\,A*(1-T/{transition_sec:.3f})+B*(T/{transition_sec:.3f})\\,B)"
        chains.append(f"[{input_index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[bg_prev]")
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
    for char_idx, character in enumerate(characters):
        position = _character_position(character.name, portrait=portrait)
        chains.append(f"[{input_index}:v]scale=-1:{scaled_char_h}[{character.name}_base]")
        chains.append(f"[{current}][{character.name}_base]overlay={position}[base{overlay_num}]")
        current = f"base{overlay_num}"
        overlay_num += 1
        input_index += 1

        expr_png_active = _using_expression_png(character, speaking, expression)
        if NATIVE_ENABLE_LIPSYNC and speaking == character.name and not expr_png_active:
            if character.mouth_half and os.path.exists(character.mouth_half):
                chains.append(f"[{input_index}:v]scale=-1:{scaled_char_h}[{character.name}_mouth_half]")
                chains.append(
                    f"[{current}][{character.name}_mouth_half]overlay={position}:"
                    f"enable='between(mod(t,0.24),0.12,0.20)'[base{overlay_num}]"
                )
                current = f"base{overlay_num}"
                overlay_num += 1
                input_index += 1
            if character.mouth_open and os.path.exists(character.mouth_open):
                chains.append(f"[{input_index}:v]scale=-1:{scaled_char_h}[{character.name}_mouth_open]")
                chains.append(
                    f"[{current}][{character.name}_mouth_open]overlay={position}:"
                    f"enable='between(mod(t,0.24),0.00,0.12)'[base{overlay_num}]"
                )
                current = f"base{overlay_num}"
                overlay_num += 1
                input_index += 1

        blink_expr = _blink_enable_expr(duration, character.name, speaking)
        if NATIVE_ENABLE_BLINK and blink_expr and not expr_png_active and character.eye_closed and os.path.exists(character.eye_closed):
            chains.append(f"[{input_index}:v]scale=-1:{scaled_char_h}[{character.name}_eye_closed]")
            chains.append(
                f"[{current}][{character.name}_eye_closed]overlay={position}:"
                f"enable='{blink_expr}'[base{overlay_num}]"
            )
            current = f"base{overlay_num}"
            overlay_num += 1
            input_index += 1
    chains.append(f"[{current}]subtitles='{_filter_escape_path(ass_path)}'[vout]")
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
    t = 0.0
    for idx, dur in enumerate(audio_durations):
        text, style, _expression = chunks[idx] if idx < len(chunks) else ("", "Default", None)
        if text:
            start = max(0.0, t + offset_sec)
            end = max(start + 0.1, t + max(0.1, dur) + offset_sec)
            style_name = style if style in inner_outline_colors else "Default"
            escaped_text = _ass_escape(text)
            text_y = height // 2 + int(y_offset)
            override = f"{{\\pos({width // 2},{text_y})}}" if alignment == 5 and y_offset else ""
            if box_enabled and alignment == 5:
                box_w = int(width * 0.88)
                box_h = int(font_size * NATIVE_SUBTITLE_BOX_LINE_HEIGHT) + NATIVE_SUBTITLE_PADDING_Y * 2
                box_path = f"m {-box_w // 2} {-box_h // 2} l {box_w // 2} {-box_h // 2} {box_w // 2} {box_h // 2} {-box_w // 2} {box_h // 2}"
                lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},SubtitleBox,,0,0,0,,{{\\pos({width // 2},{text_y})\\p1}}{box_path}{{\\p0}}")
            lines.append(f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},{style_name}Outer,,0,0,0,,{override}{escaped_text}")
            lines.append(f"Dialogue: 2,{_ass_time(start)},{_ass_time(end)},{style_name},,0,0,0,,{override}{escaped_text}")
        t += max(0.0, dur) + INTER_DIALOGUE_GAP_SEC
    with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write("\n".join(lines))


def _video_size(output_dir: str, script_path: str) -> tuple[int, int]:
    if os.path.basename(output_dir).startswith(("[Shorts]", "[SHORT]")):
        return 1080, 1920
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            items = ScriptParser.parse_string(f.read())
        if any(it.get("type") == "video_format" and str(it.get("text", "")).strip().lower() in ("shorts", "short") for it in items):
            return 1080, 1920
    except Exception:
        pass
    return 1920, 1080


def render_native_test(
    output_dir: str,
    progress_callback=None,
    voice_speed_intro: float | None = None,
    voice_speed_body: float | None = None,
    estimated_duration_sec: float | None = None,
) -> NativeRenderResult:
    """Create a simple YMM-free MP4 from generated audio/background assets."""
    output_dir = os.path.abspath(output_dir)
    script_path = os.path.join(output_dir, "script.txt")
    audio_dir = os.path.join(output_dir, "audio")
    bg_dir = os.path.join(output_dir, "backgrounds")
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"script.txt が見つかりません: {script_path}")
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

    durations = [_wav_duration(path) for path in audio_files]
    total_audio = sum(durations)

    if progress_callback:
        progress_callback(f"🎞 native MP4: 音声{len(audio_files)}件 / 背景{len(bg_files)}枚を結合します")

    width, height = _video_size(output_dir, script_path)
    characters = _character_inputs(width, height)
    script_captions_raw = _dialogue_captions(script_path)
    script_caption_count = len(script_captions_raw)
    script_char_count = sum(len(text) for text, _style, _expression in script_captions_raw)
    if script_caption_count != len(audio_files):
        missing = script_caption_count - len(audio_files)
        raise RuntimeError(
            f"字幕数とWAV数が一致しません（台本由来{script_caption_count}件 / WAV{len(audio_files)}件 / 差分{missing:+d}）。"
            "音声生成失敗の可能性があるため、欠けた音声を修正してから再実行してください。"
        )
    captions = _captions_for_audio_files(script_path, audio_files)

    segment_paths: list[str] = []
    is_shorts = height > width
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
    for idx, (audio_path, duration, caption) in enumerate(zip(audio_files, durations, captions), start=1):
        bg_path = _background_for_audio(audio_path, bg_files)
        ass_path = os.path.join(work_dir, f"subtitle_{idx:04d}.ass")
        segment_path = os.path.join(work_dir, f"segment_{idx:04d}.mp4")
        _write_subtitles(ass_path, [caption], [duration], width, height, offset_sec=NATIVE_SUBTITLE_OFFSET_SEC)
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
        filter_complex = _segment_filter(width, height, ass_path, characters, speaking, expression, duration, has_bg_transition)
        inputs = [FFMPEG_BIN, "-y", "-loop", "1", "-t", f"{max(0.1, duration):.3f}", "-i", bg_path, "-i", audio_path]
        if has_bg_transition and prev_bg_path:
            inputs.extend(["-loop", "1", "-t", f"{max(0.1, duration):.3f}", "-i", prev_bg_path])
        inputs.extend(_segment_character_inputs(duration, characters, speaking, expression))
        last_error = None
        encode_candidates = _segment_encode_args()
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
                    progress_callback("⚠ GPUエンコードに失敗したため libx264 で続行しました")
                last_error = None
                break
            except Exception as e:
                last_error = e
                if enc_idx == 0 and len(encode_candidates) > 1:
                    continue
                raise
        if last_error:
            raise last_error
        segment_paths.append(segment_path)
        if progress_callback:
            progress_callback(f"   🎞 segment {idx}/{len(audio_files)} 完了")
        prev_bg_path = bg_path
        del filter_complex, inputs, encode_candidates, last_error

    _write_concat_list(segment_list, segment_paths)
    _run_ffmpeg([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", segment_list, "-c", "copy", video_path])

    loudnorm_filter = _native_loudnorm_filter()
    if BGM_PATH and os.path.exists(BGM_PATH):
        audio_filter = (
            f"[0:a]volume=1.0[a0];[1:a]volume={NATIVE_BGM_VOLUME_DB:.1f}dB[a1];"
            "[a0][a1]amix=inputs=2:duration=first:dropout_transition=0"
        )
        if NATIVE_AUDIO_LOUDNORM_ENABLED:
            audio_filter += f"[mixed];[mixed]{loudnorm_filter}[a]"
        else:
            audio_filter += "[a]"
        _run_ffmpeg([
            FFMPEG_BIN, "-y", "-i", video_path, "-stream_loop", "-1", "-i", BGM_PATH,
            "-filter_complex", audio_filter,
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", output_path,
        ])
    else:
        if NATIVE_AUDIO_LOUDNORM_ENABLED:
            _run_ffmpeg([
                FFMPEG_BIN, "-y", "-i", video_path,
                "-map", "0:v", "-map", "0:a",
                "-c:v", "copy", "-af", loudnorm_filter,
                "-c:a", "aac", "-ar", "48000", "-ac", "2",
                output_path,
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
    })

    if progress_callback:
        # silence計測（セグメント間のINTER_DIALOGUE_GAP_SEC合計）
        silence_total = INTER_DIALOGUE_GAP_SEC * max(0, len(durations) - 1)
        median_silence = INTER_DIALOGUE_GAP_SEC
        max_silence = INTER_DIALOGUE_GAP_SEC  # 現状全セグメント同一値

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
