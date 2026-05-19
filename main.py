import os
import sys
import wave
import math
import time
import subprocess
import re
import uuid
import json
import shutil
import gc
from core.voicevox import VoicevoxAPI
from core.parser import ScriptParser
from core.ymmp_editor import YmmpEditor
from core.ai_generator import AIGenerator
from core.image_generator import ImageGenerator
from core.opening_quality import (
    apply_opening_rewrite_to_script,
    duration_review,
    duration_status_label,
    final_chatgpt_review,
    llm_opening_review,
    local_opening_review,
    rewrite_opening_with_ollama,
    save_duration_review,
    save_final_review,
    save_opening_review,
    should_auto_rewrite_opening,
)
from config import (
    BGM_LAYER,
    BGM_PATH,
    BGM_VOLUME,
    CHARACTERS,
    MAX_BACKGROUNDS_LONG,
    MAX_BACKGROUNDS_SHORTS,
    OLLAMA_REWRITE_FALLBACK_MODEL,
    OLLAMA_REWRITE_MODEL,
    OPENING_SCORE_HARD_ABORT_THRESHOLD,
    OPENING_SCORE_ABORT_THRESHOLD,
    OPENING_REWRITE_MAX_FALLBACKS,
    LONG_THUMBNAIL_AB_TEST,
    VOICEVOX_PATH,
    VOICE_INTRO_FAST_SECONDS,
    VOICE_INTRO_SPEED_SCALE_LONG,
    VOICE_INTRO_SPEED_SCALE_SHORTS,
    VOICE_SPEED_SCALE_LONG,
    VOICE_SPEED_SCALE_SHORTS,
)


class OutputDirectoryLockedError(Exception):
    """既存の出力フォルダが開かれていて退避できない場合の再試行用エラー。"""


def _find_locking_process(path):
    """Return 'Name (PID)' of the process locking the file, or None."""
    try:
        import psutil
        target = os.path.abspath(path).lower()
        for proc in psutil.process_iter(['pid', 'name', 'open_files']):
            try:
                for f in proc.open_files():
                    if f.path.lower() == target:
                        return f"{proc.info['name']} (PID {proc.info['pid']})"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return None

TRANSITION_SEC = 0.3  # 背景クロスフェード時間（秒）
VOICE_TAIL_SAFETY_SEC = 0.5
INTER_DIALOGUE_GAP_SEC = 0.2

LONG_THUMBNAIL_VARIANTS = [
    {
        "variant": "A",
        "concept": "food_closeup_click",
        "text": "default thumbnail candidate",
        "prompt": (
            "Variant A: food close-up, click-focused composition. "
            "Make the food very large in the center, bright, high contrast, glossy and appetizing. "
            "The viewer should instantly understand this is food trivia."
        ),
    },
    {
        "variant": "B",
        "concept": "old_history_surprise",
        "text": "history/surprise candidate",
        "prompt": (
            "Variant B: old history and surprise composition. "
            "Use an old dining table, vintage shop, old document, or historical atmosphere. "
            "Prioritize unexpected food history and curiosity."
        ),
    },
    {
        "variant": "C",
        "concept": "before_after_gap",
        "text": "comparison/gap candidate",
        "prompt": (
            "Variant C: comparison gap composition. "
            "Split the image left and right to compare past and present. "
            "Show a clear contrast between old treatment and the modern food appearance."
        ),
    },
]


def _meta_dir(theme_dir: str) -> str:
    p = os.path.join(theme_dir, "_meta")
    os.makedirs(p, exist_ok=True)
    return p


def _thumbs_dir(theme_dir: str) -> str:
    p = os.path.join(theme_dir, "thumbnails")
    os.makedirs(p, exist_ok=True)
    return p


def _safe_thumbnail_prefix(theme_dir):
    prefix = os.path.basename(os.path.normpath(theme_dir)) or "video"
    return re.sub(r'[\\/:*?"<>|]', '_', prefix)


def _thumbnail_variant_filename(theme_dir, variant):
    return f"{_safe_thumbnail_prefix(theme_dir)}_thumbnail_{variant}.png"


def _write_long_thumbnail_manifest(theme_dir, topic, variants, video_id=None):
    manifest_path = os.path.join(_meta_dir(theme_dir), "thumbnail_ab_test.json")
    current = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                current = json.load(f)
        except Exception:
            current = {}

    data = {
        "video_title": current.get("video_title") or topic,
        "video_id": video_id if video_id is not None else current.get("video_id"),
        "thumbnail_variants": variants,
        "ab_test_status": current.get("ab_test_status") or "manual_pending",
        "winner": current.get("winner"),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return manifest_path


def _fallback_title_variants(base_title):
    base = (base_title or "").strip() or "食べ物の意外な話"
    fallback = [
        ("A", base, "food_closeup_click"),
        ("B", f"{base}に隠れた意外な歴史", "old_history_surprise"),
        ("C", f"{base}は昔と今で何が違うのか", "before_after_gap"),
    ]
    result = []
    for variant, title, concept in fallback:
        if len(title) > 45:
            title = title[:44] + "…"
        result.append({"variant": variant, "title": title, "concept": concept})
    return result


def _write_long_title_manifest(theme_dir, topic, title_variants, default_variant="A"):
    manifest_path = os.path.join(_meta_dir(theme_dir), "title_ab_test.json")
    data = {
        "video_title": topic,
        "default_variant": default_variant,
        "title_variants": title_variants,
        "ab_test_status": "manual_pending",
        "winner": None,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return manifest_path


def record_uploaded_video_id_for_thumbnail_ab_test(output_dir, video_id):
    """Store uploaded YouTube video id in the long-thumbnail A/B manifest."""
    if not output_dir or not video_id:
        return None
    manifest_path = os.path.join(output_dir, "_meta", "thumbnail_ab_test.json")
    updated_path = None
    try:
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["video_id"] = video_id
            for item in data.get("thumbnail_variants", []):
                variant = item.get("variant")
                old_file = item.get("file")
                if not variant or not old_file:
                    continue
                old_path = os.path.join(output_dir, old_file)
                if not os.path.exists(old_path):
                    old_path = os.path.join(_thumbs_dir(output_dir), old_file)
                new_file = f"{video_id}_thumbnail_{variant}.png"
                new_path = os.path.join(_thumbs_dir(output_dir), new_file)
                if os.path.exists(old_path) and os.path.abspath(old_path) != os.path.abspath(new_path):
                    shutil.copy2(old_path, new_path)
                    item["file"] = new_file
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            updated_path = manifest_path

        title_manifest_path = os.path.join(output_dir, "_meta", "title_ab_test.json")
        if os.path.exists(title_manifest_path):
            with open(title_manifest_path, "r", encoding="utf-8") as f:
                title_data = json.load(f)
            title_data["video_id"] = video_id
            with open(title_manifest_path, "w", encoding="utf-8") as f:
                json.dump(title_data, f, ensure_ascii=False, indent=2)
            updated_path = updated_path or title_manifest_path
        return updated_path
    except Exception:
        return None

_CHANNEL_URL = "https://www.youtube.com/@zunkami"
_VOICEVOX_CREDIT = "\n\n【使用音声合成】VOICEVOX:ずんだもん / VOICEVOX:四国めたん"


def _strip_voicevox_credit(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    cleaned = [l for l in lines if "VOICEVOX:" not in l and "使用音声合成" not in l]
    return "\n".join(cleaned).strip(), len(cleaned) != len(lines)
_CHANNEL_FOOTER = (
    "\n\n"
    "👍 いいね＆チャンネル登録お願いします！\n"
    "💬 感想はコメントで！\n"
    "🔔 通知オンで見逃しなし！\n"
    f"\n▶ チャンネル登録はこちら → {_CHANNEL_URL}\n"
    "\n#ずんだもん #ゆっくり解説 #食べ物雑学 #食べ物の歴史 #VOICEVOX"
)




_PUNCT = set("。！？")

def _split_at_punctuation(text):
    """Shorts用: 句読点(。！？)でセリフを文節に分割する。
    「！？」など連続句読点は前チャンクに結合して単体句読点チャンクを作らない。"""
    chunks = []
    current = ""
    for ch in text:
        current += ch
        if ch in _PUNCT and current.strip():
            chunks.append(current)
            current = ""
    if current.strip():
        chunks.append(current)
    # 句読点のみのチャンクを直前チャンクに結合
    merged = []
    for chunk in chunks:
        if merged and not chunk.strip("".join(_PUNCT) + "　 "):
            merged[-1] += chunk
        else:
            merged.append(chunk)
    return merged if merged else [text]


def _detect_is_shorts(script_content):
    """台本テキストから動画形式を検出する。Shorts/ショート のみ True。Long/ロング は False。"""
    for line in script_content.splitlines():
        line = line.strip().replace("**", "")
        m = re.match(r'^(?:動画形式|Format)[:：]\s*(.+)$', line, re.IGNORECASE)
        if m:
            return m.group(1).strip().lower() in ("shorts", "ショート")
    return False


class GenerationReport:
    def __init__(self):
        self.voices_generated = 0
        self.voices_failed = 0
        self.backgrounds_generated = 0
        self.backgrounds_failed = 0
        self.elapsed_sec = 0.0

    def summary(self):
        m, s = divmod(int(self.elapsed_sec), 60)
        elapsed = f"{m}分{s}秒" if m else f"{s}秒"
        return (
            f"⏱  所要時間: {elapsed}\n"
            f"🎤 音声: 生成={self.voices_generated} / 失敗={self.voices_failed}\n"
            f"🖼  背景: 生成={self.backgrounds_generated} / 失敗={self.backgrounds_failed}"
        )


def _estimate_script_duration(items, is_shorts: bool):
    """Estimate narration duration before VOICEVOX generation."""
    dialogue_items = [it for it in items if it["type"] == "dialogue"]
    if not dialogue_items:
        return None, 0, 0.0
    n = len(dialogue_items)
    total_chars = sum(len(it.get("text", "")) for it in dialogue_items)
    avg_chars = total_chars / n if n else 0.0

    chars_per_sec_at_1x = 5.4
    intro_speed = VOICE_INTRO_SPEED_SCALE_SHORTS if is_shorts else VOICE_INTRO_SPEED_SCALE_LONG
    body_speed = VOICE_SPEED_SCALE_SHORTS if is_shorts else VOICE_SPEED_SCALE_LONG
    additional = TRANSITION_SEC + VOICE_TAIL_SAFETY_SEC + INTER_DIALOGUE_GAP_SEC

    elapsed = 0.0
    for item in dialogue_items:
        chars = len(item.get("text", ""))
        speed = intro_speed if elapsed < VOICE_INTRO_FAST_SECONDS else body_speed
        elapsed += chars / (chars_per_sec_at_1x * speed) + 0.1 * speed + additional
    return elapsed, n, avg_chars




def generate_thumbnail(img_gen, topic, is_shorts, theme_dir, theme_bg_dir, update_status=None,
                       script_content=None, debug_mode=False, long_thumbnail_ab_test=None):
    """Generate thumbnail image via Nano Banana using script content."""
    def _log(msg):
        if update_status: update_status(msg)
        else: print(msg, flush=True)

    thumbs = _thumbs_dir(theme_dir)
    thumb_path = os.path.join(thumbs, "thumbnail.png")

    ratio_tag = "縦9:16のショート動画" if is_shorts else "横16:9のワイドスクリーン"
    safe_zone = (
        "\nセーフゾーン（厳守）: 上下左右30%の範囲にはテキスト・文字・重要な要素を一切配置しないこと。"
    ) if is_shorts else ""
    prompt = (
        f"アスペクト比: {ratio_tag}。{safe_zone}\n"
        f"以下の台本を参考に、YouTubeサムネイル画像を生成してください。\n\n"
        f"{script_content or topic}"
    )

    from config import THUMBNAIL_CHARACTER_PNGS
    char_refs = [p for p in THUMBNAIL_CHARACTER_PNGS.values() if os.path.exists(p)]

    # プロンプトをファイルに保存（再生成・デバッグ用）
    prompt_path = os.path.join(thumbs, "thumbnail_prompt.txt")
    try:
        with open(prompt_path, "w", encoding="utf-8") as pf:
            pf.write(prompt)
    except Exception:
        pass

    # サムネイルは常に nanobanana2 で生成（背景と統一）
    thumb_img_gen = ImageGenerator(
        width=img_gen.width, height=img_gen.height,
        debug=img_gen.debug, image_style="nanobanana2",
    )

    def _generate_one(one_prompt, final_path, label):
        _log(f"サムネイル生成中: {label}")
        if debug_mode:
            _log(f"  [DEBUG] サムネイルプロンプト保存: {prompt_path}")
        generated_name = thumb_img_gen.generate_background(
            one_prompt,
            target_dir=theme_bg_dir,
            raw=True,
            reference_image_paths=char_refs,
        )
        if not generated_name:
            return None
        src_path = os.path.join(theme_bg_dir, generated_name)
        if os.path.exists(final_path):
            os.remove(final_path)
        shutil.copy2(src_path, final_path)
        if os.path.abspath(src_path) != os.path.abspath(final_path):
            os.remove(src_path)
        return final_path

    if is_shorts:
        try:
            saved_path = _generate_one(prompt, thumb_path, "thumbnail")
        except Exception as e:
            _log(f"  サムネイル生成失敗: {e}")
            return None
        if not saved_path:
            _log("  サムネイル生成をスキップしました")
            return None
        _log(f"  サムネイル保存: {saved_path}")
        return saved_path

    manifest_variants = []
    first_variant_path = None
    thumbnail_text = ""
    try:
        thumbnail_text = next(
            (it["text"] for it in ScriptParser.parse_string(script_content or "") if it["type"] == "thumbnail_text"),
            "",
        ).strip()
    except Exception:
        thumbnail_text = ""
    common_rules = (
        "\n\nLong video thumbnail A/B test rules: 16:9 landscape. "
        "Put the food large in the center. Place Zundamon at lower left and Shikoku Metan at lower right. "
        "Characters must be smaller than the food. Put 2-8 Japanese characters at the top center. "
        "Use white text, very thick black outline, drop shadow, bold gothic font, readable on smartphones."
    )
    if thumbnail_text:
        common_rules += f' Use this exact thumbnail text at the top center: "{thumbnail_text}".'
    ab_test = LONG_THUMBNAIL_AB_TEST if long_thumbnail_ab_test is None else long_thumbnail_ab_test
    variants_to_generate = LONG_THUMBNAIL_VARIANTS if ab_test else LONG_THUMBNAIL_VARIANTS[:1]
    try:
        for variant in variants_to_generate:
            variant_id = variant["variant"]
            filename = _thumbnail_variant_filename(theme_dir, variant_id)
            variant_path = os.path.join(thumbs, filename)
            variant_prompt = f"{prompt}{common_rules}\n\n{variant['prompt']}"
            saved_path = _generate_one(variant_prompt, variant_path, f"variant {variant_id}")
            if not saved_path:
                _log(f"  サムネイル案{variant_id}をスキップしました")
                return None
            if first_variant_path is None:
                first_variant_path = saved_path
            manifest_variants.append({
                "variant": variant_id,
                "file": filename,
                "concept": variant["concept"],
                "text": thumbnail_text or variant["text"],
            })
    except Exception as e:
        _log(f"  サムネイル生成失敗: {e}")
        return None

    if not first_variant_path:
        _log("  サムネイル生成をスキップしました")
        return None
    if os.path.exists(thumb_path):
        os.remove(thumb_path)
    shutil.copy2(first_variant_path, thumb_path)
    if ab_test:
        manifest_path = _write_long_thumbnail_manifest(theme_dir, topic, manifest_variants)
        _log(f"  サムネイルA/B管理ファイル保存: {manifest_path}")
    _log(f"  アップロード用サムネイル保存: {thumb_path}")
    return thumb_path


def _read_ymmp_duration(path):
    """Return the total frame count (max Frame+Length) of a ymmp file."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            p = json.load(f)
        items = p.get("Timelines", [{}])[0].get("Items", [])
        if not items:
            return 0
        return max(it.get("Frame", 0) + it.get("Length", 0) for it in items)
    except Exception:
        return 0


def _add_fixed_bgm(editor, total_frames, update_status=print):
    if not BGM_PATH or total_frames <= 0:
        return
    if not os.path.exists(BGM_PATH):
        update_status(f"  BGMなし: {BGM_PATH} が見つかりません")
        return

    editor.add_audio_item(
        BGM_PATH,
        start_frame=0,
        duration=total_frames,
        layer=BGM_LAYER,
        volume=BGM_VOLUME,
    )
    update_status(f"  BGM追加: {os.path.basename(BGM_PATH)} 音量{BGM_VOLUME:g}%")


def merge_telops_into_backgrounds(items):
    """Fold テロップ items into the preceding 背景 prompt so Nano Banana renders the text."""
    result = []
    last_bg_idx = None
    for item in items:
        if item["type"] == "telop":
            telop = item.get("text", "").strip()
            if telop and last_bg_idx is not None:
                bg = result[last_bg_idx]
                bg = dict(bg)  # copy so original parsed item is not mutated
                bg["text"] = (
                    bg["text"].rstrip("、。, ") +
                    f"。【テロップ演出】画面上部中央に超大型の日本語テロップ「{telop}」を描画。"
                    f"フォント：極太インパクト体・文字は画面幅いっぱいに大きく。"
                    f"エフェクト：金属光沢メタリック加工・白〜銀のグラデーション文字・"
                    f"太い黒縁取り・鋭いドロップシャドウ。"
                    f"背景演出：テロップ背後に漫画風の放射状集中線・スピードライン・"
                    f"爆発的なエネルギー放射エフェクト。"
                    f"食品パッケージ広告・雑誌見出し風の圧倒的なデザイン。"
                    f"テロップは画面上部35%以内に配置し、非常にくっきり読みやすくすること。"
                )
                result[last_bg_idx] = bg
            # telop item is consumed — not added to result
        else:
            if item["type"] == "background":
                last_bg_idx = len(result)
            result.append(item)
    return result


def normalize_background_order(items):
    """Accept scripts that put a background line immediately after its dialogue."""
    normalized = []
    i = 0
    while i < len(items):
        current = items[i]
        next_item = items[i + 1] if i + 1 < len(items) else None
        if (
            current.get("type") == "dialogue"
            and next_item
            and next_item.get("type") == "background"
        ):
            normalized.append(next_item)
            normalized.append(current)
            i += 2
            continue
        normalized.append(current)
        i += 1
    return normalized


def regenerate_thumbnail_only(output_dir, image_style="通常", debug=False, progress_callback=None):
    """既存の出力フォルダのサムネイルのみ再生成する。"""
    def update_status(msg, tag="info"):
        if progress_callback:
            progress_callback(msg, tag)
        else:
            print(msg, flush=True)

    script_path = os.path.join(output_dir, "script.txt")
    if not os.path.exists(script_path):
        raise Exception(f"script.txt が見つかりません: {output_dir}")

    with open(script_path, "r", encoding="utf-8") as f:
        script_content = f.read()

    is_shorts = _detect_is_shorts(script_content)
    width = 1080 if is_shorts else 1920
    height = 1920 if is_shorts else 1080

    topic = os.path.basename(output_dir)
    theme_bg_dir = os.path.join(output_dir, "backgrounds")
    os.makedirs(theme_bg_dir, exist_ok=True)

    img_gen = ImageGenerator(width=width, height=height, debug=debug, image_style=image_style)
    thumb_path = generate_thumbnail(img_gen, topic, is_shorts, output_dir, theme_bg_dir,
                                    update_status, script_content=script_content, debug_mode=debug,
                                    long_thumbnail_ab_test=long_thumbnail_ab_test)
    if not thumb_path:
        raise Exception("サムネイル生成に失敗しました")
    return thumb_path


def run_pipeline(topic, reference_script=None, debug_mode=False,
                 progress_callback=None, pregenerated_script=None,
                 image_style="通常", reuse_backgrounds=False, use_batch_api=False,
                 cancel_event=None, existing_titles=None, long_thumbnail_ab_test=None):
    report = GenerationReport()
    pipeline_start = time.time()

    def update_status(msg, tag="info"):
        if progress_callback:
            progress_callback(msg, tag)
        else:
            print(msg, flush=True)

    def is_cancelled():
        return bool(cancel_event and cancel_event.is_set())

    def cancel_result():
        report.elapsed_sec = time.time() - pipeline_start
        msg = "⏹ 作業を中止しました。"
        update_status(msg)
        return msg, report

    # Step 1: スクリプト取得（形式判定のために先に行う）
    ai = AIGenerator(debug=debug_mode)
    if pregenerated_script:
        script_content = pregenerated_script
        update_status("台本を読み込み中...")
    else:
        update_status(f"AI台本を生成中: {topic}...")
        script_content = ai.generate_script(topic, reference_script=reference_script, existing_titles=existing_titles)
        if script_content.startswith("Error"):
            report.elapsed_sec = time.time() - pipeline_start
            return script_content, report
    if is_cancelled():
        return cancel_result()

    # ★ 最初のバリデーション（sanitize前）
    _early_items = ScriptParser.parse_string(script_content)
    _is_valid, _messages = ScriptParser.validate(_early_items)
    _early_title = next((it["text"] for it in _early_items if it["type"] == "video_title"), None)
    if _early_title:
        update_status(f"  📋 取得タイトル: {_early_title}")
    if not _is_valid:
        report.elapsed_sec = time.time() - pipeline_start
        msg = "❌ 台本形式エラー:\n" + "\n".join(_messages)
        update_status(msg)
        return msg, report
    if is_cancelled():
        return cancel_result()

    from core.ng_words import apply_ng_word_replacements
    script_content = apply_ng_word_replacements(script_content)
    script_content = re.sub(r'(?m)^サムネイル[:：][^\n]*\n?', '', script_content)
    if is_cancelled():
        return cancel_result()

    # Step 2: 動画形式を検出
    is_shorts = _detect_is_shorts(script_content)
    max_backgrounds = MAX_BACKGROUNDS_SHORTS if is_shorts else MAX_BACKGROUNDS_LONG
    intro_voice_speed = VOICE_INTRO_SPEED_SCALE_SHORTS if is_shorts else VOICE_INTRO_SPEED_SCALE_LONG
    body_voice_speed = VOICE_SPEED_SCALE_SHORTS if is_shorts else VOICE_SPEED_SCALE_LONG
    update_status(f"📐 動画形式: {'Shorts' if is_shorts else 'ロング'}")

    # Step 3: パス設定（台本のvideo_titleを優先してフォルダ名に使う）
    folder_base = _early_title if _early_title else topic
    safe_topic = re.sub(r'[\\/:*?"<>|]', '_', folder_base)
    if is_shorts and not safe_topic.startswith("[Shorts]"):
        safe_topic = f"[Shorts]{safe_topic}"

    theme_dir = os.path.join("output", safe_topic)
    project_file_path = os.path.join(theme_dir, f"{safe_topic}.ymmp")

    width = 1080 if is_shorts else 1920
    height = 1920 if is_shorts else 1080

    # Step 4: 既存フォルダは削除せず、先にバックアップへ退避する。
    # 開きっぱなしで退避できない場合は、GUI側で警告して同じ生成を再試行する。
    _existing_theme_backup = None
    _saved_bg_dir = None
    _saved_thumb_path = None
    if os.path.exists(theme_dir):
        gc.collect()  # release any PIL file handles from previous run
        backup_base = os.path.join("output", "000_backups")
        backup_name = f"{safe_topic}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        backup_dir = os.path.join(backup_base, backup_name)
        try:
            os.makedirs(backup_base, exist_ok=True)
            os.replace(theme_dir, backup_dir)
            _existing_theme_backup = backup_dir
            update_status(f"📦 既存フォルダをバックアップへ退避しました: {backup_dir}")
        except PermissionError as e:
            locker = _find_locking_process(theme_dir)
            locker_info = f"\nロック中のプロセス: {locker}" if locker else ""
            raise OutputDirectoryLockedError(
                f"既存フォルダをバックアップへ退避できませんでした。\n{theme_dir}{locker_info}\n\n"
                "YMM4やエクスプローラーでプロジェクトファイル・出力フォルダを閉じてからOKを押してください。"
            ) from e
        except Exception as e:
            raise OutputDirectoryLockedError(
                f"既存フォルダをバックアップへ退避できませんでした。\n"
                f"YMM4やエクスプローラーでフォルダを開いていないか確認してください。\n({theme_dir})\n\n{e}"
            ) from e

        if reuse_backgrounds:
            _old_bg_dir = os.path.join(_existing_theme_backup, "backgrounds")
            if os.path.exists(_old_bg_dir):
                reusable_bgs = [
                    f for f in os.listdir(_old_bg_dir)
                    if f.lower().endswith(".png") and f.lower().startswith("bg_")
                ]
                if reusable_bgs:
                    _saved_bg_dir = _old_bg_dir
        # サムネイルは再生成の有無に関係なく常に退避（再生成失敗時のフォールバック用）
        _thumb_candidate = os.path.join(_existing_theme_backup, "thumbnails", "thumbnail.png")
        if os.path.exists(_thumb_candidate):
            _saved_thumb_path = _thumb_candidate

    theme_audio_dir = os.path.join(theme_dir, "audio")
    theme_bg_dir = os.path.join(theme_dir, "backgrounds")
    os.makedirs(theme_audio_dir, exist_ok=True)
    os.makedirs(theme_bg_dir, exist_ok=True)

    # 背景再利用: バックアップへ退避したファイルを復元（新規作成時は_saved_bg_dir=Noneなので通常生成へ）
    _has_saved_bgs = False
    if _saved_bg_dir:
        restored_bg_count = 0
        for f in os.listdir(_saved_bg_dir):
            if f.lower().endswith(".png") and f.lower().startswith("bg_"):
                shutil.copy2(os.path.join(_saved_bg_dir, f), theme_bg_dir)
                restored_bg_count += 1
        _has_saved_bgs = restored_bg_count > 0
        if _has_saved_bgs:
            update_status(f"🖼  既存の背景を再利用します: {restored_bg_count}枚")
    if _saved_thumb_path and os.path.exists(_saved_thumb_path):
        shutil.copy2(_saved_thumb_path, os.path.join(_thumbs_dir(theme_dir), "thumbnail.png"))

    script_txt_path = os.path.join(theme_dir, "script.txt")
    with open(script_txt_path, "w", encoding="utf-8") as f:
        f.write(script_content)

    items = ScriptParser.parse(script_txt_path)

    # Extract and save metadata (thumbnail / title / description / tags)
    meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
    items = [it for it in items if it["type"] not in ScriptParser.META_TYPES]
    items = normalize_background_order(items)

    ai_thumbnail_prompt = meta.get("thumbnail")

    if "description" in meta:
        from core.ng_words import apply_ng_word_replacements
        _desc, _stripped = _strip_voicevox_credit(meta["description"].rstrip())
        if _stripped:
            update_status("  説明文の手書きVOICEVOXクレジットを自動除去しました")
        _desc = re.sub(r'#\S+', '', _desc).strip()
        meta["description"] = apply_ng_word_replacements(_desc) + _VOICEVOX_CREDIT + _CHANNEL_FOOTER

    opening_title = meta.get("video_title", topic)
    opening_thumb_text = meta.get("thumbnail_text", "")
    opening_review = local_opening_review(items, opening_title, opening_thumb_text, is_shorts)
    llm_review = None
    rewrite_text = None
    target_duration = "38-50秒" if is_shorts else "5-8分"
    if opening_review.get("llm_review_required"):
        try:
            update_status("  🤖 Ollamaで冒頭レビュー中...")
            llm_review = llm_opening_review(
                opening_review,
                opening_title,
                opening_thumb_text,
                "Shorts" if is_shorts else "Long",
                target_duration,
            )
            if llm_review:
                update_status(
                    f"  🤖 Ollama冒頭レビュー完了: {llm_review.get('score')}点 / {llm_review.get('status')}"
                )
                if llm_review.get("fallback_to_local"):
                    opening_review_path = save_opening_review(theme_dir, opening_review, llm_review, None)
                    msg = (
                        "❌ Ollama冒頭レビューに失敗したため処理を中止しました。\n"
                        "Ollamaを起動してから再実行してください。\n"
                        f"保存先: {opening_review_path}"
                    )
                    update_status(msg, "error")
                    report.elapsed_sec = time.time() - pipeline_start
                    return msg, report
            else:
                update_status("  ⚠ Ollama冒頭レビューはスキップされました")
        except Exception as e:
            opening_review_path = save_opening_review(
                theme_dir,
                opening_review,
                {
                    "mode": "llm",
                    "provider": "ollama",
                    "score": opening_review.get("score", 0),
                    "status": "llm_review_error",
                    "issues": [f"Ollamaレビュー失敗: {e}"],
                    "warnings": [f"Ollamaレビュー失敗: {e}"],
                    "fallback_to_local": True,
                },
                None,
            )
            msg = (
                f"❌ Ollama冒頭レビューに失敗したため処理を中止しました: {e}\n"
                "Ollamaを起動してから再実行してください。\n"
                f"保存先: {opening_review_path}"
            )
            update_status(msg, "error")
            report.elapsed_sec = time.time() - pipeline_start
            return msg, report
    final_opening = llm_review or opening_review

    if should_auto_rewrite_opening(final_opening):
        rewrite_source = dict(opening_review)
        rewrite_source["score"] = final_opening.get("score")
        rewrite_source["issues"] = final_opening.get("issues", opening_review.get("issues", []))
        rewrite_attempts = []
        rewrite_accepted = False
        rewrite_models = [OLLAMA_REWRITE_MODEL]
        if OPENING_REWRITE_MAX_FALLBACKS > 0 and OLLAMA_REWRITE_FALLBACK_MODEL not in rewrite_models:
            rewrite_models.append(OLLAMA_REWRITE_FALLBACK_MODEL)
        rewrite_models = rewrite_models[: 1 + max(0, OPENING_REWRITE_MAX_FALLBACKS)]

        for attempt_index, rewrite_model in enumerate(rewrite_models):
            try:
                if attempt_index == 0:
                    update_status(f"  ✍ Ollama({rewrite_model})で冒頭リライト中...")
                else:
                    update_status(f"  ✍ Ollama({rewrite_model})で冒頭を再リライト中...")
                candidate_rewrite_text = rewrite_opening_with_ollama(
                    rewrite_source,
                    opening_title,
                    opening_thumb_text,
                    "Shorts" if is_shorts else "Long",
                    model=rewrite_model,
                )
                if not candidate_rewrite_text:
                    update_status(f"  ⚠ Ollama({rewrite_model})冒頭リライトは空でした", "warning")
                    rewrite_attempts.append({"model": rewrite_model, "accepted": False, "reason": "empty"})
                    continue

                candidate_script_content = apply_opening_rewrite_to_script(
                    script_content,
                    candidate_rewrite_text,
                    is_shorts,
                )
                candidate_items = ScriptParser.parse_string(candidate_script_content)
                candidate_meta = {
                    it["type"]: it["text"]
                    for it in candidate_items
                    if it["type"] in ScriptParser.META_TYPES
                }
                candidate_items = [
                    it for it in candidate_items if it["type"] not in ScriptParser.META_TYPES
                ]
                candidate_items = normalize_background_order(candidate_items)
                candidate_title = candidate_meta.get("video_title", topic)
                candidate_thumb_text = candidate_meta.get("thumbnail_text", "")
                candidate_review = local_opening_review(
                    candidate_items,
                    candidate_title,
                    candidate_thumb_text,
                    is_shorts,
                )
                candidate_score = int(candidate_review.get("score") or 0)
                candidate_critical_errors = candidate_review.get("critical_errors") or []
                rewrite_attempts.append(
                    {
                        "model": rewrite_model,
                        "score": candidate_score,
                        "status": candidate_review.get("status"),
                        "accepted": candidate_score >= OPENING_SCORE_HARD_ABORT_THRESHOLD and not candidate_critical_errors,
                        "critical_errors": candidate_critical_errors,
                    }
                )
                if llm_review:
                    llm_review["before_rewrite"] = True
                    llm_review["rewrite_candidate_score"] = candidate_score
                    llm_review["rewrite_candidate_status"] = candidate_review.get("status")

                if candidate_score >= OPENING_SCORE_HARD_ABORT_THRESHOLD and not candidate_critical_errors:
                    rewrite_text = candidate_rewrite_text
                    script_content = candidate_script_content
                    with open(script_txt_path, "w", encoding="utf-8") as f:
                        f.write(script_content)
                    items = candidate_items
                    meta = candidate_meta
                    ai_thumbnail_prompt = meta.get("thumbnail")
                    if "description" in meta:
                        from core.ng_words import apply_ng_word_replacements
                        _desc, _stripped = _strip_voicevox_credit(meta["description"].rstrip())
                        if _stripped:
                            update_status("  説明文の手書きVOICEVOXクレジットを自動除去しました")
                        _desc = re.sub(r'#\S+', '', _desc).strip()
                        meta["description"] = apply_ng_word_replacements(_desc) + _VOICEVOX_CREDIT + _CHANNEL_FOOTER
                    opening_title = meta.get("video_title", topic)
                    opening_thumb_text = meta.get("thumbnail_text", "")
                    opening_review = candidate_review
                    final_opening = opening_review
                    if llm_review:
                        llm_review["rewrite_accepted"] = True
                        llm_review["rewrite_accepted_model"] = rewrite_model
                        llm_review["final_status_after_rewrite"] = opening_review.get("status")
                    rewrite_accepted = True
                    update_status(
                        f"  ✍ Ollama({rewrite_model})リライト採用: 再採点 {candidate_score}点 / 重大エラーなし"
                    )
                    break

                update_status(
                    f"  ⚠ Ollama({rewrite_model})リライト不採用: 再採点 {candidate_score}点 / 停止基準{OPENING_SCORE_HARD_ABORT_THRESHOLD}点未満またはmust_fixあり",
                    "warning",
                )
                for issue in (candidate_review.get("issues") or [])[:3]:
                    update_status(f"    - リライト候補: {issue}", "warning")
                for issue in candidate_critical_errors[:3]:
                    update_status(f"    - リライト候補must_fix: {issue}", "warning")
            except Exception as e:
                update_status(f"  ⚠ Ollama({rewrite_model})冒頭リライト失敗: {e}", "warning")
                rewrite_attempts.append({"model": rewrite_model, "accepted": False, "error": str(e)})

        if not rewrite_accepted and rewrite_attempts and llm_review:
            llm_review["rewrite_accepted"] = False
            llm_review["rewrite_reject_reason"] = f"全候補が停止基準に該当: {OPENING_SCORE_HARD_ABORT_THRESHOLD}点未満またはmust_fixあり"
        if rewrite_attempts and llm_review:
            llm_review["rewrite_attempts"] = rewrite_attempts

    opening_review_path = save_opening_review(theme_dir, opening_review, llm_review, rewrite_text)
    final_score = int(final_opening.get("score") or 0)
    opening_critical_errors = final_opening.get("critical_errors") or []
    score_tag = "score_ok" if final_score >= OPENING_SCORE_ABORT_THRESHOLD and not opening_critical_errors else "score_warn" if final_score >= OPENING_SCORE_HARD_ABORT_THRESHOLD and not opening_critical_errors else "score"
    opening_model_parts = []
    if llm_review and llm_review.get("model"):
        opening_model_parts.append(f"review:{llm_review.get('model')}")
    if llm_review and llm_review.get("rewrite_accepted_model"):
        opening_model_parts.append(f"rewrite:{llm_review.get('rewrite_accepted_model')}")
    if not opening_model_parts:
        opening_model_parts.append("review:local-rule")
    opening_model_text = f" / model {', '.join(opening_model_parts)}" if opening_model_parts else ""
    update_status(
        f"■■■ 冒頭スコア {final_score}点 / {final_opening.get('status')}{opening_model_text} ■■■\n"
        f"  保存先: {opening_review_path}",
        score_tag,
    )
    for issue in (final_opening.get("issues") or [])[:3]:
        update_status(f"    - {issue}")
    for issue in opening_critical_errors[:3]:
        update_status(f"    must_fix: {issue}", "warning")

    if final_score < OPENING_SCORE_HARD_ABORT_THRESHOLD or opening_critical_errors:
        msg = (
            f"❌ 冒頭チェックの重大エラーで処理を中止しました（{final_score}点 / 停止基準: {OPENING_SCORE_HARD_ABORT_THRESHOLD}点未満またはmust_fixあり）\n"
            "台本の冒頭を修正してから再実行してください。"
        )
        update_status(msg, "error")
        report.elapsed_sec = time.time() - pipeline_start
        return msg, report

    estimated_sec, estimated_lines, estimated_avg_chars = _estimate_script_duration(items, is_shorts)
    estimated_sec = float(estimated_sec or 0.0)
    estimated_duration_result = duration_review(estimated_sec, is_shorts)
    estimated_duration_result["estimated"] = True
    if is_shorts and (estimated_sec < 35 or estimated_sec > 55):
        estimated_duration_path = save_duration_review(theme_dir, estimated_duration_result)
        msg = (
            f"❌ 推定尺が許容範囲外のため処理を中止しました"
            f"（{estimated_sec:.1f}秒 / 許容: 35〜55秒）\n"
            f"保存先: {estimated_duration_path}"
        )
        update_status(msg, "error")
        report.elapsed_sec = time.time() - pipeline_start
        return msg, report
    update_status(
        f"🧑‍⚖️ ChatGPTで生成前レビュー中... 推定尺 {estimated_sec:.1f}秒"
        f"（{estimated_lines}行 / 平均{estimated_avg_chars:.1f}文字）"
    )
    try:
        final_review = final_chatgpt_review(
            title=meta.get("video_title", topic),
            thumbnail_text=meta.get("thumbnail_text", ""),
            fixed_comment=meta.get("fixed_comment", ""),
            script_content=script_content,
            items=items,
            is_shorts=is_shorts,
            estimated_duration=estimated_sec,
            local_review=opening_review,
            ollama_review=llm_review,
            duration_result=estimated_duration_result,
        )
        final_review_path = save_final_review(theme_dir, final_review)
        if final_review and final_review.get("skipped"):
            msg = f"❌ ChatGPT生成前レビュー skipped: {final_review.get('reason')} ({final_review_path})"
            update_status(msg, "error")
            report.elapsed_sec = time.time() - pipeline_start
            return msg, report
        elif final_review:
            pre_score = int(final_review.get("final_score") or 0)
            pre_score_tag = "score_ok" if pre_score >= OPENING_SCORE_ABORT_THRESHOLD else "score_warn" if pre_score >= OPENING_SCORE_HARD_ABORT_THRESHOLD else "score"
            final_model = final_review.get("model")
            final_model_text = f" / model {final_model}" if final_model else ""
            update_status(
                f"■■■ ChatGPT生成前スコア {pre_score}点 "
                f"/ publish_ok={final_review.get('publish_ok')} / risk={final_review.get('risk')}{final_model_text} ■■■\n"
                f"  保存先: {final_review_path}",
                pre_score_tag,
            )
            for issue in (final_review.get("must_fix") or [])[:3]:
                update_status(f"    must_fix: {issue}", "warning")

            must_fix = final_review.get("must_fix") or []
            if final_review.get("publish_ok") is False and not must_fix and pre_score >= OPENING_SCORE_HARD_ABORT_THRESHOLD:
                update_status("  ⚠ publish_ok=Falseですが、must_fixなしのため警告通過します", "warning")
            if pre_score < OPENING_SCORE_HARD_ABORT_THRESHOLD or must_fix:
                msg = (
                    f"❌ ChatGPT生成前レビューで停止しました"
                    f"（{pre_score}点 / publish_ok={final_review.get('publish_ok')} / 停止基準: {OPENING_SCORE_HARD_ABORT_THRESHOLD}点未満またはmust_fixあり）\n"
                    "台本を修正してから再実行してください。"
                )
                update_status(msg, "error")
                report.elapsed_sec = time.time() - pipeline_start
                return msg, report
        else:
            msg = f"❌ ChatGPT生成前レビュー結果が空です ({final_review_path})"
            update_status(msg, "error")
            report.elapsed_sec = time.time() - pipeline_start
            return msg, report
    except Exception as e:
        final_review_path = save_final_review(theme_dir, {"error": str(e), "stage": "pre_generation"})
        msg = f"❌ ChatGPT生成前レビュー失敗: {e} ({final_review_path})"
        update_status(msg, "error")
        report.elapsed_sec = time.time() - pipeline_start
        return msg, report

    if not is_shorts:
        base_title = meta.get("video_title", topic)
        thumbnail_text = meta.get("thumbnail_text", "")
        update_status("📝 タイトルA/B/C案を生成中...")
        title_variants = ai.generate_title_variants(script_content, base_title, thumbnail_text)
        variants_by_id = {item.get("variant"): item for item in title_variants}
        fallback_by_id = {item["variant"]: item for item in _fallback_title_variants(base_title)}
        merged_title_variants = [
            variants_by_id.get(variant) or fallback_by_id[variant]
            for variant in ("A", "B", "C")
        ]
        title_manifest_path = _write_long_title_manifest(theme_dir, base_title, merged_title_variants)
        update_status(f"  ✅ タイトルA/B/C案保存: {title_manifest_path}")

    if meta:
        meta_path = os.path.join(_meta_dir(theme_dir), "metadata.txt")
        lines = []
        if "video_title" in meta:
            lines += ["【動画タイトル】", meta["video_title"], ""]
        if "thumbnail_text" in meta:
            lines += ["【サムネ文字】", meta["thumbnail_text"], ""]
        if "description" in meta:
            lines += ["【説明文】", meta["description"], ""]
        if "tags" in meta:
            lines += ["【タグ】", meta["tags"], ""]
        if "thumbnail" in meta:
            lines += ["【サムネイルプロンプト】", meta["thumbnail"], ""]
        # 台本に固定コメントがなければAIで生成
        pinned_comment = meta.get("fixed_comment", "")
        if not pinned_comment:
            update_status("💬 固定コメントを生成中...")
            pinned_comment = ai.generate_pinned_comment(script_content)
        if pinned_comment:
            lines += ["【固定コメント】", pinned_comment, ""]
        with open(meta_path, "w", encoding="utf-8") as mf:
            mf.write("\n".join(lines))
        if "video_title" in meta:
            update_status(f"📝 動画タイトル: {meta['video_title']}")
    if is_cancelled():
        return cancel_result()

    telop_count = sum(1 for it in items if it["type"] == "telop")
    items = merge_telops_into_backgrounds(items)

    dialogue_items = [it for it in items if it["type"] == "dialogue"]
    bg_items = [it for it in items if it["type"] == "background"]

    # 背景再利用: 台本の背景数と保存済み枚数が異なる場合は全部再生成
    if _has_saved_bgs:
        _saved_bg_files = sorted(
            f for f in os.listdir(theme_bg_dir)
            if f.lower().endswith(".png") and f.lower().startswith("bg_")
        )
        _expected_bg_count = min(len(bg_items), max_backgrounds)
        if len(_saved_bg_files) != _expected_bg_count:
            update_status(
                f"⚠ 背景枚数が台本と一致しないため再生成します"
                f"（保存: {len(_saved_bg_files)}枚 / 台本: {_expected_bg_count}枚）",
                "warning",
            )
            for _f in _saved_bg_files:
                try:
                    os.remove(os.path.join(theme_bg_dir, _f))
                except Exception:
                    pass
            _has_saved_bgs = False

    update_status(
        f"📄 台本解析完了: セリフ {len(dialogue_items)}件 / 背景 {len(bg_items)}箇所"
        + (f" / テロップ {telop_count}件(背景に統合)" if telop_count else "")
        + (f" / サムネイル指示あり" if ai_thumbnail_prompt else "")
    )
    for warn in _messages:
        update_status(f"  ⚠ {warn}")

    vv = VoicevoxAPI()
    if not vv.check_connection() and os.path.exists(VOICEVOX_PATH):
        subprocess.Popen([VOICEVOX_PATH], creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if is_cancelled():
                return cancel_result()
            if vv.check_connection(): break
            time.sleep(2)

    from config import VIDEO_FPS
    editor = YmmpEditor(width=width, height=height, fps=VIDEO_FPS, debug=debug_mode)

    from config import ASSETS_DIR
    TEMPLATES_DIR = os.path.join(ASSETS_DIR, "templates")
    op_template = os.path.join(TEMPLATES_DIR, "opening_shorts.ymmp" if is_shorts else "opening.ymmp")
    current_frame = 3  # frame 0-2 reserved for YMM4 init
    if os.path.exists(op_template):
        editor.merge_project(op_template, offset_frames=0)
        current_frame = _read_ymmp_duration(op_template)
        update_status(f"📂 OPテンプレート読み込み完了 ({current_frame}フレーム)")
    intro_fast_until_frame = current_frame + round(VOICE_INTRO_FAST_SECONDS * editor.fps)

    img_gen = ImageGenerator(width=width, height=height, debug=debug_mode, image_style=image_style)

    thumbnail_title = meta.get("video_title", topic)
    if _has_saved_bgs:
        # 既存サムネイルをそのまま使用
        thumb_path = os.path.join(theme_dir, "thumbnails", "thumbnail.png") if os.path.exists(os.path.join(theme_dir, "thumbnails", "thumbnail.png")) else None
        if thumb_path:
            update_status("  📌 既存サムネイルを再利用")
    else:
        if is_cancelled():
            return cancel_result()
        thumb_path = generate_thumbnail(img_gen, thumbnail_title, is_shorts, theme_dir, theme_bg_dir, update_status,
                                        script_content=script_content, debug_mode=debug_mode)
        if is_cancelled():
            return cancel_result()

    if thumb_path is None:
        raise Exception("サムネイル画像を生成できませんでした。\nNano Bananaの接続・残高を確認してください。")

    if is_shorts:
        editor.add_image_item(thumb_path, 0, current_frame, layer=0)
        update_status("  📌 サムネイルをショート先頭に挿入")
    # ロングの場合は theme_dir に保存済み（YMM4 挿入なし）

    update_status(f"🎬 アセット生成 & タイムライン構築を開始します...")

    current_bg = None
    bg_start_frame = current_frame
    voice_num = 0
    audio_num = 0
    bg_num = 0
    total_voices = len(dialogue_items)
    total_bgs = len(bg_items)
    dialogue_tachie_info = []  # (char_name, emotion, start_frame, end_frame)
    transition_frames = round(TRANSITION_SEC * editor.fps)
    first_bg_placed = False
    style_reference_path = None  # 1枚目の背景パス（2枚目以降のスタイル参照用）

    # Batch API: メインループ前に全背景を一括生成
    batch_bg_results = {}  # {bg_num(1-indexed): filename}
    if use_batch_api and not _has_saved_bgs:
        _temp_num = 0
        _batch_items = []  # (bg_num, bg_name)
        for item in items:
            if item["type"] == "background":
                _temp_num += 1
                if _temp_num <= max_backgrounds:
                    bg_name = item.get("text", item.get("file", "")).strip() or "default_background"
                    _batch_items.append((_temp_num, bg_name))

        if _batch_items:
            if is_cancelled():
                return cancel_result()
            update_status(f"🖼  Batch API: {len(_batch_items)}枚を一括送信中 (完了まで数分かかります)...")
            batch_requests = [
                {
                    "description": (
                        f"以下の台本を参考に、「{name}」のシーンの背景画像を生成してください。\n\n"
                        f"【台本】\n{script_content}"
                    ),
                    "raw": False,
                }
                for _, name in _batch_items
            ]
            batch_fnames = [f"bg_{n:03d}_001.png" for n, _ in _batch_items]
            try:
                batch_results = img_gen.generate_backgrounds_batch(batch_requests, target_dir=theme_bg_dir, fnames=batch_fnames)
                if is_cancelled():
                    return cancel_result()
                for (bg_n, _), filename in zip(_batch_items, batch_results):
                    if filename:
                        batch_bg_results[bg_n] = filename
                        report.backgrounds_generated += 1
                    else:
                        report.backgrounds_failed += 1
                ok_count = sum(1 for r in batch_results if r)
                update_status(f"  ✅ Batch API 完了: {ok_count}/{len(batch_results)}枚生成")
            except Exception as e:
                raise Exception(f"Batch API エラー: {e}")

    for i, item in enumerate(items):
        if is_cancelled():
            return cancel_result()

        if item["type"] == "background":
            if current_bg and current_frame > bg_start_frame:
                bg_path = os.path.join(theme_bg_dir, current_bg)
                if os.path.exists(bg_path):
                    editor.add_image_item(bg_path, bg_start_frame, current_frame - bg_start_frame, layer=0)
                    if first_bg_placed:
                        editor.add_transition_item(current_frame, transition_frames)
                    first_bg_placed = True

            bg_num += 1
            if bg_num > max_backgrounds:
                update_status(f"🖼  背景 [{bg_num}/{total_bgs}] 上限({max_backgrounds})超過 — 前の背景を継続使用")
                bg_start_frame = current_frame
                continue

            bg_name = item.get("text", item.get("file", "")).strip() or "default_background"

            if _has_saved_bgs:
                # 既存背景を順番に割り当て
                existing_bgs = sorted(
                    f for f in os.listdir(theme_bg_dir)
                    if f.lower().endswith(".png") and f.lower().startswith("bg_")
                )
                bg_idx = bg_num - 1
                if bg_idx < len(existing_bgs):
                    current_bg = existing_bgs[bg_idx]
                    update_status(f"🖼  背景 [{bg_num}/{total_bgs}] 再利用: {current_bg}")
                    report.backgrounds_generated += 1
                else:
                    update_status(f"🖼  背景 [{bg_num}/{total_bgs}] 既存ファイル不足 — スキップ")
                    report.backgrounds_failed += 1
                bg_start_frame = current_frame
                continue

            if use_batch_api:
                # バッチ結果から割り当て
                if bg_num in batch_bg_results:
                    current_bg = batch_bg_results[bg_num]
                    update_status(f"🖼  背景 [{bg_num}/{total_bgs}] バッチ結果使用: {current_bg}")
                else:
                    update_status(f"  ⚠ 背景 [{bg_num}/{total_bgs}] バッチ結果なし — スキップ")
                    current_bg = None
                bg_start_frame = current_frame
                continue

            update_status(f"🖼  背景 [{bg_num}/{total_bgs}] 生成中: {bg_name[:30]}...")
            try:
                if is_cancelled():
                    return cancel_result()
                bg_description = (
                    f"以下の台本を参考に、「{bg_name}」のシーンの背景画像を生成してください。\n\n"
                    f"【台本】\n{script_content}"
                )
                # プロンプトをファイルに保存（デバッグ・再生成参照用）
                prompt_file = os.path.join(theme_bg_dir, f"prompt_bg_{bg_num:04d}.txt")
                try:
                    with open(prompt_file, "w", encoding="utf-8") as _pf:
                        _pf.write(bg_description)
                except Exception:
                    pass
                if debug_mode:
                    update_status(f"  [DEBUG] 背景プロンプト保存: {prompt_file}")
                generated_file = img_gen.generate_background(
                    bg_description, target_dir=theme_bg_dir,
                    reference_image_path=style_reference_path,
                    fname=f"bg_{bg_num:03d}_001.png",
                )
                if is_cancelled():
                    return cancel_result()
            except Exception as e:
                update_status(f"  ❌ 背景生成失敗: {e}")
                generated_file = None
            if generated_file:
                current_bg = generated_file
                report.backgrounds_generated += 1
                if style_reference_path is None:
                    style_reference_path = os.path.join(theme_bg_dir, generated_file)
                update_status(f"  ✅ 背景生成完了")
            else:
                report.backgrounds_failed += 1
                current_bg = None
                update_status(f"  ⚠ 背景生成スキップ")
            bg_start_frame = current_frame
            continue

        if item["type"] == "dialogue":
            char_key = item["character"]
            text = item["text"]
            emotion = item.get("emotion", "ノーマル")
            voice_num += 1

            speaker_id = 3
            for k, v in CHARACTERS.items():
                if v["name"] == char_key:
                    speaker_id = v.get("styles", {}).get(emotion, v["speaker_id"])
                    break

            chunks = _split_at_punctuation(text)

            for chunk_text in chunks:
                if is_cancelled():
                    return cancel_result()
                audio_num += 1
                _safe_text = re.sub(r'[\\/:*?"<>|]', '', chunk_text)[:20]
                audio_filename = f"{bg_num:03d}_{audio_num:03d}_{_safe_text}.wav"
                audio_path = os.path.join(theme_audio_dir, audio_filename)
                speed_scale = intro_voice_speed if current_frame < intro_fast_until_frame else body_voice_speed

                preview = chunk_text[:20] + ("…" if len(chunk_text) > 20 else "")
                update_status(f"🎤 音声 [{voice_num}/{total_voices}] {char_key}({emotion}) x{speed_scale:g}「{preview}」")
                try:
                    _, kana = vv.generate_audio(chunk_text, speaker_id, audio_path, speed_scale=speed_scale)
                    report.voices_generated += 1
                except Exception as e:
                    update_status(f"  ❌ 音声合成失敗: {e}")
                    report.voices_failed += 1
                    continue
                if is_cancelled():
                    return cancel_result()

                # VOICEVOXのpostPhonemeが効かない場合があるため、生成後に無音を直接追加
                # 速度が高いほど末尾フォネームが詰まるので比例して余白を増やす
                _TAIL_SILENCE_SEC = max(0.1, 0.1 * speed_scale)
                try:
                    with wave.open(audio_path, 'rb') as wr:
                        sr = wr.getframerate()
                        ch = wr.getnchannels()
                        sw = wr.getsampwidth()
                        orig_frames = wr.readframes(wr.getnframes())
                    silence = b'\x00' * (int(sr * _TAIL_SILENCE_SEC) * ch * sw)
                    with wave.open(audio_path, 'wb') as ww:
                        ww.setframerate(sr)
                        ww.setnchannels(ch)
                        ww.setsampwidth(sw)
                        ww.writeframes(orig_frames + silence)
                except Exception as e:
                    update_status(f"  ⚠ 無音追加失敗(無視): {e}")

                try:
                    with wave.open(audio_path, 'rb') as wr:
                        # AdditionalTime=0.3s from character_templates.json must be added to Length
                        # so YMM4 plays the full WAV without internal early cutoff.
                        _ADDITIONAL_FRAMES = math.ceil(0.3 * editor.fps)
                        wav_frames = math.ceil(wr.getnframes() / wr.getframerate() * editor.fps)
                        duration_frames = wav_frames + _ADDITIONAL_FRAMES
                except Exception as e:
                    update_status(f"  ❌ WAV読み込み失敗: {e}")
                    report.voices_failed += 1
                    continue

                voice_item_frames = duration_frames + math.ceil(VOICE_TAIL_SAFETY_SEC * editor.fps)
                dialogue_tachie_info.append((char_key, emotion, current_frame, current_frame + voice_item_frames))
                editor.add_voice_item(char_key, chunk_text, hatsuon=kana, file_path=audio_path, start_frame=current_frame, duration=voice_item_frames)
                current_frame += voice_item_frames + math.ceil(INTER_DIALOGUE_GAP_SEC * editor.fps)

    # 終了画面用に1秒延長
    if is_cancelled():
        return cancel_result()
    current_frame += editor.fps

    # Finalize
    if current_bg and current_frame > bg_start_frame:
        bg_path = os.path.join(theme_bg_dir, current_bg)
        if os.path.exists(bg_path):
            editor.add_image_item(bg_path, bg_start_frame, current_frame - bg_start_frame, layer=0)
            
    # Build per-character emotion-segmented TachieItems
    from collections import defaultdict
    char_order = list(dict.fromkeys(info[0] for info in dialogue_tachie_info))
    char_dialogues = defaultdict(list)
    for char, emotion, start, end in dialogue_tachie_info:
        char_dialogues[char].append((emotion, start, end))

    TACHIE_PARAMS = {
        "ずんだもん": {"long": (-696, 430, 66.9),   "shorts": (-364.5, 850, 60.3)},
        "めたん":     {"long": ( 751, 430, 52.95),  "shorts": ( 348.0, 850, 50.1)},
    }
    for i, char_name in enumerate(char_order):
        if is_cancelled():
            return cancel_result()
        mode = "shorts" if is_shorts else "long"
        key = next((k for k in TACHIE_PARAMS if k in char_name), None)
        x_pos, y_pos, tachie_zoom = TACHIE_PARAMS[key][mode] if key else (0, 0, 30)
        layer = 3 + i

        # Fill gaps between dialogues with ノーマル, then merge consecutive same-emotion blocks
        # All segments clipped to start at frame 3 (TACHIE_START_FRAME) at the earliest
        TACHIE_START_FRAME = 3
        segs = sorted(char_dialogues[char_name], key=lambda x: x[1])
        full_segs = []
        prev_end = TACHIE_START_FRAME
        for emotion, start, end in segs:
            effective_start = max(start, TACHIE_START_FRAME)
            if end <= effective_start:
                continue
            if start > prev_end:
                full_segs.append(["ノーマル", prev_end, effective_start])
            full_segs.append([emotion, effective_start, end])
            prev_end = end
        if prev_end < current_frame:
            full_segs.append(["ノーマル", prev_end, current_frame])

        merged = []
        for seg in full_segs:
            if merged and merged[-1][0] == seg[0]:
                merged[-1][2] = seg[2]
            else:
                merged.append(list(seg))

        for emotion, start, end in merged:
            if end > start:
                editor.add_tachie_item(
                    char_name,
                    start,
                    end - start,
                    layer=layer,
                    x=x_pos,
                    y=y_pos,
                    zoom=tachie_zoom,
                    emotion=emotion,
                )

    editor.merge_consecutive_tachie_items()
    _add_fixed_bgm(editor, current_frame, update_status)
    if is_cancelled():
        return cancel_result()
    total_sec = current_frame / editor.fps
    duration_result = duration_review(total_sec, is_shorts)
    duration_review_path = save_duration_review(theme_dir, duration_result)
    _dur_label = f"{total_sec:.1f}秒"
    if not is_shorts:
        _m, _s = divmod(int(total_sec), 60)
        _dur_label = f"{_m}分{_s}秒 ({total_sec:.1f}秒)"
    duration_status_text = duration_status_label(duration_result.get("status"))
    update_status(
        f"━━━━━━━━ 尺チェック {_dur_label} / {duration_status_text} ━━━━━━━━\n"
        f"  理想: {duration_result.get('ideal')} / 許容: {duration_result.get('acceptable')}\n"
        f"  保存先: {duration_review_path}",
        "duration",
    )

    update_status("💾 YMM4プロジェクトを保存中...")
    editor.save(project_file_path)
    report.elapsed_sec = time.time() - pipeline_start
    msg = f"✅ 完成! プロジェクト保存済み: {project_file_path}"
    update_status(msg)

    if is_shorts:
        if total_sec < 35:
            update_status(f"📏 動画尺: {total_sec:.1f}秒 ⚠ 短すぎ（35秒未満）", "warning")
        elif total_sec < 38:
            update_status(f"📏 動画尺: {total_sec:.1f}秒 ✅ やや短いがOK（35〜37秒）", "success")
        elif total_sec <= 50:
            update_status(f"📏 動画尺: {total_sec:.1f}秒 ✅ 理想（38〜50秒）", "success")
        elif total_sec <= 55:
            update_status(f"📏 動画尺: {total_sec:.1f}秒 ⚠ OKだけど長め（51〜55秒）", "warning")
        elif total_sec <= 58:
            update_status(f"📏 動画尺: {total_sec:.1f}秒 ⚠⚠ カット推奨（〜58秒）", "warning")
        else:
            update_status(f"📏 動画尺: {total_sec:.1f}秒 🚨 要カット（58秒超え）", "error")

    update_status(report.summary())
    return msg, report

def main():
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    if len(sys.argv) < 2: return
    topic = sys.argv[1]
    debug_mode = "debug=y" in sys.argv
    run_pipeline(topic, debug_mode=debug_mode)

if __name__ == "__main__":
    main()
