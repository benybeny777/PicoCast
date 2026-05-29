import os
import sys
import wave
import time
import subprocess
import re
import uuid
import json
import shutil
import gc
from core.voicevox import VoicevoxAPI
from core.reading_normalizer import ReadingNormalizer
from core.parser import ScriptParser
from core.ai_generator import AIGenerator
from core.ng_words import apply_ng_word_replacements
from core.youtube_metadata import optimize_description, optimize_tags
from core.image_generator import ImageGenerator
from core.opening_quality import (
    apply_opening_rewrite_to_script,
    check_openai_final_review_connection,
    duration_review,
    duration_status_label,
    final_chatgpt_review,
    llm_opening_review,
    local_opening_review,
    opening_score_tag,
    rewrite_opening_with_ollama,
    save_duration_review,
    save_final_review,
    save_opening_review,
    should_auto_rewrite_opening,
)
from config import (
    CHARACTERS,
    MAX_BACKGROUNDS_LONG,
    MAX_BACKGROUNDS_LONG_BUDGET,
    MAX_BACKGROUNDS_SHORTS,
    NATIVE_LONG_BODY_VOICE_SPEED,
    NATIVE_LONG_INTRO_VOICE_SPEED,
    NATIVE_SHORTS_AVG_CHARS_MIN,
    NATIVE_SHORTS_BODY_VOICE_SPEED,
    NATIVE_SHORTS_CHARS_MUST_FIX_MIN,
    NATIVE_SHORTS_ESTIMATE_BASE_CPS,
    NATIVE_SHORTS_INTRO_VOICE_SPEED,
    NATIVE_SHORTS_LINES_IDEAL_MIN,
    NATIVE_SHORTS_LINES_IDEAL_MAX,
    NATIVE_SHORTS_LINES_MUST_FIX,
    NATIVE_SHORTS_LINES_TARGET_MAX,
    NATIVE_SHORTS_LINES_TARGET_MIN,
    NATIVE_SHORTS_SHORT_LINE_MAX,
    NATIVE_SHORTS_TARGET_CHARS_MAX,
    NATIVE_SHORTS_TARGET_CHARS_MIN,
    OLLAMA_REWRITE_FALLBACK_MODEL,
    OLLAMA_REWRITE_MODEL,
    OPENING_SCORE_HARD_ABORT_THRESHOLD,
    OPENING_SCORE_ABORT_THRESHOLD,
    OPENING_REWRITE_MAX_FALLBACKS,
    LONG_THUMBNAIL_AB_TEST,
    THUMBNAIL_CHARACTER_PNGS,
    THUMBNAIL_HOLD_FRAMES_SHORTS,
    TRANSITION_SEC,
    VIDEO_FPS,
    VOICE_INTRO_FAST_LINES,
    VOICEVOX_PATH,
    VOICE_TAIL_SAFETY_SEC,
)
from core.comment_templates import build_fixed_comment
from core.cta_policy import (
    build_cta_policy,
    check_shorts_navigation_ng,
    write_policy_file,
)


class OutputDirectoryLockedError(Exception):
    """既存の出力フォルダが開かれていて退避できない場合の再試行用エラー。"""


def _find_locking_process(path):
    """ファイルをロックしているプロセスの 'Name (PID)' を返す。ロックなしは None。"""
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
        return None  # フォールバック許可: プロセスロック確認は補助情報のため失敗しても継続
    return None


def _cleanup_old_theme_backups(backup_base: str, safe_topic: str, keep: str | None = None, keep_count: int = 1) -> int:
    """同一テーマのバックアップを新しい順に keep_count 件だけ残す。"""
    if not backup_base or not safe_topic or not os.path.isdir(backup_base):
        return 0
    backup_base_abs = os.path.abspath(backup_base)
    keep_abs = os.path.abspath(keep) if keep else None
    prefix = f"{safe_topic}_"
    candidates = []
    for name in os.listdir(backup_base_abs):
        path = os.path.abspath(os.path.join(backup_base_abs, name))
        if not path.startswith(backup_base_abs + os.sep):
            continue
        if not os.path.isdir(path):
            continue
        if name == safe_topic or name.startswith(prefix):
            candidates.append(path)
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    if keep_abs and keep_abs in candidates:
        candidates.remove(keep_abs)
        candidates.insert(0, keep_abs)
    removed = 0
    for path in candidates[keep_count:]:
        shutil.rmtree(path)
        removed += 1
    return removed


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
    """アップロード済みYouTube動画IDをLongサムネA/Bマニフェストに記録する。"""
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
    "\n#ずんだもん #ゆっくり解説 #食べ物雑学 #食べ物の歴史 #VOICEVOX #雑学ショート"
)




def _normalize_meta(meta: dict, is_shorts: bool, topic: str, update_status) -> None:
    """説明文・タグをNG語置換・最適化して meta をインプレース更新する。"""
    if "description" in meta:
        _desc, _stripped = _strip_voicevox_credit(meta["description"].rstrip())
        if _stripped:
            update_status("  説明文の手書きVOICEVOXクレジットを自動除去しました")
        _desc = re.sub(r'#\S+', '', _desc).strip()
        _desc = optimize_description(apply_ng_word_replacements(_desc), is_shorts=is_shorts, keep_hashtags=False)
        meta["description"] = _desc + _VOICEVOX_CREDIT + _CHANNEL_FOOTER
    if "tags" in meta:
        meta["tags"] = optimize_tags(
            meta["tags"],
            title=meta.get("video_title", topic),
            description=meta.get("description", ""),
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
    """台本テキストから動画形式を検出する。Shorts/ショート のみ True。Long/ロング/ネタ会議 は False。"""
    for line in script_content.splitlines():
        line = line.strip().replace("**", "")
        m = re.match(r'^(?:動画形式|Format)[:：]\s*(.+)$', line, re.IGNORECASE)
        if m:
            val = m.group(1).strip().lower()
            return "shorts" in val or "ショート" in val
    return False


def _detect_is_netakaigi(script_content):
    """台本テキストからネタ会議モードを検出する。動画形式: ネタ会議* のみ True。"""
    for line in script_content.splitlines():
        line = line.strip().replace("**", "")
        m = re.match(r'^(?:動画形式|Format)[:：]\s*(.+)$', line, re.IGNORECASE)
        if m:
            return "ネタ会議" in m.group(1)
    return False


def _detect_netakaigi_variant(script_content: str) -> str:
    """ネタ会議の画面形式バリアントを返す。'Long'（横） または 'Shorts'（縦・デフォルト）。

    判定優先順位:
      1. 動画形式: ネタ会議Long  → "Long"
      2. 動画形式: ネタ会議Shorts → "Shorts"
      3. 画面形式: 横            → "Long"
      4. その他（動画形式: ネタ会議 等） → "Shorts"（縦デフォルト）
    """
    format_val = ""
    screen_format = ""
    for line in script_content.splitlines():
        s = line.strip().replace("**", "")
        m = re.match(r'^(?:動画形式|Format)[:：]\s*(.+)$', s, re.IGNORECASE)
        if m:
            format_val = m.group(1).strip()
        m2 = re.match(r'^(?:画面形式|ScreenFormat)[:：]\s*(.+)$', s, re.IGNORECASE)
        if m2:
            screen_format = m2.group(1).strip()
        if format_val and screen_format:
            break
    if "Long" in format_val or "ロング" in format_val:
        return "Long"
    if "Shorts" in format_val or "ショート" in format_val:
        return "Shorts"
    if screen_format and ("横" in screen_format or "wide" in screen_format.lower()):
        return "Long"
    return "Shorts"  # デフォルトは縦（Shorts相当）


class GenerationReport:
    def __init__(self):
        self.voices_generated = 0
        self.voices_failed = 0
        self.backgrounds_generated = 0
        self.backgrounds_failed = 0
        self.elapsed_sec = 0.0
        self.native_render_used = False  # True when ffmpeg/native MP4 is used

    def summary(self):
        m, s = divmod(int(self.elapsed_sec), 60)
        elapsed = f"{m}分{s}秒" if m else f"{s}秒"
        return (
            f"⏱  所要時間: {elapsed}\n"
            f"🎤 音声: 生成={self.voices_generated} / 失敗={self.voices_failed}\n"
            f"🖼  背景: 生成={self.backgrounds_generated} / 失敗={self.backgrounds_failed}"
        )


def _estimate_script_duration(items, is_shorts: bool):
    """VOICEVOX生成前に台本の尺を推定する。
    Shorts: native速度（1.40x/1.25x、chars_per_sec=3.0）で計算。
    Long: native速度（1.40x/1.20x）で計算。
    """
    dialogue_items = [it for it in items if it["type"] == "dialogue"]
    if not dialogue_items:
        return None, 0, 0.0
    n = len(dialogue_items)
    total_chars = sum(len(it.get("text", "")) for it in dialogue_items)
    avg_chars = total_chars / n if n else 0.0

    elapsed = 0.0
    if is_shorts:
        for i, item in enumerate(dialogue_items):
            chars = len(item.get("text", ""))
            speed = NATIVE_SHORTS_INTRO_VOICE_SPEED if i < VOICE_INTRO_FAST_LINES else NATIVE_SHORTS_BODY_VOICE_SPEED
            elapsed += chars / (NATIVE_SHORTS_ESTIMATE_BASE_CPS * speed) + 0.1 * speed
    else:
        additional = TRANSITION_SEC + VOICE_TAIL_SAFETY_SEC + INTER_DIALOGUE_GAP_SEC
        for i, item in enumerate(dialogue_items):
            chars = len(item.get("text", ""))
            speed = NATIVE_LONG_INTRO_VOICE_SPEED if i < VOICE_INTRO_FAST_LINES else NATIVE_LONG_BODY_VOICE_SPEED
            elapsed += chars / (5.4 * speed) + 0.1 * speed + additional
    return elapsed, n, avg_chars




def generate_thumbnail(img_gen, topic, is_shorts, theme_dir, theme_bg_dir, update_status=None,
                       script_content=None, debug_mode=False, long_thumbnail_ab_test=None):
    """台本内容をもとにサムネイル画像を生成する（IMAGE_BACKEND に従い Nano Banana または Stable Diffusion WebUI Forge を使用）。"""
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

    char_refs = [p for p in THUMBNAIL_CHARACTER_PNGS.values() if os.path.exists(p)]

    # プロンプトをファイルに保存（再生成・デバッグ用）
    prompt_path = os.path.join(thumbs, "thumbnail_prompt.txt")
    try:
        with open(prompt_path, "w", encoding="utf-8") as pf:
            pf.write(prompt)
    except Exception:
        raise

    # サムネイルは IMAGE_BACKEND に従う（sd_webui の場合は SD WebUI で生成）
    # background_engine を明示的に渡すことでバックエンドを固定する
    thumb_engine = img_gen.background_engine
    thumb_img_gen = ImageGenerator(
        width=img_gen.width, height=img_gen.height,
        debug=img_gen.debug, image_style=img_gen.image_style, sd_size_mode=img_gen.sd_size_mode,
        background_engine=thumb_engine,
    )

    def _finish_thumbnail(value):
        thumb_img_gen.close()
        return value

    def _generate_one(one_prompt, final_path, label):
        _log(f"サムネイル生成中: {label}")
        if debug_mode:
            _log(f"  [DEBUG] サムネイルプロンプト保存: {prompt_path}")
        generated_name = thumb_img_gen.generate_background(
            one_prompt,
            target_dir=theme_bg_dir,
            raw=True,
            reference_image_paths=char_refs,
            is_thumbnail=True,
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
            return _finish_thumbnail(None)
        if not saved_path:
            _log("  サムネイル生成をスキップしました")
            return _finish_thumbnail(None)
        _log(f"  サムネイル保存: {saved_path}")
        return _finish_thumbnail(saved_path)

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
                return _finish_thumbnail(None)
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
        return _finish_thumbnail(None)

    if not first_variant_path:
        _log("  サムネイル生成をスキップしました")
        return _finish_thumbnail(None)
    if os.path.exists(thumb_path):
        os.remove(thumb_path)
    shutil.copy2(first_variant_path, thumb_path)
    if ab_test:
        manifest_path = _write_long_thumbnail_manifest(theme_dir, topic, manifest_variants)
        _log(f"  サムネイルA/B管理ファイル保存: {manifest_path}")
    _log(f"  アップロード用サムネイル保存: {thumb_path}")
    return _finish_thumbnail(thumb_path)


def merge_telops_into_backgrounds(items):
    """テロップアイテムを直前の背景プロンプトに折り込み、Nano Bananaにテキストを描画させる。"""
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
    """セリフ直後に背景行が来る台本形式を正規化する。"""
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


def regenerate_thumbnail_only(output_dir, image_style="通常", debug=False, progress_callback=None, sd_size_mode=False, long_thumbnail_ab_test=None, background_engine=None):
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

    # background_engine=None → IMAGE_BACKEND の設定に従う
    img_gen = ImageGenerator(width=width, height=height, debug=debug, image_style=image_style, sd_size_mode=sd_size_mode, background_engine=background_engine)
    try:
        thumb_path = generate_thumbnail(img_gen, topic, is_shorts, output_dir, theme_bg_dir,
                                        update_status, script_content=script_content, debug_mode=debug,
                                        long_thumbnail_ab_test=long_thumbnail_ab_test)
        if not thumb_path:
            raise Exception("サムネイル生成に失敗しました")
        return thumb_path
    finally:
        img_gen.close()


def run_pipeline(topic, reference_script=None, debug_mode=False,
                 progress_callback=None, pregenerated_script=None,
                 image_style="通常", reuse_backgrounds=False, use_batch_api=False,
                 cancel_event=None, existing_titles=None, long_thumbnail_ab_test=None,
                 long_budget_mode=None, sd_size_mode=False,
                 background_engine=None):
    report = GenerationReport()
    pipeline_start = time.time()
    img_gen = None

    def update_status(msg, tag="info"):
        if progress_callback:
            progress_callback(msg, tag)
        else:
            print(msg, flush=True)

    def is_cancelled():
        return bool(cancel_event and cancel_event.is_set())

    def cancel_result():
        if img_gen is not None:
            img_gen.close()
        report.elapsed_sec = time.time() - pipeline_start
        msg = "⏹ 作業を中止しました。"
        update_status(msg)
        return msg, report

    def finish_result(msg):
        if img_gen is not None:
            img_gen.close()
        return msg, report

    # 外部サービスのデバイス情報をログに出力
    try:
        from core.external_service_check import get_service_info_lines
        for line in get_service_info_lines():
            update_status(line)
    except Exception:
        pass  # フォールバック許可: デバイス情報表示は補助的

    # Step 1: スクリプト取得（形式判定のために先に行う）
    ai = AIGenerator(debug=debug_mode)
    try:
        if pregenerated_script:
            script_content = pregenerated_script
            update_status("台本を読み込み中...")
        else:
            # Web UIからは通常 pregenerated_script が渡されるため、直接呼び出し時だけAI生成を行う
            update_status(f"AI台本を生成中: {topic}...")
            script_content = ai.generate_script(topic, reference_script=reference_script, existing_titles=existing_titles)
            if script_content.startswith("Error"):
                report.elapsed_sec = time.time() - pipeline_start
                return script_content, report
    finally:
        ai.close()
    if is_cancelled():
        return cancel_result()

    # ★ 非本編ブロック（候補一覧/固定コメント/アンケート）を本編から分離
    _blocks = ScriptParser.extract_non_body_blocks(script_content)

    # ★ 最初のバリデーション（sanitize前・body_text のみで検証）
    _early_items = ScriptParser.parse_string(_blocks["body_text"])
    _is_valid, _messages = ScriptParser.validate(_early_items)
    _early_title = next((it["text"] for it in _early_items if it["type"] == "video_title"), None)
    if _early_title:
        update_status(f"  📋 取得タイトル: {_early_title}")
    if not _is_valid:
        report.elapsed_sec = time.time() - pipeline_start
        msg = "❌ 台本形式エラー:\n" + "\n".join(_messages)
        update_status(msg)
        return finish_result(msg)
    if is_cancelled():
        return cancel_result()

    script_content = apply_ng_word_replacements(script_content)
    script_content = re.sub(r'(?m)^サムネイル[:：][^\n]*\n?', '', script_content)
    if is_cancelled():
        return cancel_result()

    # Step 2: 動画形式を検出
    is_shorts = _detect_is_shorts(script_content)
    is_netakaigi = _detect_is_netakaigi(script_content)
    netakaigi_variant = _detect_netakaigi_variant(script_content) if is_netakaigi else None
    try:
        _nav_hits = check_shorts_navigation_ng(script_content, "Shorts" if is_shorts else "Long")
        if _nav_hits:
            update_status(
                "⚠ Shortsでは直接的な他動画誘導・次回予告が含まれています。"
                f"ループ締めに変更してください: {', '.join(_nav_hits)}",
                "warning",
            )
    except Exception:
        raise
    if is_shorts:
        max_backgrounds = MAX_BACKGROUNDS_SHORTS
    elif long_budget_mode:
        max_backgrounds = MAX_BACKGROUNDS_LONG_BUDGET
    else:
        max_backgrounds = MAX_BACKGROUNDS_LONG

    _render_engine = "native"
    report.native_render_used = True

    intro_voice_speed = NATIVE_SHORTS_INTRO_VOICE_SPEED if is_shorts else NATIVE_LONG_INTRO_VOICE_SPEED
    body_voice_speed = NATIVE_SHORTS_BODY_VOICE_SPEED if is_shorts else NATIVE_LONG_BODY_VOICE_SPEED

    if is_shorts:
        update_status(
            f"🎬 Shorts本番レンダリング: ffmpeg/native\n"
            f"   🔊 音声速度: intro {intro_voice_speed:.2f} / body {body_voice_speed:.2f}\n"
            f"   📏 台本基準: {NATIVE_SHORTS_LINES_TARGET_MIN}〜{NATIVE_SHORTS_LINES_TARGET_MAX}行 / "
            f"{NATIVE_SHORTS_TARGET_CHARS_MIN}〜{NATIVE_SHORTS_TARGET_CHARS_MAX}字目標"
        )
    if is_netakaigi:
        _fmt_label = f"ネタ会議{'Long（横）' if netakaigi_variant == 'Long' else 'Shorts（縦）'}"
    else:
        _fmt_label = "Shorts" if is_shorts else "ロング"
    update_status(f"📐 動画形式: {_fmt_label}")

    # Step 3: パス設定（台本のvideo_titleを優先してフォルダ名に使う）
    folder_base = _early_title if _early_title else topic
    safe_topic = re.sub(r'[\\/:*?"<>|]', '_', folder_base)
    if is_shorts and not safe_topic.startswith("[Shorts]"):
        safe_topic = f"[Shorts]{safe_topic}"
    elif is_netakaigi and not safe_topic.startswith("[ネタ会議]"):
        safe_topic = f"[ネタ会議]{safe_topic}"
    elif not is_shorts and not is_netakaigi and not safe_topic.startswith("[Long]"):
        safe_topic = f"[Long]{safe_topic}"

    theme_dir = os.path.join("output", safe_topic)

    width = 1080 if is_shorts else 1920
    height = 1920 if is_shorts else 1080
    # ネタ会議は variant に基づいて画面サイズを上書き（is_shorts の値に依存しない）
    if is_netakaigi:
        if netakaigi_variant == "Long":
            width, height = 1920, 1080
        else:
            width, height = 1080, 1920  # Shorts / デフォルト（縦）
    update_status(f"   📐 解像度: {width}x{height}")

    # Step 4: 既存フォルダは削除せず、先にバックアップへ退避する。
    # 開きっぱなしで退避できない場合は、Web UI側で警告して同じ生成を再試行する。
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
            removed_old_backups = _cleanup_old_theme_backups(backup_base, safe_topic, keep=backup_dir, keep_count=1)
            if removed_old_backups:
                update_status(f"🧹 古い同一テーマのバックアップを削除しました: {removed_old_backups}件")
        except (PermissionError, Exception) as e:
            locker = _find_locking_process(theme_dir) if isinstance(e, PermissionError) else None
            locker_info = f" (ロック: {locker})" if locker else ""
            update_status(f"⚠️ バックアップをスキップして上書き生成します{locker_info}")

        if _existing_theme_backup:
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
        f.write(script_content)  # 元テキスト全文を保存（参照用）

    # 本編テキスト（候補一覧/固定コメント/アンケートを除外済み）をパース
    items = ScriptParser.parse_string(_blocks["body_text"])

    # メタデータ（サムネ/タイトル/説明文/タグ）を取得して保存
    meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
    # 抽出ブロックのデータをメタに補完（body_text 側に同じキーがなければ追加）
    if _blocks["has_candidates"] and "meeting_candidates" not in meta:
        meta["meeting_candidates"] = _blocks["candidates_text"]
    if _blocks["has_fixed_comment"] and "fixed_comment" not in meta:
        meta["fixed_comment"] = _blocks["fixed_comment_text"]
    if _blocks["has_poll_options"] and "poll_options" not in meta:
        meta["poll_options"] = _blocks["poll_options_text"]
    items = [it for it in items if it["type"] not in ScriptParser.META_TYPES]
    items = normalize_background_order(items)
    try:
        topic_request_allowed = str(meta.get("topic_request_cta", "")).strip() == "許可"
        cta_policy = build_cta_policy(
            "Shorts" if is_shorts else "Long",
            generation_kind=meta.get("generation_kind", ""),
            topic_request_allowed=topic_request_allowed,
            topic_request_reason=meta.get("topic_request_cta_reason", ""),
            final_cta_type="topic_request" if topic_request_allowed else ("loop" if is_shorts else "long_related_video"),
        )
        write_policy_file(theme_dir, cta_policy)
    except Exception as e:
        update_status(f"  ⚠ CTA方針メタ保存をスキップ: {e}", "warning")

    ai_thumbnail_prompt = meta.get("thumbnail")

    _normalize_meta(meta, is_shorts, topic, update_status)

    opening_title = meta.get("video_title", topic)
    opening_thumb_text = meta.get("thumbnail_text", "")
    opening_review = local_opening_review(items, opening_title, opening_thumb_text, is_shorts, render_engine=_render_engine)
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
                    return finish_result(msg)
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
            return finish_result(msg)
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
                    render_engine=_render_engine,
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
                    _normalize_meta(meta, is_shorts, topic, update_status)
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
    score_tag = opening_score_tag(final_score, opening_critical_errors)
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
        if is_netakaigi:
            update_status(
                f"⚠ ネタ会議モード: 冒頭スコア低め（{final_score}点）ですが処理を続行します",
                "warning",
            )
        else:
            msg = (
                f"❌ 冒頭チェックの重大エラーで処理を中止しました（{final_score}点 / 停止基準: {OPENING_SCORE_HARD_ABORT_THRESHOLD}点未満またはmust_fixあり）\n"
                "台本の冒頭を修正してから再実行してください。"
            )
            update_status(msg, "error")
            report.elapsed_sec = time.time() - pipeline_start
            return finish_result(msg)

    estimated_sec, estimated_lines, estimated_avg_chars = _estimate_script_duration(items, is_shorts)
    estimated_sec = float(estimated_sec or 0.0)
    estimated_duration_result = duration_review(estimated_sec, is_shorts)
    estimated_duration_result["estimated"] = True
    estimated_dialogue_chars = sum(len(it.get("text", "")) for it in items if it.get("type") == "dialogue")
    if (
        is_shorts
        and (
            estimated_lines < NATIVE_SHORTS_LINES_IDEAL_MIN
            or estimated_lines >= NATIVE_SHORTS_LINES_MUST_FIX
            or estimated_dialogue_chars < NATIVE_SHORTS_CHARS_MUST_FIX_MIN
            or estimated_avg_chars < NATIVE_SHORTS_AVG_CHARS_MIN
            or sum(1 for it in items if it.get("type") == "dialogue" and len(it.get("text", "")) <= 10) > NATIVE_SHORTS_SHORT_LINE_MAX
        )
    ):
        missing_to_target = max(0, NATIVE_SHORTS_TARGET_CHARS_MIN - estimated_dialogue_chars)
        short_line_count = sum(1 for it in items if it.get("type") == "dialogue" and len(it.get("text", "")) <= 10)
        msg = (
            "❌ native Shortsの台本量不足で処理を中止しました\n"
            f"行数: {estimated_lines}行 / 理想: {NATIVE_SHORTS_LINES_IDEAL_MIN}〜{NATIVE_SHORTS_LINES_IDEAL_MAX}行\n"
            f"セリフ本文: {estimated_dialogue_chars}文字 / 最低: {NATIVE_SHORTS_CHARS_MUST_FIX_MIN}文字以上"
            f" / 目標: {NATIVE_SHORTS_TARGET_CHARS_MIN}〜{NATIVE_SHORTS_TARGET_CHARS_MAX}文字\n"
            f"平均: {estimated_avg_chars:.1f}文字 / 必須: {NATIVE_SHORTS_AVG_CHARS_MIN:.1f}文字以上\n"
            f"10文字以下の短文: {short_line_count}行 / 最大: {NATIVE_SHORTS_SHORT_LINE_MAX}行\n"
            f"不足文字数: 目標{NATIVE_SHORTS_TARGET_CHARS_MIN}文字まであと{missing_to_target}文字"
        )
        update_status(msg, "error")
        report.elapsed_sec = time.time() - pipeline_start
        return finish_result(msg)
    # native版では推定尺は参考値のみ。尺は台本量で調整するため停止しない。
    update_status(
        f"📐 native推定: {estimated_sec:.1f}秒（{estimated_lines}行 / 平均{estimated_avg_chars:.1f}文字）"
        f" ※nativeでは尺ではなく語り速度と台本量で調整"
    )
    update_status(
        f"🧑‍⚖️ ChatGPTで生成前レビュー中... 推定尺 {estimated_sec:.1f}秒"
        f"（{estimated_lines}行 / 平均{estimated_avg_chars:.1f}文字）"
    )
    openai_check = check_openai_final_review_connection()
    if openai_check.get("skipped"):
        final_review_path = save_final_review(
            theme_dir,
            {
                "skipped": True,
                "reason": openai_check.get("reason", "OPENAI_FINAL_REVIEW_ENABLED is false"),
                "stage": "pre_generation",
                "model": openai_check.get("model"),
            },
        )
        update_status(f"⚠ ChatGPT生成前レビューをスキップ: {openai_check.get('reason')} ({final_review_path})", "warning")
        openai_check = {"ok": True, "skipped_handled": True}
    if not openai_check.get("ok"):
        error = openai_check.get("error", "unknown error")
        final_review_path = save_final_review(
            theme_dir,
            {"error": error, "stage": "pre_generation_connection_check"},
        )
        msg = (
            f"❌ ChatGPT生成前レビュー接続チェック失敗: {error}\n"
            f"保存先: {final_review_path}"
        )
        update_status(msg, "error")
        report.elapsed_sec = time.time() - pipeline_start
        return finish_result(msg)
    if not openai_check.get("skipped_handled"):
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
                render_engine=_render_engine,
            )
            final_review_path = save_final_review(theme_dir, final_review)
            if final_review and final_review.get("skipped"):
                update_status(f"⚠ ChatGPT生成前レビューをスキップ: {final_review.get('reason')} ({final_review_path})", "warning")
            elif final_review:
                pre_score = int(final_review.get("final_score") or 0)
                pre_score_tag = opening_score_tag(pre_score)
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
                    return finish_result(msg)
            else:
                msg = f"❌ ChatGPT生成前レビュー結果が空です ({final_review_path})"
                update_status(msg, "error")
                report.elapsed_sec = time.time() - pipeline_start
                return finish_result(msg)
        except Exception as e:
            final_review_path = save_final_review(theme_dir, {"error": str(e), "stage": "pre_generation"})
            msg = f"❌ ChatGPT生成前レビュー失敗: {e} ({final_review_path})"
            update_status(msg, "error")
            report.elapsed_sec = time.time() - pipeline_start
            return finish_result(msg)

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
        if "generation_kind" in meta:
            lines += ["【生成区分】", meta["generation_kind"], ""]
        if "source_video_title" in meta:
            lines += ["【元動画】", meta["source_video_title"], ""]
        if "generation_purpose" in meta:
            lines += ["【目的】", meta["generation_purpose"], ""]
        if "thumbnail" in meta:
            lines += ["【サムネイルプロンプト】", meta["thumbnail"], ""]
        if "meeting_candidates" in meta:
            lines += ["【候補ネタ】", meta["meeting_candidates"], ""]
            cands = ScriptParser.parse_meeting_candidates(meta["meeting_candidates"])
            topic_candidates_data = {
                "mode": "netakaigi",
                "purpose": "premiere_poll",
                "candidate_count": len(cands),
                "candidates": cands,
                "poll_method": "comments_and_poll",
                "winner": None,
                "later_shorts_video_id": None,
            }
            with open(os.path.join(_meta_dir(theme_dir), "topic_candidates.json"), "w", encoding="utf-8") as nf:
                json.dump(topic_candidates_data, nf, ensure_ascii=False, indent=2)
            update_status(f"📋 候補一覧: あり（{len(cands)}件）")

        if "poll_options" in meta:
            poll_data = ScriptParser.parse_poll_options(meta["poll_options"])
            poll_opts = poll_data.get("options", [])
            if len(poll_opts) < 2:
                update_status("⚠ アンケート設定案: 選択肢が2件未満のため poll_options.json を保存しません", "warning")
            else:
                if len(set(poll_opts)) < len(poll_opts):
                    update_status("⚠ アンケート設定案: 重複選択肢があります", "warning")
                with open(os.path.join(_meta_dir(theme_dir), "poll_options.json"), "w", encoding="utf-8") as pf:
                    json.dump(poll_data, pf, ensure_ascii=False, indent=2)
                poll_copy_text = ScriptParser.format_poll_copy(poll_data)
                with open(os.path.join(_meta_dir(theme_dir), "poll_copy.txt"), "w", encoding="utf-8") as ptf:
                    ptf.write(poll_copy_text)
                update_status(f"📊 アンケート設定案: あり（選択肢{len(poll_opts)}件）  保存先: _meta/poll_copy.txt")
        # 固定コメントを _meta/fixed_comment.txt にも保存
        raw_fixed_comment = meta.get("fixed_comment", "").strip()
        if raw_fixed_comment:
            with open(os.path.join(_meta_dir(theme_dir), "fixed_comment.txt"), "w", encoding="utf-8") as fcf:
                fcf.write(raw_fixed_comment)

        # 台本に固定コメントがなければめたん調テンプレートで生成
        pinned_comment = raw_fixed_comment
        if not pinned_comment:
            _cmt_mode = "topic_request" if topic_request_allowed else "normal"
            pinned_comment = build_fixed_comment(meta.get("video_title", topic), mode=_cmt_mode)
            update_status(f"💬 固定コメント自動生成: めたん調（{_cmt_mode}）")
        if pinned_comment:
            lines += ["【固定コメント】", pinned_comment, ""]
        with open(meta_path, "w", encoding="utf-8") as mf:
            mf.write("\n".join(lines))
        if "video_title" in meta:
            update_status(f"📝 動画タイトル: {meta['video_title']}")
        if is_netakaigi:
            has_fc = bool(raw_fixed_comment)
            update_status(f"💬 固定コメント: {'あり' if has_fc else 'なし'}")
            if "poll_options" not in meta:
                update_status("📊 アンケート設定案: なし")
            if not _blocks["has_candidates"] and not meta.get("meeting_candidates"):
                update_status("⚠ ネタ会議モード: 候補一覧ブロックが見つかりません", "warning")
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
                if os.path.exists(os.path.join(theme_bg_dir, _f)):
                    os.remove(os.path.join(theme_bg_dir, _f))
            _has_saved_bgs = False

    update_status(
        f"📄 台本解析完了: セリフ {len(dialogue_items)}件 / 背景 {len(bg_items)}箇所"
        + (f" / テロップ {telop_count}件(背景に統合)" if telop_count else "")
        + (f" / サムネイル指示あり" if ai_thumbnail_prompt else "")
    )
    for warn in _messages:
        update_status(f"  ⚠ {warn}")

    # よみがな正規化: 辞書・形態素解析による安全な読み補正
    _all_chunks = []
    for _item in dialogue_items:
        _all_chunks.extend(_split_at_punctuation(_item.get("text", "")))
    
    reading_normalizer = ReadingNormalizer()
    
    if reading_normalizer.mode == "safe_auto":
        update_status("🔤 読み補正: safe_auto (Sudachi形態素解析)")
    elif reading_normalizer.mode == "dictionary":
        update_status("🔤 読み補正: dictionary (辞書のみ)")

    reading_map = reading_normalizer.normalize_batch(_all_chunks)
    _changed_map = {k: v for k, v in reading_map.items() if k != v}
    
    if _changed_map:
        _replacements = [f"{k}→{v}" for k, v in _changed_map.items()]
        update_status(f"🔤 読み置換: {', '.join(_replacements)}")
    
    if reading_normalizer.mode in ("dictionary", "safe_auto"):
        # メタ情報保存
        _reading_map_path = os.path.join(_meta_dir(theme_dir), "reading_map.json")
        try:
            with open(_reading_map_path, "w", encoding="utf-8") as _rmf:
                _meta_info = reading_normalizer.get_meta_info()
                _meta_info["original_to_tts"] = _changed_map
                json.dump(_meta_info, _rmf, ensure_ascii=False, indent=2)
        except Exception as _e:
            update_status(f"⚠ reading_map保存失敗: {_e}", "warning")
            
        if reading_normalizer.mode == "safe_auto" and reading_normalizer.candidates:
            _candidates_path = os.path.join(_meta_dir(theme_dir), "reading_candidates.json")
            try:
                with open(_candidates_path, "w", encoding="utf-8") as _rmf:
                    json.dump(reading_normalizer.candidates, _rmf, ensure_ascii=False, indent=2)
                update_status("🔎 読み候補を保存しました")
            except Exception as _e:
                update_status(f"⚠ reading_candidates保存失敗: {_e}", "warning")

    vv = VoicevoxAPI()
    if not vv.check_connection() and os.path.exists(VOICEVOX_PATH):
        subprocess.Popen([VOICEVOX_PATH], creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if is_cancelled():
                return cancel_result()
            if vv.check_connection(): break
            time.sleep(2)

    img_gen = ImageGenerator(
        width=width,
        height=height,
        debug=debug_mode,
        image_style=image_style,
        sd_size_mode=sd_size_mode,
        background_engine=background_engine,
    )

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
                                        script_content=script_content, debug_mode=debug_mode,
                                        long_thumbnail_ab_test=long_thumbnail_ab_test)
        if is_cancelled():
            return cancel_result()

    if thumb_path is None:
        raise Exception(
            "サムネイル画像を生成できませんでした。\n"
            "IMAGE_BACKEND=gemini の場合: Nano Banana の接続・残高を確認してください。\n"
            "IMAGE_BACKEND=sd_webui の場合: Stable Diffusion WebUI の起動状態を確認してください。"
        )

    if is_shorts:
        update_status("  📌 サムネイルをショート先頭に挿入予定(native)")
    # ロングの場合は theme_dir に保存済み

    update_status(f"🎬 アセット生成を開始します...")

    voice_num = 0
    audio_num = 0
    bg_num = 0
    total_voices = len(dialogue_items)
    total_bgs = len(bg_items)


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

    # ── 前処理: 各 dialogue に対応する bg_num を先読み割り当て ──────────────────
    # 音声ファイル名に bg_num を埋め込む必要があるため、
    # 2パス化（音声→背景の順）に先立って対応する背景番号を確定しておく。
    _REUSE_MARKERS = ("前と同じ", "[前と同じ]", "[再利用]", "再利用")
    _pre_bg = 0
    for _it in items:
        if _it["type"] == "background":
            _raw = _it.get("text", _it.get("file", "")).strip()
            if not any(_raw == m or _raw.startswith(m) for m in _REUSE_MARKERS):
                _pre_bg += 1
        elif _it["type"] == "dialogue":
            _it["_bg_num"] = _pre_bg  # この時点での背景番号を一時保持

    # ══════════════════════════════════════════════════════════════════════════
    # パス1: 全音声生成（VOICEVOX）
    # ══════════════════════════════════════════════════════════════════════════
    update_status(f"🎤 音声生成フェーズ（{total_voices}行）...")
    for item in items:
        if is_cancelled():
            return cancel_result()
        if item["type"] != "dialogue":
            continue

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
            audio_filename = f"{item['_bg_num']:03d}_{audio_num:03d}_{_safe_text}.wav"
            audio_path = os.path.join(theme_audio_dir, audio_filename)
            speed_scale = intro_voice_speed if voice_num <= VOICE_INTRO_FAST_LINES else body_voice_speed

            speech_text = reading_map.get(chunk_text, chunk_text)
            preview = chunk_text[:20] + ("…" if len(chunk_text) > 20 else "")
            update_status(f"🎤 音声 [{voice_num}/{total_voices}] コマ{item['_bg_num']} {char_key}({emotion}) x{speed_scale:g}「{preview}」")
            try:
                vv.generate_audio(speech_text, speaker_id, audio_path, speed_scale=speed_scale)
                report.voices_generated += 1
            except Exception as e:
                report.voices_failed += 1
                report.elapsed_sec = time.time() - pipeline_start
                msg = (
                    f"❌ 音声合成失敗のため処理を中止しました\n"
                    f"対象: [{voice_num}/{total_voices}] {char_key}({emotion})「{preview}」\n"
                    f"理由: {e}"
                )
                update_status(msg, "error")
                return finish_result(msg)
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
                    wr.getnframes()
            except Exception as e:
                report.voices_failed += 1
                report.elapsed_sec = time.time() - pipeline_start
                msg = (
                    f"❌ WAV読み込み失敗のため処理を中止しました\n"
                    f"対象: [{voice_num}/{total_voices}] {char_key}({emotion})「{preview}」\n"
                    f"理由: {e}"
                )
                update_status(msg, "error")
                return finish_result(msg)

    # ══════════════════════════════════════════════════════════════════════════
    # パス2: 全背景生成（Gemini / SD WebUI）
    # ══════════════════════════════════════════════════════════════════════════
    update_status(f"🖼  背景生成フェーズ（{total_bgs}件）...")
    for item in items:
        if is_cancelled():
            return cancel_result()
        if item["type"] != "background":
            continue

        _bg_raw = item.get("text", item.get("file", "")).strip()
        if any(_bg_raw == m or _bg_raw.startswith(m) for m in _REUSE_MARKERS):
            update_status(f"🖼  背景 再利用指定 — 前の背景を継続")
            continue

        bg_num += 1
        if bg_num > max_backgrounds:
            update_status(f"🖼  背景 [{bg_num}/{total_bgs}] 上限({max_backgrounds})超過 — 前の背景を継続使用")
            continue

        bg_name = item.get("text", item.get("file", "")).strip() or "default_background"

        if _has_saved_bgs:
            existing_bgs = sorted(
                f for f in os.listdir(theme_bg_dir)
                if f.lower().endswith(".png") and f.lower().startswith("bg_")
            )
            bg_idx = bg_num - 1
            if bg_idx < len(existing_bgs):
                update_status(f"🖼  背景 [{bg_num}/{total_bgs}] 再利用: {existing_bgs[bg_idx]}")
                report.backgrounds_generated += 1
            else:
                update_status(f"🖼  背景 [{bg_num}/{total_bgs}] 既存ファイル不足 — スキップ")
                report.backgrounds_failed += 1
            continue

        if use_batch_api:
            if bg_num in batch_bg_results:
                update_status(f"🖼  背景 [{bg_num}/{total_bgs}] バッチ結果使用: {batch_bg_results[bg_num]}")
            else:
                update_status(f"  ⚠ 背景 [{bg_num}/{total_bgs}] バッチ結果なし — スキップ")
            continue

        update_status(f"🖼  背景 [{bg_num}/{total_bgs}] 生成中: {bg_name[:30]}...")
        try:
            if is_cancelled():
                return cancel_result()
            bg_description = (
                f"以下の台本を参考に、「{bg_name}」のシーンの背景画像を生成してください。\n\n"
                f"【台本】\n{script_content}"
            )
            prompt_file = os.path.join(theme_bg_dir, f"prompt_bg_{bg_num:04d}.txt")
            try:
                with open(prompt_file, "w", encoding="utf-8") as _pf:
                    _pf.write(bg_description)
            except Exception:
                raise
            if debug_mode:
                update_status(f"  [DEBUG] 背景プロンプト保存: {prompt_file}")
            generated_file = img_gen.generate_background(
                bg_description, target_dir=theme_bg_dir,
                fname=f"bg_{bg_num:03d}_001.png",
            )
            if is_cancelled():
                return cancel_result()
        except Exception as e:
            update_status(f"  ❌ 背景生成失敗: {e}", "error")
            generated_file = None
        if generated_file:
            report.backgrounds_generated += 1
            update_status(f"  ✅ 背景生成完了")
        else:
            report.backgrounds_failed += 1
            update_status(f"  ⚠ 背景生成スキップ")

    if is_cancelled():
        return cancel_result()
    if report.voices_failed:
        report.elapsed_sec = time.time() - pipeline_start
        msg = (
            f"❌ 音声生成に失敗したセリフがあるためnative MP4化を中止しました"
            f"（生成={report.voices_generated} / 失敗={report.voices_failed}）\n"
            "VOICEVOXの失敗行を修正して再実行してください。"
        )
        update_status(msg, "error")
        return finish_result(msg)
    if is_cancelled():
        return cancel_result()

    # 実尺チェック: 全WAVの実際の長さを合算して duration_review で評価
    _actual_sec = 0.0
    try:
        for _wf in os.listdir(theme_audio_dir):
            if not _wf.lower().endswith(".wav"):
                continue
            _wp = os.path.join(theme_audio_dir, _wf)
            with wave.open(_wp, "rb") as _wr:
                _actual_sec += _wr.getnframes() / _wr.getframerate()
    except Exception as _e:
        update_status(f"⚠ 実尺計算スキップ: {_e}", "warning")
        _actual_sec = 0.0

    if _actual_sec > 0:
        actual_duration_result = duration_review(_actual_sec, is_shorts, estimated=False)
        dr_path = save_duration_review(theme_dir, actual_duration_result)
        _dur_status = actual_duration_result["status"]
        _dur_label = duration_status_label(_dur_status)
        _ideal = actual_duration_result.get("ideal", "")
        update_status(
            f"⏱ 実尺チェック: {_actual_sec:.1f}秒 — {_dur_label}（目安: {_ideal}）　保存: {dr_path}",
            "warning" if _dur_status in ("warning", "needs_review") else None,
        )
        if _dur_status == "needs_review":
            msg = (
                f"❌ 実尺が規格外のためMP4化を中止しました\n"
                f"実尺: {_actual_sec:.1f}秒 / 目安: {_ideal}\n"
                f"台本の分量を調整して再実行してください。"
            )
            update_status(msg, "error")
            report.elapsed_sec = time.time() - pipeline_start
            return finish_result(msg)

    # render_info を _meta に保存
    try:
        _thumb_frames = THUMBNAIL_HOLD_FRAMES_SHORTS if is_shorts else 0
        render_info = {
            "render_engine": _render_engine,
            "native_renderer": {
                "enabled": True,
                "voice_speed_intro": intro_voice_speed,
                "voice_speed_body": body_voice_speed,
                "min_silence_between_lines": 0.0,
                "target_dialogue_lines": f"{NATIVE_SHORTS_LINES_IDEAL_MIN}-{NATIVE_SHORTS_LINES_IDEAL_MAX}" if is_shorts else "n/a",
                "thumbnail_hold_frames": _thumb_frames,
                "thumbnail_hold_seconds": round(_thumb_frames / VIDEO_FPS, 3),
            },
        }
        render_info_path = os.path.join(_meta_dir(theme_dir), "render_info.json")
        with open(render_info_path, "w", encoding="utf-8") as f:
            json.dump(render_info, f, ensure_ascii=False, indent=2)
    except Exception as e:
        update_status(f"⚠ render_info.json保存に失敗: {e}", "warning")

    report.elapsed_sec = time.time() - pipeline_start
    msg = f"✅ 完成! 出力フォルダ: {theme_dir}"
    update_status(msg)

    update_status(report.summary())
    return finish_result(msg)

