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
import stat
import gc
from core.voicevox import VoicevoxAPI
from core.parser import ScriptParser
from core.ymmp_editor import YmmpEditor
from core.ai_generator import AIGenerator
from core.image_generator import ImageGenerator
from config import CHARACTERS, VOICEVOX_PATH, MAX_BACKGROUNDS


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

_CHANNEL_URL = "https://www.youtube.com/@zunkami"
_VOICEVOX_CREDIT = "\n\n【使用音声合成】VOICEVOX:ずんだもん / VOICEVOX:四国めたん"
_CHANNEL_FOOTER = f"\n\n▶ チャンネル登録はこちら → {_CHANNEL_URL}"




def _split_at_punctuation(text):
    """Shorts用: 句読点(。！？)でセリフを文節に分割する。"""
    chunks = []
    current = ""
    for ch in text:
        current += ch
        if ch in "。！？" and current.strip():
            chunks.append(current)
            current = ""
    if current.strip():
        chunks.append(current)
    return chunks if chunks else [text]


def _detect_is_shorts(script_content):
    """台本テキストから動画形式: Shorts/ロングを検出する。"""
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




def generate_thumbnail(img_gen, topic, is_shorts, theme_dir, theme_bg_dir, update_status=None,
                       script_content=None):
    """Generate thumbnail image via Nano Banana using script content."""
    def _log(msg):
        if update_status: update_status(msg)
        else: print(msg, flush=True)

    thumb_path = os.path.join(theme_dir, "thumbnail.png")

    ratio_tag = "縦9:16のショート動画" if is_shorts else "横16:9のワイドスクリーン"
    safe_zone = (
        "\nセーフゾーン（厳守）: 上下左右30%の範囲にはテキスト・文字・重要な要素を一切配置しないこと。"
    ) if is_shorts else ""
    prompt = (
        f"アスペクト比: {ratio_tag}。{safe_zone}\n"
        f"以下の台本を参考に、YouTubeサムネイル画像を生成してください。\n\n"
        f"{script_content or topic}"
    )

    from config import CHARACTER_PNGS
    char_refs = [p for p in CHARACTER_PNGS.values() if os.path.exists(p)]

    _log("🖼  サムネイルを生成中...")
    try:
        generated = img_gen.generate_background(prompt, target_dir=theme_bg_dir, raw=True,
                                                 reference_image_paths=char_refs)
    except Exception as e:
        _log(f"  ❌ サムネイル生成失敗: {e}")
        return None

    if not generated:
        _log("  ⚠ サムネイル生成スキップ")
        return None

    src = os.path.join(theme_bg_dir, generated)
    if os.path.exists(thumb_path):
        os.remove(thumb_path)
    shutil.copy2(src, thumb_path)

    _log(f"  ✅ サムネイル保存: {thumb_path}")
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
                    f"アニメタイトルカード・少年漫画の必殺技名テキスト風の圧倒的なデザイン。"
                    f"テロップは画面上部35%以内に配置し、非常にくっきり読みやすくすること。"
                )
                result[last_bg_idx] = bg
            # telop item is consumed — not added to result
        else:
            if item["type"] == "background":
                last_bg_idx = len(result)
            result.append(item)
    return result

def regenerate_thumbnail_only(output_dir, image_style="通常", debug=False, progress_callback=None):
    """既存の出力フォルダのサムネイルのみ再生成する。"""
    def update_status(msg):
        if progress_callback:
            progress_callback(msg)
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
                                    update_status, script_content=script_content)
    if not thumb_path:
        raise Exception("サムネイル生成に失敗しました")
    return thumb_path


def run_pipeline(topic, reference_script=None, debug_mode=False,
                 progress_callback=None, pregenerated_script=None,
                 image_style="通常", reuse_backgrounds=False, use_batch_api=False):
    report = GenerationReport()
    pipeline_start = time.time()

    def update_status(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg, flush=True)

    # Step 1: スクリプト取得（形式判定のために先に行う）
    ai = AIGenerator(debug=debug_mode)
    if pregenerated_script:
        script_content = pregenerated_script
        update_status("台本を読み込み中...")
    else:
        update_status(f"AI台本を生成中: {topic}...")
        script_content = ai.generate_script(topic, reference_script=reference_script)
        if script_content.startswith("Error"):
            report.elapsed_sec = time.time() - pipeline_start
            return script_content, report

    update_status("🔍 YouTubeポリシー補正中...")
    script_content = ai.sanitize_for_youtube(script_content)
    script_content = re.sub(r'(?m)^サムネイル[:：][^\n]*\n?', '', script_content)

    # Step 2: 動画形式を検出
    is_shorts = _detect_is_shorts(script_content)
    update_status(f"📐 動画形式: {'Shorts' if is_shorts else 'ロング'}")

    # Step 3: パス設定
    safe_topic = re.sub(r'[\\/:*?"<>|]', '_', topic)
    if is_shorts and not safe_topic.startswith("[Shorts]"):
        safe_topic = f"[Shorts]{safe_topic}"

    theme_dir = os.path.join("output", safe_topic)
    project_file_path = os.path.join(theme_dir, f"{safe_topic}.ymmp")

    width = 1080 if is_shorts else 1920
    height = 1920 if is_shorts else 1080

    # Step 4: 既存フォルダ削除（背景再利用時は退避）
    import tempfile
    _saved_bg_tmp = None
    _saved_thumb_tmp = None
    if os.path.exists(theme_dir):
        if reuse_backgrounds:
            _old_bg_dir = os.path.join(theme_dir, "backgrounds")
            if os.path.exists(_old_bg_dir):
                _saved_bg_tmp = tempfile.mkdtemp()
                for f in os.listdir(_old_bg_dir):
                    shutil.copy2(os.path.join(_old_bg_dir, f), _saved_bg_tmp)
            _old_thumb = os.path.join(theme_dir, "thumbnail.png")
            if os.path.exists(_old_thumb):
                _saved_thumb_tmp = tempfile.mkdtemp()
                shutil.copy2(_old_thumb, os.path.join(_saved_thumb_tmp, "thumbnail.png"))
        gc.collect()  # release any PIL file handles from previous run
        def _on_rm_error(func, path, exc_info):
            os.chmod(path, stat.S_IWRITE)
            for _ in range(5):
                try:
                    func(path)
                    return
                except PermissionError:
                    time.sleep(0.3)
            locker = _find_locking_process(path)
            locker_info = f"\nロック中のプロセス: {locker}" if locker else ""
            raise PermissionError(f"{path}{locker_info}")
        try:
            shutil.rmtree(theme_dir, onerror=_on_rm_error)
        except PermissionError as e:
            raise Exception(f"既存フォルダを削除できませんでした。\n{e}\nそのプロセスを閉じてから再生成してください。")
        except Exception:
            raise Exception(f"既存フォルダを削除できませんでした。\nYMM4やエクスプローラーでフォルダを開いていないか確認してください。\n({theme_dir})")
        update_status(f"🗑  既存フォルダを削除しました: {safe_topic}")

    theme_audio_dir = os.path.join(theme_dir, "audio")
    theme_bg_dir = os.path.join(theme_dir, "backgrounds")
    os.makedirs(theme_audio_dir, exist_ok=True)
    os.makedirs(theme_bg_dir, exist_ok=True)

    # 背景再利用: 退避したファイルを復元（新規作成時は_saved_bg_tmp=Noneなので通常生成へ）
    _has_saved_bgs = False
    if _saved_bg_tmp:
        for f in os.listdir(_saved_bg_tmp):
            shutil.copy2(os.path.join(_saved_bg_tmp, f), theme_bg_dir)
        shutil.rmtree(_saved_bg_tmp)
        _has_saved_bgs = True
        update_status("🖼  既存の背景を再利用します")
    if _saved_thumb_tmp:
        saved_thumb = os.path.join(_saved_thumb_tmp, "thumbnail.png")
        if os.path.exists(saved_thumb):
            shutil.copy2(saved_thumb, os.path.join(theme_dir, "thumbnail.png"))
        shutil.rmtree(_saved_thumb_tmp)

    script_txt_path = os.path.join(theme_dir, "script.txt")
    with open(script_txt_path, "w", encoding="utf-8") as f:
        f.write(script_content)

    items = ScriptParser.parse(script_txt_path)
    is_valid, messages = ScriptParser.validate(items)
    if not is_valid:
        report.elapsed_sec = time.time() - pipeline_start
        msg = "❌ 台本形式エラー:\n" + "\n".join(messages)
        update_status(msg)
        return msg, report

    # Extract and save metadata (thumbnail / title / description / tags)
    meta_types = {"thumbnail", "video_title", "description", "tags", "video_format"}
    meta = {it["type"]: it["text"] for it in items if it["type"] in meta_types}
    items = [it for it in items if it["type"] not in meta_types]

    ai_thumbnail_prompt = meta.get("thumbnail")

    if "description" in meta:
        meta["description"] = meta["description"].rstrip() + _VOICEVOX_CREDIT + _CHANNEL_FOOTER

    if meta:
        meta_path = os.path.join(theme_dir, "metadata.txt")
        lines = []
        if "video_title" in meta:
            lines += ["【動画タイトル】", meta["video_title"], ""]
        if "description" in meta:
            lines += ["【説明文】", meta["description"], ""]
        if "tags" in meta:
            lines += ["【タグ】", meta["tags"], ""]
        if "thumbnail" in meta:
            lines += ["【サムネイルプロンプト】", meta["thumbnail"], ""]
        with open(meta_path, "w", encoding="utf-8") as mf:
            mf.write("\n".join(lines))
        if "video_title" in meta:
            update_status(f"📝 動画タイトル: {meta['video_title']}")

    telop_count = sum(1 for it in items if it["type"] == "telop")
    items = merge_telops_into_backgrounds(items)

    dialogue_items = [it for it in items if it["type"] == "dialogue"]
    bg_items = [it for it in items if it["type"] == "background"]
    update_status(
        f"📄 台本解析完了: セリフ {len(dialogue_items)}件 / 背景 {len(bg_items)}箇所"
        + (f" / テロップ {telop_count}件(背景に統合)" if telop_count else "")
        + (f" / サムネイル指示あり" if ai_thumbnail_prompt else "")
    )
    for warn in messages:
        update_status(f"  ⚠ {warn}")

    vv = VoicevoxAPI()
    if not vv.check_connection() and os.path.exists(VOICEVOX_PATH):
        subprocess.Popen([VOICEVOX_PATH], creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if vv.check_connection(): break
            time.sleep(2)

    editor = YmmpEditor(width=width, height=height, debug=debug_mode)

    from config import ASSETS_DIR
    TEMPLATES_DIR = os.path.join(ASSETS_DIR, "templates")
    op_template = os.path.join(TEMPLATES_DIR, "opening_shorts.ymmp" if is_shorts else "opening.ymmp")
    current_frame = 3  # frame 0-2 reserved for YMM4 init
    if os.path.exists(op_template):
        editor.merge_project(op_template, offset_frames=0)
        current_frame = _read_ymmp_duration(op_template)
        update_status(f"📂 OPテンプレート読み込み完了 ({current_frame}フレーム)")

    img_gen = ImageGenerator(width=width, height=height, debug=debug_mode, image_style=image_style)

    thumbnail_title = meta.get("video_title", topic)
    if _has_saved_bgs:
        # 既存サムネイルをそのまま使用
        thumb_path = os.path.join(theme_dir, "thumbnail.png") if os.path.exists(os.path.join(theme_dir, "thumbnail.png")) else None
        if thumb_path:
            update_status("  📌 既存サムネイルを再利用")
    else:
        thumb_path = generate_thumbnail(img_gen, thumbnail_title, is_shorts, theme_dir, theme_bg_dir, update_status,
                                        script_content=script_content)
    if thumb_path:
        if is_shorts:
            editor.add_image_item(thumb_path, 0, 3, layer=0)
            update_status("  📌 サムネイルをショート先頭フレームに挿入")
        # ロングの場合は theme_dir に保存済み（YMM4 挿入なし）

    update_status(f"🎬 アセット生成 & タイムライン構築を開始します...")

    current_bg = None
    bg_start_frame = current_frame
    voice_num = 0
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
                if _temp_num <= MAX_BACKGROUNDS:
                    bg_name = item.get("text", item.get("file", "")).strip() or "default_background"
                    _batch_items.append((_temp_num, bg_name))

        if _batch_items:
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
            try:
                batch_results = img_gen.generate_backgrounds_batch(batch_requests, target_dir=theme_bg_dir)
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

        if item["type"] == "background":
            if current_bg and current_frame > bg_start_frame:
                bg_path = os.path.join(theme_bg_dir, current_bg)
                if os.path.exists(bg_path):
                    editor.add_image_item(bg_path, bg_start_frame, current_frame - bg_start_frame, layer=0)
                    if first_bg_placed:
                        editor.add_transition_item(current_frame, transition_frames)
                    first_bg_placed = True

            bg_num += 1
            if bg_num > MAX_BACKGROUNDS:
                update_status(f"🖼  背景 [{bg_num}/{total_bgs}] 上限({MAX_BACKGROUNDS})超過 — 前の背景を継続使用")
                bg_start_frame = current_frame
                continue

            bg_name = item.get("text", item.get("file", "")).strip() or "default_background"

            if _has_saved_bgs:
                # 既存背景を順番に割り当て
                existing_bgs = sorted(
                    f for f in os.listdir(theme_bg_dir)
                    if f.startswith("bg_") and f.endswith(".png")
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
                bg_description = (
                    f"以下の台本を参考に、「{bg_name}」のシーンの背景画像を生成してください。\n\n"
                    f"【台本】\n{script_content}"
                )
                generated_file = img_gen.generate_background(
                    bg_description, target_dir=theme_bg_dir,
                    reference_image_path=style_reference_path
                )
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
                audio_filename = f"{uuid.uuid4().hex}.wav"
                audio_path = os.path.join(theme_audio_dir, audio_filename)

                preview = chunk_text[:20] + ("…" if len(chunk_text) > 20 else "")
                update_status(f"🎤 音声 [{voice_num}/{total_voices}] {char_key}({emotion})「{preview}」")
                try:
                    _, kana = vv.generate_audio(chunk_text, speaker_id, audio_path)
                    report.voices_generated += 1
                except Exception as e:
                    update_status(f"  ❌ 音声合成失敗: {e}")
                    report.voices_failed += 1
                    continue

                try:
                    with wave.open(audio_path, 'rb') as wr:
                        # AdditionalTime=0.3s from character_templates.json must be added to Length
                        # so YMM4 plays the full WAV without internal early cutoff
                        _ADDITIONAL_FRAMES = math.ceil(0.3 * editor.fps)
                        duration_frames = math.ceil(wr.getnframes() / wr.getframerate() * editor.fps) + _ADDITIONAL_FRAMES
                except Exception as e:
                    update_status(f"  ❌ WAV読み込み失敗: {e}")
                    report.voices_failed += 1
                    continue

                dialogue_tachie_info.append((char_key, emotion, current_frame, current_frame + duration_frames))
                editor.add_voice_item(char_key, chunk_text, hatsuon=kana, file_path=audio_path, start_frame=current_frame, duration=duration_frames)
                current_frame += duration_frames + 15

    # 終了画面用に5秒延長
    current_frame += 5 * editor.fps

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
                editor.add_tachie_item(char_name, start, end - start, layer=layer, x=x_pos, y=y_pos, zoom=tachie_zoom)

    editor.merge_consecutive_tachie_items()
    update_status("💾 YMM4プロジェクトを保存中...")
    editor.save(project_file_path)
    report.elapsed_sec = time.time() - pipeline_start
    msg = f"✅ 完成! プロジェクト保存済み: {project_file_path}"
    update_status(msg)
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
