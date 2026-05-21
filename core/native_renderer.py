import os
import re
import subprocess
import wave
from dataclasses import dataclass

from config import (
    BGM_PATH,
    BGM_VOLUME,
    FFMPEG_BIN,
    NATIVE_BACKGROUND_TRANSITION,
    NATIVE_BACKGROUND_TRANSITION_SEC,
    NATIVE_CHARACTER_HEIGHT_LONG,
    NATIVE_CHARACTER_HEIGHT_SHORTS,
    NATIVE_ENABLE_BLINK,
    NATIVE_ENABLE_LIPSYNC,
    NATIVE_FFMPEG_CQ,
    NATIVE_FFMPEG_CRF,
    NATIVE_FFMPEG_ENCODER,
    NATIVE_FFMPEG_PRESET,
    NATIVE_RENDER_CHARACTERS,
    NATIVE_SUBTITLE_OFFSET_SEC,
    VIDEO_FPS,
)
from core.native_character_assets import CharacterVariantSet, load_character_variants
from core.parser import ScriptParser


INTER_DIALOGUE_GAP_SEC = 0.0


@dataclass
class NativeRenderResult:
    output_path: str
    duration_sec: float
    audio_count: int
    background_count: int


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


def _wav_duration(path: str) -> float:
    with wave.open(path, "rb") as wr:
        return wr.getnframes() / float(wr.getframerate())


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


def _dialogue_captions(script_path: str) -> list[tuple[str, str]]:
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            items = ScriptParser.parse_string(f.read())
    except Exception:
        return []
    captions: list[tuple[str, str]] = []
    for item in items:
        if item.get("type") == "dialogue":
            style = _caption_style(item.get("character", ""))
            captions.extend((text, style) for text in _split_at_punctuation(item.get("text", "")))
    return captions


def _captions_for_audio_files(script_path: str, audio_files: list[str]) -> list[tuple[str, str]]:
    script_captions = _dialogue_captions(script_path)
    result: list[tuple[str, str]] = []
    search_from = 0
    for audio_path in audio_files:
        audio_text = _audio_caption(audio_path)
        audio_key = _audio_stem_key(audio_text)
        matched = None
        for idx in range(search_from, len(script_captions)):
            script_text, style = script_captions[idx]
            if _audio_stem_key(script_text) == audio_key:
                matched = (script_text, style)
                search_from = idx + 1
                break
        if matched is None:
            matched = (audio_text, "Default")
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


def _character_inputs(width: int, height: int) -> list[CharacterVariantSet]:
    if not NATIVE_RENDER_CHARACTERS:
        return []
    return [item for item in load_character_variants() if item.base and os.path.exists(item.base)]


def _character_position(name: str) -> str:
    return "40:H-h-40" if name == "zundamon" else "W-w-40:H-h-40"


def _speaker_name(style: str) -> str | None:
    if style == "Zundamon":
        return "zundamon"
    if style == "Metan":
        return "metan"
    return None


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
    duration: float,
    has_background_transition: bool = False,
) -> str:
    char_h = NATIVE_CHARACTER_HEIGHT_SHORTS if height > width else NATIVE_CHARACTER_HEIGHT_LONG
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
    for char_idx, character in enumerate(characters):
        position = _character_position(character.name)
        chains.append(f"[{input_index}:v]scale=-1:{char_h}[{character.name}_base]")
        chains.append(f"[{current}][{character.name}_base]overlay={position}[base{overlay_num}]")
        current = f"base{overlay_num}"
        overlay_num += 1
        input_index += 1

        if NATIVE_ENABLE_LIPSYNC and speaking == character.name:
            if character.mouth_half and os.path.exists(character.mouth_half):
                chains.append(f"[{input_index}:v]scale=-1:{char_h}[{character.name}_mouth_half]")
                chains.append(
                    f"[{current}][{character.name}_mouth_half]overlay={position}:"
                    f"enable='between(mod(t,0.24),0.12,0.20)'[base{overlay_num}]"
                )
                current = f"base{overlay_num}"
                overlay_num += 1
                input_index += 1
            if character.mouth_open and os.path.exists(character.mouth_open):
                chains.append(f"[{input_index}:v]scale=-1:{char_h}[{character.name}_mouth_open]")
                chains.append(
                    f"[{current}][{character.name}_mouth_open]overlay={position}:"
                    f"enable='between(mod(t,0.24),0.00,0.12)'[base{overlay_num}]"
                )
                current = f"base{overlay_num}"
                overlay_num += 1
                input_index += 1

        blink_expr = _blink_enable_expr(duration, character.name, speaking)
        if NATIVE_ENABLE_BLINK and blink_expr and character.eye_closed and os.path.exists(character.eye_closed):
            chains.append(f"[{input_index}:v]scale=-1:{char_h}[{character.name}_eye_closed]")
            chains.append(
                f"[{current}][{character.name}_eye_closed]overlay={position}:"
                f"enable='{blink_expr}'[base{overlay_num}]"
            )
            current = f"base{overlay_num}"
            overlay_num += 1
            input_index += 1
    chains.append(f"[{current}]subtitles='{_filter_escape_path(ass_path)}'[vout]")
    return ";".join(chains)


def _segment_character_inputs(duration: float, characters: list[CharacterVariantSet], speaking: str | None) -> list[str]:
    args: list[str] = []
    for character in characters:
        paths = [character.base]
        if NATIVE_ENABLE_LIPSYNC and speaking == character.name:
            paths.extend([character.mouth_half, character.mouth_open])
        if NATIVE_ENABLE_BLINK and _blink_enable_expr(duration, character.name, speaking):
            paths.append(character.eye_closed)
        for path in paths:
            if path and os.path.exists(path):
                args.extend(["-loop", "1", "-t", f"{max(0.1, duration):.3f}", "-i", path])
    return args


def _write_subtitles(
    path: str,
    chunks: list[tuple[str, str]],
    audio_durations: list[float],
    width: int,
    height: int,
    offset_sec: float = 0.0,
) -> None:
    font_size = 64 if height >= 1600 else 52
    margin_v = 180 if height >= 1600 else 70
    style_body = (
        "{name},Meiryo,{font_size},{primary},&H00FFFFFF,&H00181818,&H80000000,"
        "1,0,0,0,100,100,0,0,1,5,1,2,70,70,{margin_v},1"
    )
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
        "Style: " + style_body.format(name="Default", font_size=font_size, primary="&H00FFFFFF", margin_v=margin_v),
        "Style: " + style_body.format(name="Zundamon", font_size=font_size, primary="&H0067F28B", margin_v=margin_v),
        "Style: " + style_body.format(name="Metan", font_size=font_size, primary="&H00F6A0FF", margin_v=margin_v),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    t = 0.0
    for idx, dur in enumerate(audio_durations):
        text, style = chunks[idx] if idx < len(chunks) else ("", "Default")
        if text:
            start = max(0.0, t + offset_sec)
            end = max(start + 0.1, t + max(0.1, dur) + offset_sec)
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{_ass_escape(text)}")
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


def render_native_test(output_dir: str, progress_callback=None) -> NativeRenderResult:
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
    audio_list = os.path.join(work_dir, "audio_concat.txt")
    segment_list = os.path.join(work_dir, "segment_concat.txt")
    video_path = os.path.join(work_dir, "video_with_narration.mp4")
    output_path = os.path.join(output_dir, os.path.basename(output_dir) + "_native_test.mp4")

    durations = [_wav_duration(path) for path in audio_files]
    total_audio = sum(durations)

    if progress_callback:
        progress_callback(f"🎞 YMMなし(test): 音声{len(audio_files)}件 / 背景{len(bg_files)}枚を結合します")

    width, height = _video_size(output_dir, script_path)
    characters = _character_inputs(width, height)
    script_caption_count = len(_dialogue_captions(script_path))
    captions = _captions_for_audio_files(script_path, audio_files)
    if progress_callback and script_caption_count != len(audio_files):
        progress_callback(f"⚠ 字幕数補正: 台本由来{script_caption_count}件 / WAV{len(audio_files)}件。WAV順に合わせて字幕を作ります")

    segment_paths: list[str] = []
    prev_bg_path: str | None = None
    for idx, (audio_path, duration, caption) in enumerate(zip(audio_files, durations, captions), start=1):
        bg_path = _background_for_audio(audio_path, bg_files)
        ass_path = os.path.join(work_dir, f"subtitle_{idx:04d}.ass")
        segment_path = os.path.join(work_dir, f"segment_{idx:04d}.mp4")
        _write_subtitles(ass_path, [caption], [duration], width, height, offset_sec=NATIVE_SUBTITLE_OFFSET_SEC)
        _caption_text, caption_style = caption
        speaking = _speaker_name(caption_style)
        has_bg_transition = _background_transition_enabled(prev_bg_path, bg_path, duration)
        filter_complex = _segment_filter(width, height, ass_path, characters, speaking, duration, has_bg_transition)
        inputs = [FFMPEG_BIN, "-y", "-loop", "1", "-t", f"{max(0.1, duration):.3f}", "-i", bg_path, "-i", audio_path]
        if has_bg_transition and prev_bg_path:
            inputs.extend(["-loop", "1", "-t", f"{max(0.1, duration):.3f}", "-i", prev_bg_path])
        inputs.extend(_segment_character_inputs(duration, characters, speaking))
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
        prev_bg_path = bg_path

    _write_concat_list(segment_list, segment_paths)
    _run_ffmpeg([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", segment_list, "-c", "copy", video_path])

    if BGM_PATH and os.path.exists(BGM_PATH):
        bgm_volume = max(0.0, float(BGM_VOLUME)) / 100.0
        _run_ffmpeg([
            FFMPEG_BIN, "-y", "-i", video_path, "-stream_loop", "-1", "-i", BGM_PATH,
            "-filter_complex",
            f"[0:a]volume=1.0[a0];[1:a]volume={bgm_volume:.3f}[a1];"
            "[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", output_path,
        ])
    else:
        _run_ffmpeg([FFMPEG_BIN, "-y", "-i", video_path, "-c", "copy", output_path])

    if progress_callback:
        progress_callback(f"✅ YMMなし(test) MP4出力: {output_path}")
    return NativeRenderResult(
        output_path=output_path,
        duration_sec=total_audio,
        audio_count=len(audio_files),
        background_count=len(bg_files),
    )
