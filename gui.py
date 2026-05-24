import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import re
import os
import sys
import subprocess
import traceback
import time
import shutil
import queue
import json
import hashlib
import io
from main import (
    OutputDirectoryLockedError,
    run_pipeline,
    normalize_background_order,
    record_uploaded_video_id_for_thumbnail_ab_test,
    LONG_THUMBNAIL_VARIANTS,
)
from core.ai_generator import AIGenerator
from core.image_generator import ImageGenerator
from core.analytics_score import analytics_period_label, build_performance_summary, format_duration, format_duration_status, save_score_files, score_items, to_tsv
from core.output_paths import UPLOADED_TITLES_FILE, analytics_paths, ensure_output_dirs, migrate_root_file
from core.opening_quality import duration_review, duration_status_label, llm_opening_review, local_opening_review, opening_score_tag, save_duration_review
from core.parser import ScriptParser
from core.script_prompts import build_script_generation_prompt, build_title_prompt
from config import (
    DEFAULT_SHORTS_RENDER_ENGINE,
    FFMPEG_BIN,
    NATIVE_FFMPEG_ENCODER,
    NATIVE_FFMPEG_PRESET,
    SD_SIZE_IMAGE_SCALE,
    THUMBNAIL_CHARACTER_PNGS,
    VOICEVOX_PATH,
    VOICEVOX_URL,
)
import requests

APP_VERSION_BASE = "2026.05.19"


def build_app_version() -> str:
    try:
        count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        short_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        dirty = subprocess.run(
            ["git", "diff", "--quiet"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode != 0
        version = f"{APP_VERSION_BASE}.{count}-{short_hash}"
        return version + ("-dirty" if dirty else "")
    except Exception:
        return APP_VERSION_BASE

try:
    from PIL import Image, ImageTk
except Exception:
    Image = ImageTk = None


def split_input_scripts(raw_scripts):
    """Split pasted scripts by supported batch separators."""
    raw_scripts = raw_scripts.strip()
    if not raw_scripts:
        return []

    # Preferred separator from our prompt.
    scripts = [s.strip() for s in re.split(r'\n-{3,}\n', raw_scripts) if s.strip()]
    if len(scripts) > 1:
        return scripts

    # Also accept headings like: ━━ 動画1：ショート版 ━━
    heading_re = re.compile(r'^\s*━+\s*動画\s*\d+[^。\n]*━+\s*$', re.MULTILINE)
    if heading_re.search(raw_scripts):
        chunks = []
        current = []
        for line in raw_scripts.splitlines():
            if heading_re.match(line):
                if current and any(part.strip() for part in current):
                    chunks.append("\n".join(current).strip())
                current = []
                continue
            current.append(line)
        if current and any(part.strip() for part in current):
            chunks.append("\n".join(current).strip())
        if len(chunks) > 1:
            return chunks

    # Last-resort split: multiple scripts pasted back-to-back starting with 動画形式.
    starts = [m.start() for m in re.finditer(r'(?m)^動画形式[:：]', raw_scripts)]
    if len(starts) > 1:
        starts.append(len(raw_scripts))
        return [raw_scripts[starts[i]:starts[i + 1]].strip() for i in range(len(starts) - 1)]

    return [raw_scripts]


def unified_check(name, primary_url, path):
    file_ok = os.path.exists(path)
    found_url = None
    urls_to_try = [primary_url]
    if "8188" in primary_url or "8000" in primary_url:
        for p in ["8188", "8000", "8189"]:
            alt = primary_url.replace("8188", p).replace("8000", p)
            if alt not in urls_to_try: urls_to_try.append(alt)
    for url in urls_to_try:
        try:
            with requests.get(url, timeout=0.8):
                found_url = url
                break
        except:
            continue
    return {
        "name": name,
        "connected": found_url is not None,
        "url": found_url if found_url else primary_url,
        "file_ok": file_ok,
        "path": path
    }


def ffmpeg_native_status():
    configured = str(NATIVE_FFMPEG_ENCODER or "libx264").strip() or "libx264"
    preset = str(NATIVE_FFMPEG_PRESET or "").strip()
    result = {
        "bin": FFMPEG_BIN,
        "configured": configured,
        "preset": preset,
        "available": False,
        "gpu": configured not in ("", "libx264"),
        "hw_encoders": [],
        "error": "",
    }
    try:
        proc = subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for enc in ("h264_nvenc", "hevc_nvenc", "av1_nvenc", "h264_qsv", "hevc_qsv", "h264_amf", "hevc_amf"):
            if enc in text:
                result["hw_encoders"].append(enc)
        result["available"] = configured == "libx264" or configured in text
        if proc.returncode != 0 and not result["available"]:
            result["error"] = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
            result["error"] = result["error"][0] if result["error"] else f"exit {proc.returncode}"
    except Exception as e:
        result["error"] = str(e)
    return result


def _file_digest(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _load_image_copy(path):
    with open(path, "rb") as f:
        data = f.read()
    with Image.open(io.BytesIO(data)) as src:
        return src.copy()

print(f"\n--- [System Startup Check] ---")
for n, u, p in [("VOICEVOX", VOICEVOX_URL, VOICEVOX_PATH)]:
    res = unified_check(n, u, p)
    c_status = f"[Conn: OK ({res['url']})]" if res['connected'] else "[Conn: ERR]"
    f_status = "[File: OK]" if res['file_ok'] else "[File: ERR]"
    print(f"{res['name']:<10}: {c_status:<35} {f_status}")
_ffmpeg_boot = ffmpeg_native_status()
_ffmpeg_mode = "GPU" if _ffmpeg_boot["gpu"] and _ffmpeg_boot["available"] else "CPU" if _ffmpeg_boot["available"] else "ERR"
_ffmpeg_preset = f" / preset {_ffmpeg_boot['preset']}" if _ffmpeg_boot["preset"] else ""
_ffmpeg_hw = f" / HW: {', '.join(_ffmpeg_boot['hw_encoders'][:4])}" if _ffmpeg_boot["hw_encoders"] else ""
print(f"ffmpeg   : [{_ffmpeg_mode}: {_ffmpeg_boot['configured']}{_ffmpeg_preset}]{_ffmpeg_hw}")
if _ffmpeg_boot["error"]:
    print(f"           {_ffmpeg_boot['error']}")
print(f"------------------------------\n")


class ToolTip:
    def __init__(self, widget, text, delay=500, wraplength=320):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self._after_id = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._window or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        except Exception:
            return
        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self._window,
            text=self.text,
            justify=tk.LEFT,
            background="#1f2933",
            foreground="#ffffff",
            relief=tk.SOLID,
            borderwidth=1,
            padx=8,
            pady=6,
            wraplength=self.wraplength,
            font=("Meiryo", 9),
        )
        label.pack()

    def _hide(self, _event=None):
        self._cancel()
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None


class YMM4AutoGui:
    def __init__(self, root):
        self.root = root
        self.app_version = build_app_version()
        self.root.title(f"YMM4 Auto Video Factory v{self.app_version}")
        self.root.geometry("920x780")
        self.root.minsize(800, 620)
        self.root.configure(bg="#f5f7fa")

        # アプリアイコン（ずんだもん）
        try:
            from PIL import Image as _PilImage, ImageTk as _ImageTk
            _icon_path = os.path.join(os.path.dirname(__file__), "assets", "characters", "zundamon.png")
            if os.path.exists(_icon_path):
                with _PilImage.open(_icon_path) as _icon_src:
                    _icon_img = _icon_src.resize((64, 64), _PilImage.LANCZOS)
                self._app_icon = _ImageTk.PhotoImage(_icon_img)
                self.root.iconphoto(True, self._app_icon)
        except Exception:
            pass

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#f5f7fa")
        style.configure("TLabel", font=("Meiryo", 9), background="#f5f7fa")
        style.configure("Header.TLabel", font=("Meiryo", 13, "bold"), foreground="#2d3436")
        style.configure("TButton", font=("Meiryo", 9, "bold"), padding=4)
        style.configure("Accent.TButton", foreground="white", background="#0984e3")
        style.map("Accent.TButton", background=[('active', '#0773c5')])

        main_frame = ttk.Frame(root, padding="12")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header + script controls in one row
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 4))
        self.generate_btn = ttk.Button(top_frame, text="🎬 生成 🚀", style="Accent.TButton", command=self.start_generation)
        self.generate_btn.pack(side=tk.RIGHT, padx=(4, 0), ipady=4)
        self._add_tooltip(self.generate_btn, "貼り付けた台本から音声・背景・サムネ・YMM4プロジェクトを生成します。")
        self.cancel_btn = ttk.Button(top_frame, text="作業中止", command=self.request_cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._add_tooltip(self.cancel_btn, "実行中の生成処理に中止リクエストを送ります。")
        self.llm_check_btn = ttk.Button(top_frame, text="LLM/尺チェック", command=self.start_bulk_llm_check)
        self.llm_check_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._add_tooltip(self.llm_check_btn, "履歴の台本をまとめて冒頭品質・推定尺・最終品質レビューします。")
        script_prompt_btn = ttk.Button(top_frame, text="AI台本作成", command=self.copy_script_generation_prompt)
        script_prompt_btn.pack(side=tk.RIGHT)
        self._add_tooltip(script_prompt_btn, "既存タイトル重複を避ける台本生成プロンプトをクリップボードにコピーします。")
        title_prompt_btn = ttk.Button(top_frame, text="Shortsタイトル案", width=16, command=self.copy_title_prompt)
        title_prompt_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._add_tooltip(title_prompt_btn, "Shorts寄りの通常タイトル案プロンプトをコピーします。Longも混ざる場合があります。")
        long_title_prompt_btn = ttk.Button(top_frame, text="Longタイトル案", width=14, command=self.copy_long_title_prompt)
        long_title_prompt_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._add_tooltip(long_title_prompt_btn, "Long候補だけを出すタイトル案プロンプトをコピーします。3幕構成と実績横展開を重視します。")
        clear_btn = ttk.Button(top_frame, text="クリア", width=6, command=self.clear_script)
        clear_btn.pack(side=tk.RIGHT, padx=4)
        self._add_tooltip(clear_btn, "台本入力欄を空にします。")

        # Script area
        self.ref_text = scrolledtext.ScrolledText(main_frame, height=6, font=("Consolas", 10), bg="#fdfdfd", borderwidth=1, relief="solid", highlightthickness=1, highlightbackground="#dfe6e9", highlightcolor="#0984e3")
        self.ref_text.pack(fill=tk.X, expand=False, pady=(0, 4))

        # Options row (all in one line)
        opt_frame = ttk.Frame(main_frame)
        opt_frame.pack(fill=tk.X, pady=2)


        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="デバッグ", variable=self.debug_var).pack(side=tk.LEFT, padx=4)

        self.reuse_bg_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="背景再利用", variable=self.reuse_bg_var).pack(side=tk.LEFT, padx=4)

        self.batch_api_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="Batch API", variable=self.batch_api_var).pack(side=tk.LEFT, padx=4)

        self.long_thumbnail_ab_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="LongサムネAB", variable=self.long_thumbnail_ab_var).pack(side=tk.LEFT, padx=4)
        self.long_budget_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="Long節約", variable=self.long_budget_var).pack(side=tk.LEFT, padx=4)
        self.sd_size_var = tk.BooleanVar(value=False)
        sd_cb = ttk.Checkbutton(opt_frame, text="SD生成", variable=self.sd_size_var)
        sd_cb.pack(side=tk.LEFT, padx=4)
        self._add_tooltip(sd_cb, f"画像を縮小サイズ(×{SD_SIZE_IMAGE_SCALE})で生成して拡大セット。API負荷・コスト削減。デフォルトOFF。")

        ttk.Label(opt_frame, text="画風:").pack(side=tk.LEFT, padx=(12, 2))
        self.style_var = tk.StringVar(value="nanobanana2")
        self.style_combo = ttk.Combobox(opt_frame, textvariable=self.style_var, values=["nanobanana2", "nanobanana pro"], state="readonly", width=14)
        self.style_combo.pack(side=tk.LEFT, padx=2)

        self.history_batch_btn = ttk.Button(opt_frame, text="履歴から複数生成", command=self.open_history_batch_dialog)
        self.history_batch_btn.pack(side=tk.LEFT, padx=(10, 0))
        self._add_tooltip(self.history_batch_btn, "過去の生成履歴を複数選び、同じ設定でまとめて再生成します。")

        # Sub buttons row
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 4))
        self.upload_btn = ttk.Button(btn_frame, text="📤 YouTubeアップ", command=self.start_youtube_upload)
        self.upload_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._add_tooltip(self.upload_btn, "生成済み動画を選び、予約枠を確認してYouTubeへアップロードします。")
        self.comment_btn = ttk.Button(btn_frame, text="💬 固定コメント", command=self.start_post_fixed_comments)
        self.comment_btn.pack(side=tk.LEFT, padx=(4, 4))
        self._add_tooltip(self.comment_btn, "アップロード済み履歴のscript.txtにある固定コメントを、既存動画へ投稿します。")
        self.open_folder_btn = ttk.Button(btn_frame, text="📁 出力フォルダを開く", command=self.open_output_dir)
        self.open_folder_btn.pack(side=tk.LEFT)
        self._add_tooltip(self.open_folder_btn, "生成物が保存される output フォルダを開きます。")
        self.image_review_btn = ttk.Button(btn_frame, text="🔄 画像確認", command=self.start_image_review)
        self.image_review_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._add_tooltip(self.image_review_btn, "サムネイル・背景画像を確認し、選んだ画像だけ再生成できます。")
        self._studio_url = None
        self.studio_btn = ttk.Button(btn_frame, text="🌐 YouTube Studio", command=self._open_studio)
        self.studio_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._add_tooltip(self.studio_btn, "ブラウザでYouTube Studioを開きます。")
        self.schedule_btn = ttk.Button(btn_frame, text="📅 スケジュール", command=self.show_upload_schedule_dialog)
        self.schedule_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._add_tooltip(self.schedule_btn, "予約済み・手動公開済みのアップロード予定を一覧確認します。")
        self.analytics_btn = ttk.Button(btn_frame, text="📊 アナリティクス", command=self.open_analytics_window)
        self.analytics_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._add_tooltip(self.analytics_btn, "YouTube Analyticsを取得し、横展開候補や改善対象を評価します。")

        test_btn_frame = ttk.Frame(main_frame)
        test_btn_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(test_btn_frame, text="test:").pack(side=tk.LEFT, padx=(0, 6))
        self.native_generate_btn = ttk.Button(test_btn_frame, text="YMMなし生成(test)", command=self.start_native_generation)
        self.native_generate_btn.pack(side=tk.LEFT, padx=(0, 4), ipady=2)
        self._add_tooltip(self.native_generate_btn, "貼り付けた台本から素材を生成し、YMM4を使わずffmpegで簡易MP4を出力します。")
        self.native_render_history_btn = ttk.Button(test_btn_frame, text="YMMなしMP4化(test)", command=self.start_native_render_from_history)
        self.native_render_history_btn.pack(side=tk.LEFT, padx=(4, 0), ipady=2)
        self._add_tooltip(self.native_render_history_btn, "既存履歴の音声・背景を使い、ffmpegのYMMなしMP4出力だけを実行します。")
        # Status + progress
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(main_frame, textvariable=self.status_var, font=("Meiryo", 8, "italic"), width=110)
        self.status_label.pack(anchor=tk.W, fill=tk.X)
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill=tk.X, pady=(2, 4))

        # Log（最下部・残りスペースを埋める）
        log_header = ttk.Frame(main_frame)
        log_header.pack(anchor=tk.W, fill=tk.X)
        ttk.Label(log_header, text="実行ログ:").pack(side=tk.LEFT)
        self.batch_progress_var = tk.StringVar(value="")
        ttk.Label(
            log_header,
            textvariable=self.batch_progress_var,
            font=("Meiryo", 9, "bold"),
            foreground="#ef57ff",
        ).pack(side=tk.LEFT, padx=(10, 0))
        self.log_area = scrolledtext.ScrolledText(main_frame, height=6, font=("Meiryo", 9), bg="#1e272e", fg="#d2dae2")
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.log_area.tag_config("info", foreground="#00d8d6")
        self.log_area.tag_config("error", foreground="#ff5e57")
        self.log_area.tag_config("success", foreground="#05c46b")
        self.log_area.tag_config("warning", foreground="#ffa502", font=("Meiryo", 9, "bold"))
        self.log_area.tag_config("batch", foreground="#ef57ff", font=("Meiryo", 9, "bold"))
        self.log_area.tag_config("score", foreground="#ffffff", background="#b33939", font=("Meiryo", 12, "bold"))
        self.log_area.tag_config("score_ok", foreground="#ffffff", background="#218c74", font=("Meiryo", 12, "bold"))
        self.log_area.tag_config("score_warn", foreground="#111111", background="#ffda79", font=("Meiryo", 12, "bold"))
        self.log_area.tag_config("duration", foreground="#34ace0", font=("Meiryo", 11, "bold"))

        self.last_output_dir = None
        self.cancel_event = threading.Event()
        self._gen_id = 0
        self._log_queue = queue.Queue()
        self._schedule_sync_running = False

        self.refresh_history()
        self._migrate_upload_records_once()
        self.root.after(80, self._drain_log_queue)
        threading.Thread(target=self.check_engines_startup, args=(self.debug_var.get(),), daemon=True).start()

    def _add_tooltip(self, widget, text):
        tooltip = ToolTip(widget, text)
        widget._tooltip = tooltip
        return widget

    def _migrate_upload_records_once(self):
        pass  # central upload_records.json abolished

    def _set_batch_progress_text(self, text):
        self.root.after(0, lambda t=text: self.batch_progress_var.set(t))

    def check_engines_startup(self, debug_mode=False):
        self.log("--- システム接続確認 ---")
        ai = AIGenerator(debug=debug_mode)
        g_status = "接続OK (Gemini / Nano Banana)" if ai.client else "未設定 (configを確認してください)"
        self.log(f"Google AI : {g_status}", "info" if ai.client else "error")

        for n, u, p in [("VOICEVOX", VOICEVOX_URL, VOICEVOX_PATH)]:
            res = unified_check(n, u, p)
            status = "OK" if res['connected'] else "ERR"
            style = "success" if res['connected'] else "error"
            self.log(f"{res['name']:<10}: {status} ({res['url']})", style)
        ffmpeg_status = ffmpeg_native_status()
        preset_text = f" / preset {ffmpeg_status['preset']}" if ffmpeg_status["preset"] else ""
        if ffmpeg_status["available"]:
            mode = "GPU" if ffmpeg_status["gpu"] else "CPU"
            hw_text = f" / HW: {', '.join(ffmpeg_status['hw_encoders'][:4])}" if ffmpeg_status["hw_encoders"] else ""
            self.log(
                f"ffmpeg   : OK ({mode}: {ffmpeg_status['configured']}{preset_text}){hw_text}",
                "success" if ffmpeg_status["gpu"] else "info",
            )
            if ffmpeg_status["gpu"]:
                self.log("           GPU失敗時は libx264(CPU) に自動フォールバック", "info")
        else:
            err = f" / {ffmpeg_status['error']}" if ffmpeg_status["error"] else ""
            self.log(
                f"ffmpeg   : ERR ({ffmpeg_status['bin']} / encoder {ffmpeg_status['configured']} が利用不可{err})",
                "error",
            )
        self.log("----------------------")

    def copy_script_generation_prompt(self):
        active, uploaded = self.collect_existing_titles()
        all_titles = active + uploaded
        food_titles = [t for t in all_titles if self._is_food_title(t)]
        prompt = build_script_generation_prompt(food_titles)
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.root.update()
        self.log(f"AI台本生成プロンプトをクリップボードにコピーしました（既存タイトル{len(food_titles)}件）✅", "success")

    def copy_title_prompt(self, long_only=False):
        active, uploaded = self.collect_existing_titles()
        all_titles = active + uploaded
        food_titles = [title for title in all_titles if self._is_food_title(title)]
        analytics_tsv, analytics_path, analytics_count = self._read_latest_analytics_tsv()
        summary = self._read_latest_analytics_summary()
        if analytics_tsv and summary:
            analytics_tsv = f"{summary}\n\n【動画別TSV】\n{analytics_tsv}"
        title_prompt = build_title_prompt(food_titles, analytics_tsv=analytics_tsv)
        if long_only:
            title_prompt += "\n\n今回の生成条件:\n・ロング候補として20案を出す\n・Shorts候補は出さない\n・すべてLong候補の出力形式を使う\n・Long TOP5を出す\n"
        self.root.clipboard_clear()
        self.root.clipboard_append(title_prompt)
        self.root.update()
        analytics_msg = f" / 実績データ{analytics_count}件" if analytics_tsv else " / 実績データなし"
        if analytics_path:
            analytics_msg += f" ({os.path.basename(analytics_path)})"
        label = "Longタイトル案" if long_only else "動画タイトル作成"
        self.log(f"{label}プロンプトをコピーしました（食べ物系既存タイトル{len(food_titles)}件 / 全{len(all_titles)}件{analytics_msg}）✅", "success")

    def copy_long_title_prompt(self):
        self.copy_title_prompt(long_only=True)

    @staticmethod
    def _read_latest_analytics_items():
        paths = analytics_paths(".json")
        if not paths:
            return [], None
        latest = max(paths, key=lambda path: os.path.getmtime(path))
        try:
            with open(latest, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return [], latest
        meta = {
            "generated_at": data.get("generated_at"),
            "days": data.get("days"),
            "start_date": data.get("start_date") or (data.get("summary") or {}).get("start_date"),
            "end_date": data.get("end_date") or (data.get("summary") or {}).get("end_date"),
        }
        return data.get("items") or [], latest, meta

    def _read_latest_analytics_summary(self):
        items, _path, meta = self._read_latest_analytics_items()
        return build_performance_summary(items, meta=meta) if items else ""

    @staticmethod
    def _read_latest_analytics_tsv(max_rows=80):
        paths = analytics_paths(".tsv")
        if not paths:
            return "", None, 0
        latest = max(paths, key=lambda path: os.path.getmtime(path))
        try:
            with open(latest, "r", encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f if line.strip()]
        except OSError:
            return "", latest, 0
        if not lines:
            return "", latest, 0
        header, rows = lines[0], lines[1:max_rows + 1]
        return "\n".join([header] + rows), latest, len(rows)

    def clear_script(self):
        self.ref_text.delete("1.0", tk.END)
        self.log("台本をクリアしました")

    def request_cancel(self):
        self.cancel_event.set()
        self.cancel_btn.config(state=tk.DISABLED)
        self.progress.stop()
        self.status_var.set("Canceled")
        self._toggle_ui(True)
        self.log("⏹ 作業中止しました。進行中の外部API呼び出しが戻り次第、結果を破棄します。", "error")

    def log(self, message, tag="info"):
        self._log_queue.put((str(message), tag))

    @staticmethod
    def _compact_log_message(message, limit=6000):
        if len(message) <= limit:
            return message
        head = message[: limit // 2]
        tail = message[-limit // 2 :]
        omitted = len(message) - len(head) - len(tail)
        return f"{head}\n...（ログ表示を短縮: {omitted}文字省略）...\n{tail}"

    def _drain_log_queue(self):
        processed = 0
        last_message = None
        try:
            while processed < 60:
                message, tag = self._log_queue.get_nowait()
                display_message = self._compact_log_message(message)
                self._append_log_line(display_message, tag)
                last_message = message
                processed += 1
        except queue.Empty:
            pass

        if last_message is not None:
            self._trim_log_area()
            self.status_var.set(last_message[:300])
            self.log_area.see(tk.END)

        delay = 20 if processed == 60 else 80
        self.root.after(delay, self._drain_log_queue)

    def _append_log_line(self, message, tag):
        self.log_area.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n", tag)

    def _trim_log_area(self, max_lines=500, keep_lines=420):
        line_count = int(self.log_area.index("end-1c").split(".")[0])
        if line_count > max_lines:
            delete_to = max(1, line_count - keep_lines)
            self.log_area.delete("1.0", f"{delete_to}.0")

    def _log_ui(self, message, tag, update_status=True):
        display_message = self._compact_log_message(message)
        self._append_log_line(display_message, tag)
        self._trim_log_area()
        if update_status:
            self.log_area.see(tk.END)
            status_text = str(message).splitlines()[0].strip()
            if len(status_text) > 90:
                status_text = status_text[:87] + "..."
            self.status_var.set(status_text)

    def _run_on_ui_sync(self, func):
        if threading.current_thread() is threading.main_thread():
            return func()

        done = threading.Event()
        result = {}

        def wrapper():
            try:
                result["value"] = func()
            except BaseException as e:
                result["error"] = e
            finally:
                done.set()

        self.root.after(0, wrapper)
        done.wait()
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _generation_settings(self):
        return {
            "debug_mode": self.debug_var.get(),
            "image_style": self.style_var.get(),
            "reuse_backgrounds": self.reuse_bg_var.get(),
            "use_batch_api": self.batch_api_var.get(),
            "long_thumbnail_ab_test": self.long_thumbnail_ab_var.get(),
            "long_budget_mode": self.long_budget_var.get(),
            "sd_size_mode": self.sd_size_var.get(),
            "native_render": False,
        }

    def refresh_history(self):
        if not os.path.exists("output"): os.makedirs("output", exist_ok=True)
        history = [
            d for d in os.listdir("output")
            if os.path.isdir(os.path.join("output", d)) and not d.startswith("000_")
        ]
        history.sort(key=lambda d: os.path.getmtime(os.path.join("output", d)), reverse=True)
        self.history_items = history

    def _folder_name_to_title(self, name):
        for prefix in ("[Shorts]", "[Long]", "[SHORT]", "[LONG]"):
            if name.startswith(prefix):
                return name[len(prefix):].strip()
        return name

    @staticmethod
    def _strip_video_type_prefix(title):
        title = str(title or "").strip()
        for prefix in ("[Shorts]", "[Long]", "[SHORT]", "[LONG]"):
            if title.startswith(prefix):
                return title[len(prefix):].strip()
        return title

    @staticmethod
    def _preferred_long_thumbnail(output_dir):
        candidates = [
            os.path.join(output_dir, "thumbnail.png"),
            os.path.join(output_dir, "thumbnails", "thumbnail.png"),
        ]
        existing = [path for path in candidates if os.path.exists(path)]
        if not existing:
            return candidates[1]
        existing.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        return existing[0]

    def _collect_titles_from_folder(self, folder, exclude_uploaded=False):
        """フォルダ内のサブディレクトリ名からタイトルを収集（存在しない場合は空リスト）。"""
        if not os.path.isdir(folder):
            return []
        names = sorted(
            (
                d for d in os.listdir(folder)
                if os.path.isdir(os.path.join(folder, d))
                and not (exclude_uploaded and d in {"000_uploaded", "000_backups"})
            ),
            key=lambda d: os.path.getmtime(os.path.join(folder, d)),
            reverse=True,
        )
        return [self._folder_name_to_title(name) for name in names]

    def _is_food_title(self, title):
        non_food_keywords = (
            "鬼滅", "ワンピ", "呪術", "スカッと", "こめお", "大喧嘩", "喧嘩", "激論",
            "アニメ", "漫画", "伏線", "考察"
        )
        if any(keyword in title for keyword in non_food_keywords):
            return False
        food_keywords = (
            "食", "飲", "料理", "飯", "味", "お菓子", "菓子", "野菜", "肉", "魚", "寿司", "外食",
            "保存食", "発酵", "調味料", "薬", "毒扱い", "無毒", "給料",
            "人参", "にんじん", "ハチミツ", "蜂蜜", "タピオカ", "フグ", "ふぐ",
            "クロワッサン", "かき氷", "シロップ", "カレー", "コンニャク", "こんにゃく",
            "メロンパン", "マック", "ポテト", "ケチャップ", "トマト", "サーモン",
            "鮭", "ロブスター", "オマール海老", "コーラ", "コカ・コーラ", "ポップコーン",
            "チョコ", "チョコレート", "塩", "フライドポテト", "ポテトフライ",
            "ポテチ", "ポテトチップス",
            "オレンジ", "ミイラ", "カエル", "海のゴキブリ"
        )
        return any(keyword in title for keyword in food_keywords)

    def collect_existing_titles(self):
        self.refresh_history()
        active = self._collect_titles_from_folder("output", exclude_uploaded=True)

        # 投稿済み: ログファイル（フォルダが消えても残る）＋現存フォルダをマージ
        log_path = migrate_root_file("uploaded_titles.txt", os.path.dirname(UPLOADED_TITLES_FILE))
        logged_names = []
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as lf:
                logged_names = [l.strip() for l in lf if l.strip()]
        uploaded_dir = os.path.join("output", "000_uploaded")
        folder_names = []
        if os.path.isdir(uploaded_dir):
            folder_names = sorted(
                (d for d in os.listdir(uploaded_dir) if os.path.isdir(os.path.join(uploaded_dir, d))),
                key=lambda d: os.path.getmtime(os.path.join(uploaded_dir, d)),
                reverse=True,
            )
        # ログ優先（順序保持）、フォルダにあってログにないものを末尾に追加
        seen = set(logged_names)
        merged_names = list(logged_names)
        for n in folder_names:
            if n not in seen:
                merged_names.append(n)
        uploaded = [self._folder_name_to_title(n) for n in merged_names]
        return active, uploaded

    def _append_uploaded_titles(self, titles):
        ensure_output_dirs()
        log_path = migrate_root_file("uploaded_titles.txt", os.path.dirname(UPLOADED_TITLES_FILE))
        existing = set()
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as lf:
                existing = {line.strip() for line in lf if line.strip()}

        added = 0
        with open(log_path, "a", encoding="utf-8", newline="\n") as lf:
            for title in titles:
                title = str(title).strip()
                if not title or title in existing:
                    continue
                existing.add(title)
                lf.write(title + "\n")
                added += 1
        return added

    def open_history_batch_dialog(self):
        self.refresh_history()
        histories = [
            name for name in getattr(self, "history_items", [])
            if os.path.exists(os.path.join("output", name, "script.txt"))
        ]
        if not histories:
            messagebox.showinfo("履歴なし", "実行できる履歴がありません。")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("履歴を複数選択")
        dialog.geometry("520x420")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="生成する履歴を選択してください（Ctrl / Shift で複数選択）").pack(anchor=tk.W, padx=10, pady=(10, 4))

        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        history_list = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
            font=("Meiryo", 9),
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=history_list.yview)
        history_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for name in histories:
            script_path = os.path.join("output", name, "script.txt")
            output_dir = os.path.join("output", name)
            try:
                edited_at = time.strftime("%Y/%m/%d %H:%M", time.localtime(os.path.getmtime(output_dir)))
            except OSError:
                edited_at = "----/--/-- --:--"
            suffix = "" if os.path.exists(script_path) else "  (script.txtなし)"
            display_name = self._folder_name_to_title(name)
            history_list.insert(tk.END, f"{edited_at}  {display_name}{suffix}")

        def run_selected():
            indices = list(history_list.curselection())
            if not indices:
                messagebox.showwarning("未選択", "履歴を1つ以上選択してください。", parent=dialog)
                return
            selected = [histories[i] for i in indices]
            dialog.destroy()
            self.start_generation_from_histories(selected)

        btns = ttk.Frame(dialog)
        btns.pack(fill=tk.X, padx=10, pady=(4, 10))
        ttk.Button(btns, text="キャンセル", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="選択した履歴を生成", style="Accent.TButton", command=run_selected).pack(side=tk.RIGHT, padx=(0, 8))

    def start_generation_from_histories(self, history_names):
        scripts = []
        missing = []
        for name in history_names:
            script_path = os.path.join("output", name, "script.txt")
            if not os.path.exists(script_path):
                missing.append(name)
                continue
            with open(script_path, "r", encoding="utf-8") as f:
                script = f.read().strip()
            if script:
                scripts.append(script)

        if missing:
            self.log(f"⚠ script.txtなしの履歴をスキップ: {len(missing)}件", "error")
        if not scripts:
            messagebox.showwarning("Error", "実行できる履歴台本がありません。")
            return

        self._toggle_ui(False)
        self.cancel_event = threading.Event()
        self._gen_id += 1

        abort = False
        for i, script in enumerate(scripts, 1):
            prefix = f"[台本{i}] " if len(scripts) > 1 else ""
            items = ScriptParser.parse_string(script)
            is_valid, messages = ScriptParser.validate(items)
            for m in messages:
                if not m.startswith("⚠"):
                    self.log(f"❌ {prefix}{m}", "error")
                    abort = True
            is_shorts = any(it.get("text", "").strip() == "Shorts" for it in items if it["type"] == "video_format")
            errs, warns = self._pre_generate_check(items, is_shorts)
            for e in errs:
                self.log(f"❌ {prefix}{e}", "error")
                abort = True
            for w in warns:
                self.log(f"⚠ {prefix}{w}", "warning")
            est, n, avg = self._estimate_duration(items, is_shorts)
            if est is not None:
                if is_shorts:
                    if est < 35:
                        verdict, tag = "⚠ 短すぎ", "warning"
                    elif est < 38:
                        verdict, tag = "✅ やや短い", "success"
                    elif est <= 50:
                        verdict, tag = "✅ 理想", "success"
                    elif est <= 55:
                        verdict, tag = "⚠ OKだけど長め", "warning"
                    elif est <= 58:
                        verdict, tag = "⚠ 長め", "warning"
                    else:
                        verdict, tag = "🚨 長すぎ", "warning"
                    self.log(f"{prefix}📏 Shorts推定尺: {est:.0f}秒 {verdict}  （{n}行 / 平均{avg:.1f}文字）", tag)
                else:
                    m, s = divmod(int(est), 60)
                    self.log(f"{prefix}📏 Long推定尺: {m}分{s}秒  （{n}行 / 平均{avg:.1f}文字）", "duration")

        if abort:
            self.log("❌ エラーがあるため処理を中止しました", "error")
            self._toggle_ui(True)
            return

        self.log("⚠ 問題がある場合は「作業中止」ボタンで止めてください", "warning")
        self.log(f"履歴一括処理開始: 合計 {len(scripts)} 件", "batch")
        threading.Thread(target=self._run_batch, args=(scripts, self._generation_settings(), self.cancel_event), daemon=True).start()

    def _mp4_candidates_in_dir(self, output_dir):
        if not os.path.isdir(output_dir):
            return []
        candidates = [
            os.path.join(output_dir, f)
            for f in os.listdir(output_dir)
            if f.lower().endswith(".mp4")
        ]
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates

    def _external_mp4_candidate(self, output_dir):
        search_dir = self._DOCUMENTS_SEARCH_DIR
        if not os.path.isdir(search_dir) or not os.path.isdir(output_dir):
            return None
        ymmp_stems = [
            os.path.splitext(f)[0]
            for f in os.listdir(output_dir)
            if f.lower().endswith(".ymmp")
        ]
        for stem in ymmp_stems:
            src = os.path.join(search_dir, stem + ".mp4")
            if os.path.exists(src):
                return src
        return None

    def _has_uploadable_mp4(self, output_dir):
        return bool(self._mp4_candidates_in_dir(output_dir) or self._external_mp4_candidate(output_dir))

    def select_history_dialog(self, title, action_text, multi=False, require_script=False, require_mp4=False):
        self.refresh_history()
        histories = getattr(self, "history_items", [])
        if require_script:
            histories = [
                name for name in histories
                if os.path.exists(os.path.join("output", name, "script.txt"))
            ]
        if require_mp4:
            histories = [
                name for name in histories
                if self._has_uploadable_mp4(os.path.join("output", name))
            ]
        if not histories:
            msg = "アップロード可能なMP4がある履歴がありません。" if require_mp4 else "選択できる履歴がありません。"
            messagebox.showinfo("履歴なし", msg)
            return []

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("560x420")
        dialog.transient(self.root)
        dialog.grab_set()

        select_text = "Ctrl / Shift で複数選択" if multi else "1件選択"
        ttk.Label(dialog, text=f"履歴を選択してください（{select_text}）").pack(anchor=tk.W, padx=10, pady=(10, 4))

        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        history_list = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED if multi else tk.BROWSE,
            exportselection=False,
            font=("Meiryo", 9),
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=history_list.yview)
        history_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for name in histories:
            output_dir = os.path.join("output", name)
            try:
                edited_at = time.strftime("%Y/%m/%d %H:%M", time.localtime(os.path.getmtime(output_dir)))
            except OSError:
                edited_at = "----/--/-- --:--"
            script_suffix = "" if os.path.exists(os.path.join(output_dir, "script.txt")) else "  (script.txtなし)"
            image_suffix = "" if (
                os.path.exists(os.path.join(output_dir, "thumbnails", "thumbnail.png"))
                or os.path.isdir(os.path.join(output_dir, "backgrounds"))
            ) else "  (画像なし)"
            mp4_suffix = "" if self._has_uploadable_mp4(output_dir) else "  (MP4なし)"
            display_name = self._folder_name_to_title(name)
            history_list.insert(tk.END, f"{edited_at}  {display_name}{script_suffix}{image_suffix}{mp4_suffix}")

        result = {"selected": []}

        def run_selected():
            indices = list(history_list.curselection())
            if not indices:
                messagebox.showwarning("未選択", "履歴を選択してください。", parent=dialog)
                return
            result["selected"] = [histories[i] for i in indices]
            dialog.destroy()

        btns = ttk.Frame(dialog)
        btns.pack(fill=tk.X, padx=10, pady=(4, 10))
        ttk.Button(btns, text="キャンセル", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text=action_text, style="Accent.TButton", command=run_selected).pack(side=tk.RIGHT, padx=(0, 8))

        self.root.wait_window(dialog)
        return result["selected"]

    @staticmethod
    def _pre_generate_check(items, is_shorts):
        """生成前危険チェック。(errors, warnings) のリストを返す。"""
        errors = []
        warnings = []
        meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
        dialogue_items = [it for it in items if it["type"] == "dialogue"]
        bg_items = [it for it in items if it["type"] == "background"]
        try:
            from core.cta_policy import check_shorts_navigation_ng

            script_text = "\n".join(it.get("text", "") for it in dialogue_items)
            hits = check_shorts_navigation_ng(script_text, "Shorts" if is_shorts else "Long")
            if hits:
                warnings.append(
                    "Shortsでは直接的な他動画誘導・次回予告が含まれています。"
                    f"ループ締めに変更してください: {', '.join(hits)}"
                )
        except Exception:
            pass

        if not meta.get("video_title"):
            errors.append("video_titleがありません")

        thumb_text = meta.get("thumbnail_text", "")
        if thumb_text and len(thumb_text) > 15:
            warnings.append(f"サムネイル文字が長い（{len(thumb_text)}文字）: 「{thumb_text[:20]}」")

        min_bg = 4 if is_shorts else 3
        if len(bg_items) < min_bg:
            warnings.append(f"背景数が少ない（{len(bg_items)}箇所、推奨{min_bg}以上）")

        if dialogue_items:
            first_text = dialogue_items[0].get("text", "")
            if len(first_text) < 8:
                warnings.append(f"冒頭セリフが短すぎます（{len(first_text)}文字）: 「{first_text}」")
            if is_shorts:
                from config import (
                    NATIVE_SHORTS_AVG_CHARS_MIN,
                    NATIVE_SHORTS_CHARS_MUST_FIX_MIN,
                    NATIVE_SHORTS_LINES_IDEAL_MAX,
                    NATIVE_SHORTS_LINES_IDEAL_MIN,
                    NATIVE_SHORTS_LINES_MUST_FIX,
                    NATIVE_SHORTS_LINES_TARGET_MAX,
                    NATIVE_SHORTS_LINES_TARGET_MIN,
                    NATIVE_SHORTS_SHORT_LINE_MAX,
                    NATIVE_SHORTS_TARGET_CHARS_MIN,
                )

                dialogue_count = len(dialogue_items)
                total_dialogue_chars = sum(len(it.get("text", "")) for it in dialogue_items)
                avg_dialogue_chars = total_dialogue_chars / dialogue_count if dialogue_count else 0.0
                if dialogue_count < NATIVE_SHORTS_LINES_IDEAL_MIN:
                    errors.append(
                        f"Shorts台本量不足（{dialogue_count}行 / 理想{NATIVE_SHORTS_LINES_IDEAL_MIN}行以上）"
                    )
                if dialogue_count >= NATIVE_SHORTS_LINES_MUST_FIX:
                    errors.append(f"Shortsセリフ数過多（{dialogue_count}行 / 31行以上は禁止）")
                if total_dialogue_chars < NATIVE_SHORTS_CHARS_MUST_FIX_MIN:
                    missing = NATIVE_SHORTS_TARGET_CHARS_MIN - total_dialogue_chars
                    errors.append(
                        f"Shorts本文文字数不足（セリフ本文{total_dialogue_chars}文字 / 最低{NATIVE_SHORTS_CHARS_MUST_FIX_MIN}文字以上）"
                        f"。目標{NATIVE_SHORTS_TARGET_CHARS_MIN}文字まであと{missing}文字"
                    )
                if avg_dialogue_chars < NATIVE_SHORTS_AVG_CHARS_MIN:
                    errors.append(
                        f"Shorts平均文字数不足（平均{avg_dialogue_chars:.1f}文字 / 必須{NATIVE_SHORTS_AVG_CHARS_MIN:.1f}文字以上）"
                    )
                short_line_count = sum(1 for it in dialogue_items if len(it.get("text", "")) <= 10)
                very_short_line_count = sum(1 for it in dialogue_items if len(it.get("text", "")) <= 7)
                if short_line_count > NATIVE_SHORTS_SHORT_LINE_MAX:
                    errors.append(
                        f"Shorts短文セリフ過多（10文字以下が{short_line_count}行 / 最大{NATIVE_SHORTS_SHORT_LINE_MAX}行）"
                    )
                if very_short_line_count:
                    warnings.append(f"7文字以下の短文セリフがあります（{very_short_line_count}行）。原則11〜15文字に伸ばしてください")
                if NATIVE_SHORTS_LINES_IDEAL_MIN <= dialogue_count <= NATIVE_SHORTS_LINES_IDEAL_MAX and not (
                    NATIVE_SHORTS_LINES_TARGET_MIN <= dialogue_count <= NATIVE_SHORTS_LINES_TARGET_MAX
                ):
                    warnings.append(
                        f"Shortsセリフ数は許容内ですが、安定目標は{NATIVE_SHORTS_LINES_TARGET_MIN}〜{NATIVE_SHORTS_LINES_TARGET_MAX}行です"
                    )

        return errors, warnings

    @staticmethod
    def _estimate_duration(items, is_shorts: bool):
        """推定尺（秒）を返す。Shorts: native速度(1.40x/1.25x)、Long: YMM4速度(1.6x/1.35x)。"""
        dialogue_items = [it for it in items if it["type"] == "dialogue"]
        if not dialogue_items:
            return None, 0, 0
        n = len(dialogue_items)
        total_chars = sum(len(it.get("text", "")) for it in dialogue_items)
        avg_chars = total_chars / n if n else 0

        from config import (
            NATIVE_SHORTS_INTRO_VOICE_SPEED, NATIVE_SHORTS_BODY_VOICE_SPEED,
            NATIVE_SHORTS_ESTIMATE_BASE_CPS, VOICE_INTRO_FAST_LINES,
        )

        elapsed = 0.0
        if is_shorts:
            for i, item in enumerate(dialogue_items):
                chars = len(item.get("text", ""))
                speed = NATIVE_SHORTS_INTRO_VOICE_SPEED if i < VOICE_INTRO_FAST_LINES else NATIVE_SHORTS_BODY_VOICE_SPEED
                elapsed += chars / (NATIVE_SHORTS_ESTIMATE_BASE_CPS * speed) + 0.1 * speed
        else:
            ADDITIONAL = 0.3 + 0.5 + 0.2
            for item in dialogue_items:
                chars = len(item.get("text", ""))
                speed = 1.6 if elapsed < 5.0 else 1.35
                elapsed += chars / (5.4 * speed) + 0.1 * speed + ADDITIONAL

        return elapsed, n, avg_chars

    @staticmethod
    def _duration_tag(status):
        if status in ("ideal", "ok", "ok_but_short"):
            return "success"
        if status in ("ok_but_long", "warning"):
            return "warning"
        return "error"

    def start_bulk_llm_check(self):
        raw_scripts = self.ref_text.get("1.0", tk.END).strip()
        scripts = split_input_scripts(raw_scripts)
        if not scripts:
            messagebox.showwarning("Error", "チェックする台本を入力してください")
            return
        self.llm_check_btn.config(state=tk.DISABLED)
        self.log(f"🤖 LLM/尺チェック開始: 合計 {len(scripts)} 件", "batch")
        threading.Thread(target=self._run_bulk_llm_check, args=(scripts,), daemon=True).start()

    def _run_bulk_llm_check(self, scripts):
        ok_count = 0
        warn_count = 0
        ng_count = 0
        ai_report = [
            "以下の台本チェック結果をもとに、全台本を出力してください。",
            "問題がある台本は修正し、問題がない台本は元の内容をそのまま出力してください。",
            "一部の台本だけではなく、修正不要の台本も含めて全本分を返してください。",
            "",
            "修正方針:",
            "- Shortsは38〜50秒を理想、35〜55秒を許容にする",
            "- 51〜55秒は長めなので、可能なら短くする",
            "- 冒頭スコアが低い台本は、冒頭1〜3セリフで食べ物名と意外性を強くする",
            "- 1セリフ15文字以内を守る",
            "- 台本全体の形式は元のフォーマットを維持する",
            "- 問題がない台本は書き換えず、そのまま再掲する",
            "- 出力は台本ごとに分け、元の順番を維持する",
            "",
            "チェック結果:",
        ]
        try:
            for idx, script in enumerate(scripts, 1):
                prefix = f"[台本{idx}] "
                try:
                    items = ScriptParser.parse_string(script)
                    is_valid, messages = ScriptParser.validate(items)
                    for m in messages:
                        tag = "warning" if str(m).startswith("⚠") else "error"
                        self.log(f"{prefix}{m}", tag)
                    if not is_valid:
                        ng_count += 1
                        continue

                    meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
                    body_items = normalize_background_order([it for it in items if it["type"] not in ScriptParser.META_TYPES])
                    video_format = meta.get("video_format", "")
                    is_shorts = video_format.strip().lower() in ("shorts", "short", "ショート")
                    title = meta.get("video_title", f"台本{idx}")
                    thumb_text = meta.get("thumbnail_text", "")
                    target_duration = "38-50秒" if is_shorts else "5-8分"
                    ai_report.append("")
                    ai_report.append(f"## 台本{idx}: {title}")
                    ai_report.append(f"- 動画形式: {'Shorts' if is_shorts else 'Long'}")
                    ai_report.append("")
                    ai_report.append("元台本:")
                    ai_report.append("```text")
                    ai_report.append(script.strip())
                    ai_report.append("```")

                    self.log(f"{prefix}🤖 Ollama冒頭レビュー中: {title}")
                    local = local_opening_review(body_items, title, thumb_text, is_shorts)
                    llm = None
                    try:
                        llm = llm_opening_review(
                            local,
                            title,
                            thumb_text,
                            "Shorts" if is_shorts else "Long",
                            target_duration,
                        )
                    except Exception as e:
                        self.log(f"{prefix}⚠ Ollamaレビュー失敗: {e}", "warning")

                    opening = llm or local
                    opening_score = int(opening.get("score") or 0)
                    opening_status = opening.get("status", "")
                    opening_critical_errors = opening.get("critical_errors") or []
                    opening_tag = opening_score_tag(opening_score, opening_critical_errors)
                    opening_model = opening.get("model")
                    opening_model_text = f" / model {opening_model or 'local-rule'}"
                    self.log(
                        f"{prefix}■■■ 冒頭LLMスコア {opening_score}点 / {opening_status}{opening_model_text} ■■■",
                        opening_tag,
                    )
                    ai_report.append(f"- 冒頭LLMスコア: {opening_score}点 / {opening_status}{opening_model_text}")
                    for issue in (opening.get("issues") or opening.get("warnings") or [])[:3]:
                        self.log(f"{prefix}  ・{issue}", "warning")
                        ai_report.append(f"  - {issue}")
                    for issue in opening_critical_errors[:3]:
                        self.log(f"{prefix}  must_fix: {issue}", "warning")
                        ai_report.append(f"  - must_fix: {issue}")

                    est, n, avg = self._estimate_duration(items, is_shorts)
                    duration_tag = "warning"
                    if est is not None:
                        dur = duration_review(est, is_shorts)
                        duration_status = dur.get("status", "unknown")
                        duration_status_text = duration_status_label(duration_status)
                        duration_tag = self._duration_tag(duration_status)
                        ai_report.append(f"- 推定尺: {est:.1f}秒 / {duration_status_text}")
                        ai_report.append(f"- セリフ数: {n}行 / 平均{avg:.1f}文字")
                        if is_shorts:
                            self.log(
                                f"{prefix}━━━━━━━━ 推定尺 {est:.1f}秒 / {duration_status_text} ━━━━━━━━ "
                                f"（{n}行 / 平均{avg:.1f}文字）",
                                duration_tag,
                            )
                        else:
                            m, s = divmod(int(est), 60)
                            self.log(
                                f"{prefix}━━━━━━━━ 推定尺 {m}分{s}秒 / {duration_status_text} ━━━━━━━━ "
                                f"（{n}行 / 平均{avg:.1f}文字）",
                                duration_tag,
                            )

                    if opening_tag == "score" or duration_tag == "error":
                        ng_count += 1
                        ai_report.append("- 判定: 要確認")
                    elif opening_tag == "score_warn" or duration_tag == "warning":
                        warn_count += 1
                        ai_report.append("- 判定: 警告")
                    else:
                        ok_count += 1
                        ai_report.append("- 判定: OK")
                except Exception as e:
                    ng_count += 1
                    self.log(f"{prefix}❌ チェック失敗: {e}", "error")
                    self.log(traceback.format_exc(), "error")
                    ai_report.append("")
                    ai_report.append(f"## 台本{idx}")
                    ai_report.append(f"- 判定: チェック失敗")
                    ai_report.append(f"- エラー: {e}")
            self.log(f"🤖 LLM/尺チェック完了: OK {ok_count} / 警告 {warn_count} / 要確認 {ng_count}", "batch")
            ai_report.append("")
            ai_report.append(f"総合: OK {ok_count} / 警告 {warn_count} / 要確認 {ng_count}")
            report_text = "\n".join(ai_report)
            self.root.after(0, lambda text=report_text: self._copy_bulk_check_report(text))
        finally:
            self.root.after(0, lambda: self.llm_check_btn.config(state=tk.NORMAL))

    def _copy_bulk_check_report(self, report_text):
        self.root.clipboard_clear()
        self.root.clipboard_append(report_text)
        self.root.update()
        self.log("📋 AI修正依頼用チェック結果をクリップボードにコピーしました", "success")

    def _run_generation_score_gate(self, scripts, cancel_event, native_render=None):
        ok_count = 0
        warn_count = 0
        ng_count = 0
        ai_report = [
            "生成前スコアリング結果です。要確認の台本がある場合は、生成前に修正してください。",
            "",
            "チェック結果:",
        ]
        total = len(scripts)
        self.log(f"🤖 生成前スコアリング開始: 合計 {total} 件", "batch")
        self._set_batch_progress_text(f"スコアリング: 0/{total} 完了")

        for idx, script in enumerate(scripts, 1):
            if cancel_event.is_set():
                ng_count += 1
                self.log("⏹ 生成前スコアリングを中止しました。", "error")
                self._set_batch_progress_text(f"スコアリング中止: {idx - 1}/{total} 完了")
                break

            prefix = f"[台本{idx}] "
            self._set_batch_progress_text(f"スコアリング中: {idx}/{total}")
            try:
                items = ScriptParser.parse_string(script)
                is_valid, messages = ScriptParser.validate(items)
                for m in messages:
                    tag = "warning" if str(m).startswith("⚠") else "error"
                    self.log(f"{prefix}{m}", tag)
                if not is_valid:
                    ng_count += 1
                    ai_report.extend(["", f"## 台本{idx}", "- 判定: 要確認", "- 理由: フォーマットエラー"])
                    self.root.after(0, lambda v=int((idx / max(total, 1)) * 20): self.progress.config(value=v))
                    self._set_batch_progress_text(f"スコアリング: {idx}/{total} 完了")
                    continue

                meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
                body_items = normalize_background_order([it for it in items if it["type"] not in ScriptParser.META_TYPES])
                video_format = meta.get("video_format", "")
                is_shorts = video_format.strip().lower() in ("shorts", "short", "ショート")
                title = meta.get("video_title", f"台本{idx}")
                thumb_text = meta.get("thumbnail_text", "")
                target_duration = "38-50秒" if is_shorts else "5-8分"

                ai_report.extend(["", f"## 台本{idx}: {title}", f"- 動画形式: {'Shorts' if is_shorts else 'Long'}"])
                self.log(f"{prefix}🤖 生成前Ollama冒頭レビュー中: {title}")
                # native_render=None → Shortsはdefault engine、Longは常にymm4
                _effective_native = native_render if native_render is not None else (is_shorts and DEFAULT_SHORTS_RENDER_ENGINE == "native")
                _render_engine = "native" if _effective_native else "ymm4"
                local = local_opening_review(body_items, title, thumb_text, is_shorts, render_engine=_render_engine)
                llm = llm_opening_review(
                    local,
                    title,
                    thumb_text,
                    "Shorts" if is_shorts else "Long",
                    target_duration,
                )
                opening = llm or local
                opening_score = int(opening.get("score") or 0)
                opening_status = opening.get("status", "")
                opening_critical_errors = opening.get("critical_errors") or []
                opening_model = opening.get("model")
                opening_model_text = f" / model {opening_model or 'local-rule'}"
                opening_tag = opening_score_tag(opening_score, opening_critical_errors)
                self.log(
                    f"{prefix}■■■ 生成前冒頭スコア {opening_score}点 / {opening_status}{opening_model_text} ■■■",
                    opening_tag,
                )
                ai_report.append(f"- 冒頭スコア: {opening_score}点 / {opening_status}{opening_model_text}")

                for issue in (opening.get("issues") or opening.get("warnings") or [])[:3]:
                    self.log(f"{prefix}  ・{issue}", "warning")
                    ai_report.append(f"  - {issue}")
                for issue in opening_critical_errors[:3]:
                    self.log(f"{prefix}  must_fix: {issue}", "warning")
                    ai_report.append(f"  - must_fix: {issue}")

                est, n, avg = self._estimate_duration(items, is_shorts)
                duration_tag = "warning"
                if est is not None:
                    dur = duration_review(est, is_shorts)
                    duration_status = dur.get("status", "unknown")
                    duration_status_text = duration_status_label(duration_status)
                    duration_tag = self._duration_tag(duration_status)
                    ai_report.append(f"- 推定尺: {est:.1f}秒 / {duration_status_text}")
                    ai_report.append(f"- セリフ数: {n}行 / 平均{avg:.1f}文字")
                    if is_shorts:
                        self.log(
                            f"{prefix}━━━━━━━━ 生成前推定尺 {est:.1f}秒 / {duration_status_text} ━━━━━━━━ "
                            f"（{n}行 / 平均{avg:.1f}文字）",
                            duration_tag,
                        )
                    else:
                        m, s = divmod(int(est), 60)
                        self.log(
                            f"{prefix}━━━━━━━━ 生成前推定尺 {m}分{s}秒 / {duration_status_text} ━━━━━━━━ "
                            f"（{n}行 / 平均{avg:.1f}文字）",
                            duration_tag,
                        )

                if opening.get("fallback_to_local"):
                    ng_count += 1
                    ai_report.append("- 判定: 要確認")
                    ai_report.append("- 理由: Ollamaレビュー失敗")
                elif opening_tag == "score" or duration_tag == "error":
                    ng_count += 1
                    ai_report.append("- 判定: 要確認")
                elif opening_tag == "score_warn" or duration_tag == "warning":
                    warn_count += 1
                    ai_report.append("- 判定: 警告")
                else:
                    ok_count += 1
                    ai_report.append("- 判定: OK")
            except Exception as e:
                ng_count += 1
                self.log(f"{prefix}❌ 生成前チェック失敗: {e}", "error")
                self.log(traceback.format_exc(), "error")
                ai_report.extend(["", f"## 台本{idx}", "- 判定: チェック失敗", f"- エラー: {e}"])

            self.root.after(0, lambda v=int((idx / max(total, 1)) * 20): self.progress.config(value=v))
            self._set_batch_progress_text(f"スコアリング: {idx}/{total} 完了")

        self.log(f"🤖 生成前スコアリング完了: OK {ok_count} / 警告 {warn_count} / 要確認 {ng_count}", "batch")
        self._set_batch_progress_text(f"スコアリング完了: {ok_count} OK / {warn_count} 警告 / {ng_count} 要確認")
        ai_report.extend(["", f"総合: OK {ok_count} / 警告 {warn_count} / 要確認 {ng_count}"])
        report_text = "\n".join(ai_report)
        self.root.after(0, lambda text=report_text: self._copy_bulk_check_report(text))
        return ng_count == 0 and not cancel_event.is_set()


    def start_generation(self):
        self._start_generation(native_render=False)

    def start_native_generation(self):
        self._start_generation(native_render=True)

    def start_native_render_from_history(self):
        selected = self.select_history_dialog(
            "YMMなしMP4化(test)する履歴を選択",
            "MP4化する",
            multi=True,
            require_script=True,
        )
        if not selected:
            return
        self._toggle_ui(False)
        self.cancel_event = threading.Event()
        self._gen_id += 1
        self.log(f"YMMなしMP4化(test)開始: 合計 {len(selected)} 件", "batch")
        threading.Thread(target=self._run_native_render_histories, args=(selected, self._gen_id, self.cancel_event), daemon=True).start()

    def _start_generation(self, native_render=False):
        from core.parser import ScriptParser
        raw_scripts = self.ref_text.get("1.0", tk.END).strip()
        scripts = split_input_scripts(raw_scripts)

        if not scripts:
            messagebox.showwarning("Error", "台本を入力してください")
            return

        self._toggle_ui(False)
        self.cancel_event = threading.Event()
        self._gen_id += 1
        self.batch_progress_var.set("" if len(scripts) <= 1 else f"一括生成準備中: 0/{len(scripts)} 完了")

        # バリデーション・危険チェック・尺予測をログに出力
        abort = False
        for i, script in enumerate(scripts, 1):
            prefix = f"[台本{i}] " if len(scripts) > 1 else ""
            items = ScriptParser.parse_string(script)
            is_valid, messages = ScriptParser.validate(items)
            for m in messages:
                if not m.startswith("⚠"):
                    self.log(f"❌ {prefix}{m}", "error")
                    abort = True
            is_shorts = any(it.get("text", "").strip() == "Shorts" for it in items if it["type"] == "video_format")
            errs, warns = self._pre_generate_check(items, is_shorts)
            for e in errs:
                self.log(f"❌ {prefix}{e}", "error")
                abort = True
            for w in warns:
                self.log(f"⚠ {prefix}{w}", "warning")
            est, n, avg = self._estimate_duration(items, is_shorts)
            if est is not None:
                if is_shorts:
                    if est < 35:
                        verdict, tag = "⚠ 短すぎ", "warning"
                    elif est < 38:
                        verdict, tag = "✅ やや短い", "success"
                    elif est <= 50:
                        verdict, tag = "✅ 理想", "success"
                    elif est <= 55:
                        verdict, tag = "⚠ OKだけど長め", "warning"
                    elif est <= 58:
                        verdict, tag = "⚠ 長め", "warning"
                    else:
                        verdict, tag = "🚨 長すぎ", "warning"
                    self.log(f"{prefix}📏 Shorts推定尺: {est:.0f}秒 {verdict}  （{n}行 / 平均{avg:.1f}文字）", tag)
                else:
                    m, s = divmod(int(est), 60)
                    self.log(f"{prefix}📏 Long推定尺: {m}分{s}秒  （{n}行 / 平均{avg:.1f}文字）", "duration")

        if abort:
            self.log("❌ エラーがあるため処理を中止しました", "error")
            if len(scripts) > 1:
                self.batch_progress_var.set("一括生成準備エラー")
            self._toggle_ui(True)
            return

        self.log("⚠ 問題がある場合は「作業中止」ボタンで止めてください", "warning")
        settings = self._generation_settings()
        # native_render=True: 明示的にnative強制 / None: run_pipeline内でShortsはauto-native
        settings["native_render"] = True if native_render else None
        mode = "YMMなし生成" if native_render else "一括処理（Shortsはffmpeg/nativeで出力）"
        self.log(f"{mode}開始: 合計 {len(scripts)} 件")
        threading.Thread(target=self._run_batch, args=(scripts, settings, self.cancel_event), daemon=True).start()

    def _run_native_render_histories(self, history_names, gen_id, cancel_event):
        from core.native_renderer import render_native_test

        total = len(history_names)
        for idx, name in enumerate(history_names, start=1):
            if cancel_event.is_set():
                self.log("⏹ YMMなしMP4化(test)を中止しました。", "error")
                break
            output_dir = os.path.join("output", name)
            try:
                self._set_batch_progress_text(f"YMMなしMP4化(test): {idx}/{total}")
                self.root.after(0, lambda v=int(((idx - 1) / max(total, 1)) * 100): self.progress.config(value=v))
                self.log(f"🎞 YMMなしMP4化(test): {name}", "batch")
                result = render_native_test(output_dir, progress_callback=self.log)
                self.log(
                    f"✅ YMMなしMP4化完了: {os.path.basename(result.output_path)} "
                    f"(実尺{result.duration_sec:.1f}s / 音声合計{result.audio_duration_sec:.1f}s / 音声{result.audio_count} / 背景{result.background_count})",
                    "success",
                )
            except Exception as e:
                self.log(f"❌ YMMなしMP4化失敗: {name}: {e}", "error")
                if self.debug_var.get():
                    self.log(traceback.format_exc(), "error")

        if gen_id == self._gen_id:
            self.root.after(0, lambda: self.progress.config(value=100 if not cancel_event.is_set() else 0))
            self.root.after(0, lambda: self.status_var.set("YMMなしMP4化(test) 完了" if not cancel_event.is_set() else "Canceled"))
            self.root.after(0, lambda: self._toggle_ui(True))
            self._set_batch_progress_text("" if cancel_event.is_set() else f"YMMなしMP4化(test)完了: {total}/{total}")

    @staticmethod
    def _project_path_from_message(message):
        marker = "プロジェクト保存済み: "
        if marker not in str(message):
            return None
        return str(message).split(marker, 1)[1].strip().splitlines()[0].strip()

    def _run_batch(self, scripts, settings=None, cancel_event=None):
        settings = settings or self._generation_settings()
        cancel_event = cancel_event or self.cancel_event
        gen_id = self._gen_id
        count = len(scripts)
        _active, _uploaded = self.collect_existing_titles()
        _all_titles = _active + _uploaded
        existing_titles = [t for t in _all_titles if self._is_food_title(t)]
        is_batch = count > 1
        try:
            from core.cta_policy import (
                ensure_topic_request_fixed_comment,
                should_allow_topic_request_cta,
                topic_request_cta_reason,
                update_script_topic_request_cta,
            )

            updated_scripts = []
            already_allowed = False
            for idx, script in enumerate(scripts):
                items = ScriptParser.parse_string(script)
                meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
                video_type = meta.get("video_format") or ("Shorts" if any(it.get("text", "").strip() == "Shorts" for it in items if it["type"] == "video_format") else "Long")
                generation_kind = meta.get("generation_kind", "")
                allowed = should_allow_topic_request_cta(
                    video_type=video_type,
                    generation_kind=generation_kind,
                    batch_index=idx,
                    batch_size=count,
                    already_allowed_in_batch=already_allowed,
                )
                reason = topic_request_cta_reason(
                    video_type=video_type,
                    generation_kind=generation_kind,
                    batch_index=idx,
                    batch_size=count,
                    already_allowed_in_batch=already_allowed,
                )
                if allowed:
                    already_allowed = True
                script = update_script_topic_request_cta(script, allowed, reason)
                script = ensure_topic_request_fixed_comment(script, allowed)
                updated_scripts.append(script)
            scripts = updated_scripts
        except Exception as e:
            self.log(f"⚠ CTA方針の自動付与をスキップ: {e}", "warning")

        if is_batch:
            self._set_batch_progress_text(f"一括生成: 0/{count} 完了")
            if not self._run_generation_score_gate(scripts, cancel_event, native_render=settings.get("native_render")):
                if cancel_event.is_set():
                    self.log("\n⏹ 生成前スコアリング中に中止しました。", "error")
                    self.root.after(0, lambda: self.status_var.set("Canceled"))
                else:
                    self.log("\n❌ 生成前スコアリングで要確認の台本があるため、一括生成を開始しません。", "error")
                    self.root.after(0, lambda: self.status_var.set("Score check failed"))
                self.root.after(0, lambda: self._toggle_ui(True))
                return
            self.log("✅ 生成前スコアリングOK。全台本の生成を開始します。", "success")
            self._set_batch_progress_text(f"一括生成: 0/{count} 完了")

        for idx, script in enumerate(scripts):
            if cancel_event.is_set():
                self.log("⏹ 中止しました。残りの履歴/台本は処理しません。", "error")
                break
            try:
                # Derive topic via parser (handles both same-line and next-line values)
                try:
                    _items_for_topic = ScriptParser.parse_string(script)
                    _title_items = [it for it in _items_for_topic if it["type"] == "video_title"]
                    topic = _title_items[0]["text"].strip()[:50] if _title_items and _title_items[0]["text"].strip() else None
                except Exception:
                    topic = None
                if not topic:
                    first_line = next((l.strip() for l in script.split("\n") if l.strip()), "")
                    topic = re.sub(r'^[#*【]|\s*[:：].*$', '', first_line.replace("**", "")).strip()[:30]
                if not topic:
                    topic = f"Generated_Project_{idx+1}"

                if is_batch:
                    self.log(f"\n>>> 処理中 ({idx+1}/{count}): {topic}", "batch")
                    self._set_batch_progress_text(f"一括生成中: {idx+1}/{count}（完了 {idx}/{count}）")
                    self.root.after(0, lambda v=int((idx/count)*100): self.progress.config(value=v))

                while True:
                    try:
                        msg, report = run_pipeline(
                            topic,
                            pregenerated_script=script,
                            debug_mode=settings["debug_mode"],
                            image_style=settings["image_style"],
                            progress_callback=self.log,
                            reuse_backgrounds=settings["reuse_backgrounds"],
                            use_batch_api=settings["use_batch_api"],
                            cancel_event=cancel_event,
                            existing_titles=existing_titles,
                            long_thumbnail_ab_test=settings.get("long_thumbnail_ab_test", False),
                            long_budget_mode=settings.get("long_budget_mode", False),
                            sd_size_mode=settings.get("sd_size_mode", False),
                            native_render=settings.get("native_render"),  # None=auto, True=force native
                        )
                        break
                    except OutputDirectoryLockedError as e:
                        if cancel_event.is_set():
                            raise
                        self.log(f"⚠ 既存プロジェクトが開かれている可能性があります: {e}", "error")
                        retry = self._run_on_ui_sync(
                            lambda m=str(e): messagebox.askokcancel(
                                "プロジェクトファイルを閉じてください",
                                m + "\n\n閉じたらOKを押すと同じ生成を再試行します。\nキャンセルすると処理を中止します。",
                            )
                        )
                        if retry:
                            self.log("🔁 既存フォルダ退避を再試行します...", "batch")
                            continue
                        cancel_event.set()
                        raise

                if cancel_event.is_set():
                    self.log("⏹ 中止しました。残りの履歴/台本は処理しません。", "error")
                    break
                pipeline_failed = msg.lstrip().startswith(("❌", "⏹"))
                if pipeline_failed:
                    self.log(f"要修正: {topic}", "error")
                    if not is_batch:
                        self.root.after(0, lambda m=msg, r=report, gid=gen_id:
                            self.finish_generation(m, r, is_error=True) if gid == self._gen_id else None)
                        return
                    self._set_batch_progress_text(f"一括生成: {idx+1}/{count} 完了")
                    continue
                _should_native_render = getattr(report, "native_render_used", False) or settings.get("native_render") is True
                if _should_native_render:
                    project_path = self._project_path_from_message(msg)
                    output_dir = os.path.dirname(project_path) if project_path else None
                    if not output_dir or not os.path.isdir(output_dir):
                        raise Exception("native MP4出力先フォルダを特定できませんでした")
                    from core.native_renderer import render_native_test
                    from config import (
                        NATIVE_SHORTS_INTRO_VOICE_SPEED, NATIVE_SHORTS_BODY_VOICE_SPEED,
                        NATIVE_LONG_INTRO_VOICE_SPEED, NATIVE_LONG_BODY_VOICE_SPEED,
                    )
                    try:
                        _native_is_shorts = any(
                            it["type"] == "video_format" and it["text"].strip().lower() in ("shorts", "short", "ショート")
                            for it in _items_for_topic
                        )
                    except Exception:
                        _native_is_shorts = False
                    self.log(f"🎞 native MP4出力開始: {os.path.basename(output_dir)}", "batch")
                    native_result = render_native_test(
                        output_dir,
                        progress_callback=self.log,
                        voice_speed_intro=NATIVE_SHORTS_INTRO_VOICE_SPEED if _native_is_shorts else NATIVE_LONG_INTRO_VOICE_SPEED,
                        voice_speed_body=NATIVE_SHORTS_BODY_VOICE_SPEED if _native_is_shorts else NATIVE_LONG_BODY_VOICE_SPEED,
                    )
                    _nd_status = "unknown"
                    try:
                        native_duration = duration_review(native_result.duration_sec, _native_is_shorts)
                        native_duration["source"] = "native_mp4"
                        save_duration_review(output_dir, native_duration)
                        _nd_status = native_duration.get("status", "unknown")
                    except Exception as e:
                        self.log(f"⚠ native実尺メタ保存に失敗: {e}", "warning")
                    _nd_label = duration_status_label(_nd_status)
                    _nd_tag = self._duration_tag(_nd_status)
                    _dur_sec = native_result.duration_sec
                    self.log(
                        f"━━━━━━━━ 実尺チェック {_dur_sec:.1f}秒 / {_nd_label} ━━━━━━━━",
                        _nd_tag,
                    )
                    msg = (
                        f"{msg}\n"
                        f"✅ native MP4出力済み: {native_result.output_path}\n"
                        f"📏 実動画尺: {_dur_sec:.1f}秒（音声合計: {native_result.audio_duration_sec:.1f}秒）/ {_nd_label}"
                    )
                    if report:
                        report.elapsed_sec = getattr(report, "elapsed_sec", 0) or 0
                self.log(f"成功: {topic}", "success")
                if is_batch:
                    self._set_batch_progress_text(f"一括生成: {idx+1}/{count} 完了")
                if not is_batch:
                    self.root.after(0, lambda m=msg, r=report, gid=gen_id:
                        self.finish_generation(m, r) if gid == self._gen_id else None)
                    return

            except Exception as e:
                if cancel_event.is_set():
                    self.log("⏹ 中止しました。進行中処理から戻りました。", "error")
                    break
                err_msg = str(e)
                if settings["debug_mode"]:
                    self.log(traceback.format_exc(), "error")
                self.log(f"❌ エラー: {err_msg}", "error")
                if is_batch:
                    self._set_batch_progress_text(f"一括生成: {idx+1}/{count} 完了")
                if not is_batch:
                    self.root.after(0, lambda m=err_msg, gid=gen_id:
                        self.finish_generation(m, None, is_error=True) if gid == self._gen_id else None)
                    return

        if cancel_event.is_set():
            self.log("\n⏹ 処理を中止しました。", "error")
            if is_batch:
                self._set_batch_progress_text("一括生成中止")
            if cancel_event is self.cancel_event:
                self.root.after(0, lambda: self.status_var.set("Canceled"))
                self.root.after(0, lambda: self._toggle_ui(True))
        elif is_batch:
            self.root.after(0, lambda: self.progress.config(value=100))
            self._set_batch_progress_text(f"一括生成完了: {count}/{count}")
            self.log("\n✅ 全ての一括処理が完了しました！", "success")
            self.root.after(0, lambda c=count: messagebox.showinfo("一括完了", f"{c}件の処理が完了しました。"))
            self.root.after(0, lambda: self._toggle_ui(True))

    def start_youtube_upload(self):
        selected = self.select_history_dialog(
            "YouTubeアップロードする履歴を選択",
            "アップロード",
            multi=True,
            require_mp4=True,
        )
        if not selected:
            return

        base_jobs = []
        skipped = []
        for name in selected:
            output_dir = os.path.join("output", name)
            mp4_candidates = self._mp4_candidates_in_dir(output_dir)

            if not mp4_candidates:
                moved = self._find_and_move_mp4(output_dir, name)
                if moved:
                    mp4_candidates = [moved]
                else:
                    skipped.append(name)
                    continue

            mp4_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            mp4_path = mp4_candidates[0]

            meta = self._read_meta_from_dir(output_dir)
            title = meta.get("title") or self._folder_name_to_title(os.path.basename(output_dir))
            description = meta.get("description", "")
            tags = meta.get("tags", "")
            fixed_comment = meta.get("fixed_comment", "")
            if not description:
                self.log(f"⚠ 説明文が空です: {title}", "warning")
            if not tags:
                self.log(f"⚠ タグが空です: {title}", "warning")
            is_shorts = os.path.basename(output_dir).startswith("[Shorts]")
            thumb = None if is_shorts else self._preferred_long_thumbnail(output_dir)
            if (not is_shorts) and (not thumb or not os.path.exists(thumb)):
                self.log(f"⚠ ロング用サムネイルが見つかりません: {title}", "warning")
            base_jobs.append((mp4_path, title, description, tags, thumb, output_dir, fixed_comment))

        if skipped:
            self.log(f"⚠ MP4なしの履歴をスキップ: {len(skipped)}件", "error")
        if not base_jobs:
            messagebox.showwarning("MP4なし", "選択した履歴フォルダにアップロード可能なMP4がありません。")
            return

        # Shorts / Long をタイプ別にスロット割り当て（YouTube の実態を参照）
        from core.upload_scheduler import assign_slots_from_youtube, format_slot

        self.log("📡 YouTubeのスケジュール済み動画を確認中...", "info")
        shorts_jobs = [(j, "shorts") for j in base_jobs if os.path.basename(j[5]).startswith("[Shorts]")]
        long_jobs   = [(j, "long")   for j in base_jobs if not os.path.basename(j[5]).startswith("[Shorts]")]

        shorts_slots = assign_slots_from_youtube(len(shorts_jobs), "shorts")
        long_slots   = assign_slots_from_youtube(len(long_jobs),   "long")

        # (job, video_type, slot) を結合して元の選択順に並べ替え
        slot_map = {}
        for (j, vt), slot in zip(shorts_jobs, shorts_slots):
            slot_map[id(j)] = (vt, slot)
        for (j, vt), slot in zip(long_jobs, long_slots):
            slot_map[id(j)] = (vt, slot)

        # 確認ダイアログ
        rows = []
        seen_schedule_rows = set()
        seen_schedule_rows = set()
        for j in base_jobs:
            vt, slot = slot_map[id(j)]
            score_label = self._read_score_label(j[5])
            rows.append(("Shorts" if vt == "shorts" else "Long", j[1], format_slot(slot), score_label))
        if not self._confirm_upload_schedule(rows):
            return

        jobs = [
            (mp4, title, desc, tags, thumb, output_dir, slot_map[id(j)][1], slot_map[id(j)][0], fixed_comment)
            for j in base_jobs
            for mp4, title, desc, tags, thumb, output_dir, fixed_comment in [j]
        ]

        self.upload_btn.config(state=tk.DISABLED)
        threading.Thread(
            target=self._run_upload_batch,
            args=(jobs,),
            daemon=True
        ).start()

    def _upload_record_path(self, output_dir):
        candidates = [
            os.path.join(output_dir, "_meta", "upload_record.json"),
            os.path.join(output_dir, "upload_record.json"),
        ]
        return next((path for path in candidates if os.path.exists(path)), candidates[0])

    def _read_upload_record(self, output_dir):
        path = self._upload_record_path(output_dir)
        if not os.path.exists(path):
            return {}, path
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), path
        except Exception:
            return {}, path

    def _write_upload_record_data(self, path, data):
        from core.upload_records import UPLOAD_RECORDS_FILE
        if os.path.abspath(path) == os.path.abspath(UPLOAD_RECORDS_FILE):
            return  # central file abolished
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _update_upload_record_fields(self, path, fields):
        if not path:
            return
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data.update(fields)
        self._write_upload_record_data(path, data)

    def _cleanup_uploaded_backups(self, folder_name):
        if not folder_name:
            return 0
        backup_base = os.path.abspath(os.path.join("output", "000_backups"))
        if not os.path.isdir(backup_base):
            return 0
        prefix = f"{folder_name}_"
        removed = 0
        for name in os.listdir(backup_base):
            path = os.path.abspath(os.path.join(backup_base, name))
            if not path.startswith(backup_base + os.sep):
                continue
            if not os.path.isdir(path):
                continue
            if name == folder_name or name.startswith(prefix):
                shutil.rmtree(path)
                removed += 1
        return removed

    def _find_upload_record_for_schedule(self, title, video_type, publish_at):
        from datetime import datetime
        from core.upload_records import UPLOAD_RECORDS_FILE, find_upload_record
        central_record = find_upload_record(title=title, video_type=video_type, publish_at=publish_at)
        if central_record and central_record.get("video_id"):
            return central_record, UPLOAD_RECORDS_FILE
        uploaded_dir = os.path.join("output", "000_uploaded")
        if not os.path.isdir(uploaded_dir):
            return None, None
        target_ts = int(publish_at.timestamp())
        for name in os.listdir(uploaded_dir):
            output_dir = os.path.join(uploaded_dir, name)
            if not os.path.isdir(output_dir):
                continue
            record, record_path = self._read_upload_record(output_dir)
            if not record.get("video_id"):
                continue
            rec_type = str(record.get("video_type") or "").lower()
            if rec_type and rec_type != video_type:
                continue
            rec_publish = record.get("publish_at")
            if rec_publish:
                try:
                    rec_dt = datetime.fromisoformat(str(rec_publish))
                    if abs(int(rec_dt.timestamp()) - target_ts) <= 60:
                        return record, record_path
                except Exception:
                    pass
            rec_title = self._strip_video_type_prefix(record.get("title") or self._folder_name_to_title(name))
            if rec_title == self._strip_video_type_prefix(title):
                return record, record_path
        return None, None

    def _collect_uploaded_comment_candidates(self):
        from core.upload_records import load_upload_records
        uploaded_dir = os.path.join("output", "000_uploaded")
        rows = []
        seen_video_ids = set()

        # Primary source: scan 000_uploaded folders
        if os.path.isdir(uploaded_dir):
            folders = sorted(
                (d for d in os.listdir(uploaded_dir) if os.path.isdir(os.path.join(uploaded_dir, d))),
                key=lambda d: os.path.getmtime(os.path.join(uploaded_dir, d)),
                reverse=True,
            )
            for name in folders:
                output_dir = os.path.join(uploaded_dir, name)
                meta = self._read_meta_from_dir(output_dir)
                fixed_comment = (meta.get("fixed_comment") or "").strip()
                if not fixed_comment:
                    continue
                record, record_path = self._read_upload_record(output_dir)
                video_id = (record.get("video_id") or "").strip()
                if not video_id:
                    continue
                seen_video_ids.add(video_id)
                rows.append({
                    "name": name,
                    "output_dir": output_dir,
                    "title": meta.get("title") or record.get("title") or self._folder_name_to_title(name),
                    "fixed_comment": fixed_comment,
                    "video_id": video_id,
                    "record": record,
                    "record_path": record_path,
                    "posted_id": record.get("fixed_comment_thread_id") or record.get("fixed_comment_id"),
                    "pinned_at": record.get("fixed_comment_pinned_at"),
                })

        # Supplemental: per-video records from folder scan (for videos not in 000_uploaded)
        for record in sorted(load_upload_records(), key=lambda r: r.get("uploaded_at") or "", reverse=True):
            video_id = (record.get("video_id") or "").strip()
            if not video_id or video_id in seen_video_ids:
                continue
            fixed_comment = (record.get("fixed_comment_text") or "").strip()
            if not fixed_comment:
                continue
            # Use _local_path from folder scan so thread IDs can be written back
            record_path = record.get("_local_path") or ""
            rows.append({
                "name": record.get("title") or video_id,
                "output_dir": os.path.dirname(os.path.dirname(record_path)) if record_path else "",
                "title": record.get("title") or video_id,
                "fixed_comment": fixed_comment,
                "video_id": video_id,
                "record": dict(record),
                "record_path": record_path,
                "posted_id": record.get("fixed_comment_thread_id") or record.get("fixed_comment_id"),
                "pinned_at": record.get("fixed_comment_pinned_at"),
            })
        return rows

    def _enrich_comment_candidate_statuses(self, rows):
        if not rows:
            return rows
        try:
            from core.youtube_uploader import get_youtube_client
            youtube = get_youtube_client()
            ids = [row["video_id"] for row in rows if row.get("video_id")]
            status_by_id = {}
            for i in range(0, len(ids), 50):
                resp = youtube.videos().list(
                    part="snippet,status",
                    id=",".join(ids[i:i + 50]),
                ).execute()
                for item in resp.get("items", []):
                    status_by_id[item["id"]] = item
            for row in rows:
                item = status_by_id.get(row["video_id"])
                if not item:
                    row["video_status_label"] = "動画なし"
                    row["is_public"] = False
                    row["made_for_kids"] = False
                    continue
                status = item.get("status", {})
                row["privacy_status"] = status.get("privacyStatus") or "不明"
                row["made_for_kids"] = bool(status.get("madeForKids"))
                row["is_public"] = row["privacy_status"] == "public"
                if row["made_for_kids"]:
                    row["video_status_label"] = "子ども向け"
                elif row["is_public"]:
                    row["video_status_label"] = "公開"
                else:
                    row["video_status_label"] = row["privacy_status"]
        except Exception as e:
            self.log(f"  ⚠ 固定コメント対象の動画状態確認に失敗: {e}", "warning")
            for row in rows:
                row.setdefault("video_status_label", "未確認")
                row.setdefault("is_public", True)
                row.setdefault("made_for_kids", False)
        return rows

    def select_uploaded_comments_dialog(self):
        candidates = self._enrich_comment_candidate_statuses(self._collect_uploaded_comment_candidates())
        if not candidates:
            messagebox.showinfo(
                "対象なし",
                "固定コメントとvideo_idがあるアップロード済み履歴が見つかりません。",
            )
            return []

        dialog = tk.Toplevel(self.root)
        dialog.title("固定コメントを投稿する動画を選択")
        dialog.geometry("720x420")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text="script.txtの固定コメントを既存動画へ投稿します（Ctrl / Shift で複数選択）",
        ).pack(anchor=tk.W, padx=10, pady=(10, 4))

        filter_frame = ttk.Frame(dialog)
        filter_frame.pack(fill=tk.X, padx=10, pady=(0, 4))
        unposted_only_var = tk.BooleanVar(value=True)
        public_only_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(filter_frame, text="未投稿だけ", variable=unposted_only_var).pack(side=tk.LEFT)
        ttk.Checkbutton(filter_frame, text="公開済みだけ", variable=public_only_var).pack(side=tk.LEFT, padx=(12, 0))
        count_var = tk.StringVar(value="")
        ttk.Label(filter_frame, textvariable=count_var, font=("Meiryo", 8)).pack(side=tk.LEFT, padx=(12, 0))

        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, font=("Meiryo", 9))
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        visible_rows = []

        def render_candidates():
            listbox.delete(0, tk.END)
            visible_rows.clear()
            for row in candidates:
                if unposted_only_var.get() and (row.get("posted_id") or row.get("pinned_at")):
                    continue
                if public_only_var.get() and (not row.get("is_public") or row.get("made_for_kids")):
                    continue
                visible_rows.append(row)
                status_bits = [row.get("video_status_label") or "未確認"]
                if row.get("posted_id"):
                    status_bits.append("投稿済み")
                if row.get("pinned_at"):
                    status_bits.append("ピン留め済み")
                preview = row["fixed_comment"].replace("\n", " / ")
                if len(preview) > 42:
                    preview = preview[:40] + "..."
                listbox.insert(tk.END, f"{row['title']}  /  {preview}  ({' / '.join(status_bits)})")
            count_var.set(f"表示 {len(visible_rows)} / 全 {len(candidates)} 件")

        unposted_only_var.trace_add("write", lambda *_: render_candidates())
        public_only_var.trace_add("write", lambda *_: render_candidates())
        render_candidates()

        selected = []

        def do_ok():
            indices = list(listbox.curselection())
            if not indices:
                messagebox.showwarning("未選択", "1件以上選択してください。", parent=dialog)
                return
            already = [visible_rows[i] for i in indices if visible_rows[i].get("posted_id")]
            if already and not messagebox.askyesno(
                "投稿済みを含みます",
                f"投稿済み記録がある動画が{len(already)}件あります。\n未投稿のものだけ投稿しますか？",
                parent=dialog,
            ):
                return
            selected.extend(visible_rows[i] for i in indices)
            dialog.destroy()

        def mark_pinned():
            indices = list(listbox.curselection())
            if not indices:
                messagebox.showwarning("未選択", "1件以上選択してください。", parent=dialog)
                return
            now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            marked = 0
            for i in indices:
                row = visible_rows[i]
                record = dict(row.get("record") or {})
                record["fixed_comment_pinned_at"] = now
                try:
                    self._write_upload_record_data(row["record_path"], record)
                    row["record"] = record
                    row["pinned_at"] = now
                    marked += 1
                except Exception as e:
                    self.log(f"  ⚠ ピン留め記録の保存に失敗: {row['title']}: {e}", "warning")
            render_candidates()
            self.log(f"📌 ピン留め済みとして記録: {marked}件", "success")

        btns = ttk.Frame(dialog)
        btns.pack(fill=tk.X, padx=10, pady=(4, 10))
        ttk.Button(btns, text="キャンセル", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="投稿開始", command=do_ok).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(btns, text="選択をピン留め済みにする", command=mark_pinned).pack(side=tk.RIGHT, padx=(0, 8))

        self.root.wait_window(dialog)
        return selected

    def start_post_fixed_comments(self):
        selected = self.select_uploaded_comments_dialog()
        if not selected:
            return
        self.comment_btn.config(state=tk.DISABLED)
        self.log(f"💬 固定コメント投稿開始: {len(selected)}件", "batch")
        threading.Thread(target=self._run_post_fixed_comments, args=(selected,), daemon=True).start()

    def _run_post_fixed_comments(self, rows):
        try:
            from core.youtube_uploader import get_youtube_client, post_comment
            total = len(rows)
            posted = 0
            skipped = 0
            failed = 0
            posted_links = []
            status_by_id = {}
            try:
                youtube = get_youtube_client()
                ids = [row["video_id"] for row in rows if row.get("video_id")]
                for i in range(0, len(ids), 50):
                    resp = youtube.videos().list(
                        part="snippet,status",
                        id=",".join(ids[i:i + 50]),
                    ).execute()
                    for item in resp.get("items", []):
                        status_by_id[item["id"]] = item
            except Exception as e:
                self.log(f"  ⚠ 動画状態の確認に失敗したため、固定コメント投稿を中止します: {e}", "warning")
                self.log(f"💬 固定コメント投稿完了: 投稿 0 / スキップ {total} / 失敗 0", "warning")
                return

            for idx, row in enumerate(rows, 1):
                title = row["title"]
                video_url = f"https://youtu.be/{row['video_id']}"
                if row.get("posted_id"):
                    skipped += 1
                    self.log(f"💬 [{idx}/{total}] 投稿済みのためスキップ: {title}", "warning")
                    continue
                video_status = status_by_id.get(row["video_id"])
                if status_by_id and not video_status:
                    skipped += 1
                    self.log(f"💬 [{idx}/{total}] 動画が見つからないためスキップ: {title}", "warning")
                    continue
                if video_status:
                    status = video_status.get("status", {})
                    privacy = status.get("privacyStatus")
                    made_for_kids = status.get("madeForKids")
                    if made_for_kids:
                        skipped += 1
                        self.log(f"💬 [{idx}/{total}] 子ども向け設定のためスキップ: {title}", "warning")
                        continue
                    if privacy != "public":
                        skipped += 1
                        self.log(f"💬 [{idx}/{total}] {privacy or '不明'} のためスキップ: {title}", "warning")
                        continue

                self.log(f"💬 [{idx}/{total}] 固定コメント投稿中: {title}", "batch")
                self.log(f"  動画URL: {video_url}", "batch")
                comment_id = post_comment(row["video_id"], row["fixed_comment"], progress_callback=self.log)
                if comment_id:
                    record = dict(row.get("record") or {})
                    record["fixed_comment_thread_id"] = comment_id
                    record["fixed_comment_posted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    record["fixed_comment_text"] = row["fixed_comment"]
                    try:
                        self._write_upload_record_data(row["record_path"], record)
                    except Exception as e:
                        self.log(f"  ⚠ 投稿記録の保存に失敗: {e}", "warning")
                    posted += 1
                    posted_links.append({
                        "title": title,
                        "video_id": row["video_id"],
                        "comment_id": comment_id,
                        "record_path": row["record_path"],
                        "record": record,
                    })
                    self.log(f"  ✅ コメント投稿完了: {video_url}", "success")
                    self.log("     ピン留めはYouTube側で確認してください", "success")
                else:
                    failed += 1
                    self.log(f"  ❌ コメント投稿失敗: {title}", "error")

            tag = "success" if failed == 0 else "warning"
            self.log(f"💬 固定コメント投稿完了: 投稿 {posted} / スキップ {skipped} / 失敗 {failed}", tag)
            if posted_links:
                self.root.after(0, lambda links=posted_links: self.show_posted_comment_links_dialog(links))
        finally:
            self.root.after(0, lambda: self.comment_btn.config(state=tk.NORMAL))

    def show_posted_comment_links_dialog(self, links):
        import webbrowser

        dialog = tk.Toplevel(self.root)
        dialog.title("固定コメント投稿済みリンク")
        dialog.geometry("780x360")
        dialog.transient(self.root)

        ttk.Label(
            dialog,
            text="投稿したコメントです。動画を開いて内容を確認できます。",
            font=("Meiryo", 9),
        ).pack(anchor=tk.W, padx=12, pady=(10, 4))

        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        cols = ("#", "タイトル", "動画ID")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        ysb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        tree.heading("#", text="#", anchor=tk.CENTER)
        tree.heading("タイトル", text="タイトル", anchor=tk.W)
        tree.heading("動画ID", text="動画ID", anchor=tk.CENTER)
        tree.column("#", width=40, stretch=False, anchor=tk.CENTER)
        tree.column("タイトル", width=520, stretch=True, anchor=tk.W)
        tree.column("動画ID", width=140, stretch=False, anchor=tk.CENTER)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)

        for idx, item in enumerate(links, 1):
            tree.insert("", tk.END, iid=str(idx - 1), values=(idx, item["title"], item["video_id"]))

        if links:
            tree.selection_set("0")

        def selected_link():
            sel = tree.selection()
            if not sel:
                return None
            try:
                return links[int(sel[0])]
            except Exception:
                return None

        def open_video():
            item = selected_link()
            if item:
                webbrowser.open(f"https://youtu.be/{item['video_id']}")

        def mark_selected_pinned():
            item = selected_link()
            if not item:
                return
            record = dict(item.get("record") or {})
            record["fixed_comment_pinned_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            try:
                self._write_upload_record_data(item["record_path"], record)
                item["record"] = record
                self.log(f"📌 ピン留め済みとして記録: {item['title']}", "success")
            except Exception as e:
                self.log(f"  ⚠ ピン留め記録の保存に失敗: {e}", "warning")

        btns = ttk.Frame(dialog)
        btns.pack(fill=tk.X, padx=12, pady=(4, 10))
        ttk.Label(btns, text=f"投稿済み {len(links)} 件", font=("Meiryo", 8)).pack(side=tk.LEFT)
        ttk.Button(btns, text="閉じる", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="動画を開く", style="Accent.TButton", command=open_video).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(btns, text="ピン留め済みにする", command=mark_selected_pinned).pack(side=tk.RIGHT, padx=(0, 8))

    def open_analytics_window(self):
        win = tk.Toplevel(self.root)
        win.title("YouTube Analytics - 動画評価一覧")
        win.geometry("1180x640")

        state = {
            "items": [],
            "days": 28,
            "analytics_meta": {},
            "sort_col": None,
            "sort_reverse": False,
        }

        top = ttk.Frame(win, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="期間:").pack(side=tk.LEFT)
        days_var = tk.IntVar(value=28)
        days_combo = ttk.Combobox(top, textvariable=days_var, values=[7, 28, 90], state="readonly", width=6)
        days_combo.pack(side=tk.LEFT, padx=(4, 12))
        summary_var = tk.StringVar(value="未取得")
        ttk.Label(top, textvariable=summary_var).pack(side=tk.LEFT, padx=(0, 12))
        error_var = tk.StringVar(value="")
        error_label = ttk.Label(win, textvariable=error_var, foreground="#c0392b", wraplength=1120)
        error_label.pack(fill=tk.X, padx=8, pady=(0, 6))

        cols = (
            "title", "published_at", "video_type", "duration", "duration_status", "analysis_status", "is_provisional", "views", "impressions", "ctr",
            "average_view_duration", "average_percentage_viewed", "likes", "like_rate",
            "comments", "subscribers_net", "score", "action",
            "audio_cutoff_risk", "generation_kind", "source_video_title", "generation_purpose",
            "character_pattern", "genre_group",
        )
        headings = {
            "title": "タイトル",
            "published_at": "公開日時",
            "video_type": "種別",
            "duration": "尺",
            "duration_status": "尺判定",
            "analysis_status": "分析状態",
            "is_provisional": "判定保留",
            "views": "再生数",
            "impressions": "インプレ",
            "ctr": "CTR",
            "average_view_duration": "平均視聴時間",
            "average_percentage_viewed": "平均視聴率",
            "likes": "高評価",
            "like_rate": "高評価率",
            "comments": "コメント",
            "subscribers_net": "登録者増減",
            "score": "評価",
            "action": "対応",
            "audio_cutoff_risk": "音切れリスク",
            "generation_kind": "生成区分",
            "source_video_title": "元動画",
            "generation_purpose": "目的",
            "character_pattern": "キャラパターン",
            "genre_group": "ジャンル",
        }

        frame = ttk.Frame(win, padding=(8, 0, 8, 8))
        frame.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=20)
        ysb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        xsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        widths = {
            "title": 260,
            "published_at": 140,
            "video_type": 70,
            "duration": 70,
            "duration_status": 90,
            "analysis_status": 90,
            "is_provisional": 80,
            "views": 80,
            "impressions": 90,
            "ctr": 70,
            "average_view_duration": 100,
            "average_percentage_viewed": 90,
            "likes": 70,
            "like_rate": 80,
            "comments": 80,
            "subscribers_net": 90,
            "score": 55,
            "action": 130,
            "audio_cutoff_risk": 90,
            "generation_kind": 90,
            "source_video_title": 220,
            "generation_purpose": 160,
            "character_pattern": 110,
            "genre_group": 100,
        }
        for col in cols:
            tree.heading(col, text=headings[col], command=lambda c=col: sort_by(c))
            tree.column(col, width=widths.get(col, 90), anchor=tk.W if col in ("title", "action", "source_video_title", "generation_purpose") else tk.CENTER)

        tree.tag_configure("score_S", background="#fff3bf")
        tree.tag_configure("score_A", background="#d3f9d8")
        tree.tag_configure("score_B", background="#d0ebff")
        tree.tag_configure("score_C", background="#ffe8cc")
        tree.tag_configure("score_D", background="#ffe3e3")

        def _widget_alive(widget):
            try:
                return bool(widget.winfo_exists())
            except tk.TclError:
                return False

        def _fmt_percent(value):
            if value is None:
                return ""
            try:
                return f"{float(value):.1f}%"
            except Exception:
                return ""

        def _fmt_ctr(value):
            if value is None:
                return ""
            try:
                return f"{float(value):.2f}%"
            except Exception:
                return ""

        def _fmt_published(value):
            if not value:
                return ""
            try:
                from datetime import datetime, timezone, timedelta
                text = str(value).replace("Z", "+00:00")
                dt = datetime.fromisoformat(text)
                jst = timezone(timedelta(hours=9))
                return dt.astimezone(jst).strftime("%Y/%m/%d %H:%M")
            except Exception:
                return str(value)[:16]

        def _sort_value(item, col):
            from datetime import datetime
            if col == "published_at":
                value = item.get(col)
                if not value:
                    return 0
                try:
                    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
                except Exception:
                    return 0
            if col == "duration_status":
                order = {"ideal": 5, "ok": 4, "ok_but_short": 3, "ok_but_long": 3, "warning": 2, "needs_review": 1}
                return order.get(str(item.get(col) or ""), 0)
            if col == "score":
                order = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "未計測": 0, "対象外": -1}
                return order.get(str(item.get(col) or ""), -2)
            if col == "is_provisional":
                return 1 if item.get(col) else 0
            if col == "audio_cutoff_risk":
                return 1 if item.get(col) else 0
            if col in {
                "duration", "views", "impressions", "ctr", "average_view_duration",
                "average_percentage_viewed", "likes", "like_rate", "comments", "subscribers_net",
            }:
                try:
                    value = item.get(col)
                    return float(value) if value not in (None, "") else -1
                except Exception:
                    return -1
            return str(item.get(col) or "")

        def _refresh_headings():
            if not _widget_alive(tree):
                return
            for col in cols:
                label = headings[col]
                if state["sort_col"] == col:
                    label += " ▼" if state["sort_reverse"] else " ▲"
                tree.heading(col, text=label, command=lambda c=col: sort_by(c))

        def sort_by(col):
            if not _widget_alive(tree):
                return
            if state["sort_col"] == col:
                state["sort_reverse"] = not state["sort_reverse"]
            else:
                state["sort_col"] = col
                state["sort_reverse"] = col in {
                    "published_at", "duration", "views", "impressions", "ctr",
                    "average_view_duration", "average_percentage_viewed", "likes",
                    "like_rate", "comments", "subscribers_net", "score", "audio_cutoff_risk",
                }
            state["items"].sort(key=lambda item: _sort_value(item, col), reverse=state["sort_reverse"])
            _refresh_headings()
            render()

        def render():
            if not _widget_alive(tree):
                return
            tree.delete(*tree.get_children())
            for item in state["items"]:
                values = (
                    item.get("title", ""),
                    _fmt_published(item.get("published_at")),
                    item.get("video_type", ""),
                    format_duration(item.get("duration")),
                    format_duration_status(item.get("duration_status")),
                    item.get("analysis_status", ""),
                    "保留" if item.get("is_provisional") else "",
                    item.get("views", 0),
                    item.get("impressions", 0),
                    _fmt_ctr(item.get("ctr")),
                    format_duration(item.get("average_view_duration")),
                    _fmt_percent(item.get("average_percentage_viewed")),
                    item.get("likes", 0),
                    _fmt_ctr(item.get("like_rate")),
                    item.get("comments", 0),
                    item.get("subscribers_net", 0),
                    item.get("score", ""),
                    item.get("action", ""),
                    "あり" if item.get("audio_cutoff_risk") else "",
                    item.get("generation_kind", ""),
                    item.get("source_video_title", ""),
                    item.get("generation_purpose", ""),
                    item.get("character_pattern", ""),
                    item.get("genre_group", ""),
                )
                tree.insert("", tk.END, values=values, tags=(f"score_{item.get('score', 'D')}",))

        def fetch():
            days = int(days_var.get())
            state["days"] = days
            fetch_btn.config(state=tk.DISABLED)
            summary_var.set("取得中...")
            error_var.set("")

            def worker():
                try:
                    from core.youtube_analytics import fetch_video_analytics
                    data = fetch_video_analytics(days)
                    items = score_items(data.get("items", []))
                    api_summary = data.get("summary", {})
                    json_path, tsv_path = save_score_files(items, days, summary=api_summary)

                    def done():
                        if not _widget_alive(tree):
                            return
                        state["items"] = items
                        state["analytics_meta"] = {
                            "days": api_summary.get("days", days),
                            "start_date": api_summary.get("start_date"),
                            "end_date": api_summary.get("end_date"),
                            "generated_at": None,
                        }
                        summary = api_summary
                        period_text = analytics_period_label(
                            days=summary.get("days", days),
                            start_date=summary.get("start_date"),
                            end_date=summary.get("end_date"),
                        )
                        published_count = sum(1 for item in items if item.get("publish_status") == "published")
                        scheduled_count = sum(1 for item in items if item.get("publish_status") == "scheduled")
                        analyzable_count = sum(1 for item in items if item.get("analysis_status") == "analyzable")
                        data_wait_count = sum(1 for item in items if item.get("analysis_status") == "data_wait")
                        summary_var.set(
                            f"{days}日 / 全{len(items)}件（公開{published_count} / 予約{scheduled_count} / 分析{analyzable_count} / 待ち{data_wait_count}）"
                            f" / {period_text} / 再生 {summary.get('views', 0)} / 保存: {os.path.basename(json_path)}"
                        )
                        render()
                        self.log(f"📊 Analytics評価一覧を保存: {json_path} / {tsv_path}", "success")
                        fetch_btn.config(state=tk.NORMAL)

                    self.root.after(0, done)
                except Exception as e:
                    err_text = str(e)
                    tb_text = traceback.format_exc()

                    def failed(err_text=err_text, tb_text=tb_text):
                        if not _widget_alive(tree):
                            return
                        summary_var.set("取得失敗")
                        error_var.set(err_text)
                        self.log(f"❌ Analytics取得エラー: {err_text}", "error")
                        if self.debug_var.get():
                            self.log(tb_text, "error")
                        fetch_btn.config(state=tk.NORMAL)
                    self.root.after(0, failed)

            threading.Thread(target=worker, daemon=True).start()

        def copy_score_list():
            text = to_tsv(state["items"])
            win.clipboard_clear()
            win.clipboard_append(text)
            win.update()
            self.log(f"📋 評価一覧をコピーしました: {len(state['items'])}件", "success")

        def copy_ai_analysis():
            summary = build_performance_summary(state["items"], meta=state.get("analytics_meta") or {"days": state.get("days")})
            lines = [
                "以下はYouTube Analyticsの動画別成績です。改善候補と横展開候補を分析してください。",
                "analysis_status=data_wait の動画も無視せず、平均視聴率未取得の暫定評価として必ずコメントしてください。",
                "data_wait は views / likes / like_rate / comments を見て、強い反応がある場合は「暫定横展開候補」「要追跡」「まだ判断保留」など短く分類してください。",
                "",
                summary,
                "",
                to_tsv(state["items"]),
            ]
            win.clipboard_clear()
            win.clipboard_append("\n".join(lines))
            win.update()
            self.log(f"📋 AI分析用にコピーしました: {len(state['items'])}件", "success")

        fetch_btn = ttk.Button(top, text="取得", style="Accent.TButton", command=fetch)
        fetch_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._add_tooltip(fetch_btn, "YouTube Analyticsから指定期間の動画別成績を取得し、評価ファイルを保存します。")
        copy_score_btn = ttk.Button(top, text="📋 評価一覧コピー", command=copy_score_list)
        copy_score_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._add_tooltip(copy_score_btn, "表示中の評価一覧をTSV形式でクリップボードにコピーします。")
        copy_ai_btn = ttk.Button(top, text="📋 AI分析用にコピー", command=copy_ai_analysis)
        copy_ai_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._add_tooltip(copy_ai_btn, "Analytics一覧にAI分析用の依頼文を添えてクリップボードにコピーします。")

        fetch()

    def show_upload_schedule_dialog(self, auto_sync=True):
        from core.upload_scheduler import format_slot
        from datetime import datetime, timedelta, timezone
        JST = timezone(timedelta(hours=9))
        now = datetime.now(JST)

        def _schedule_dt(value):
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(JST)
            except Exception:
                return None

        def build_rows(statuses: dict | None = None):
            """Build rows from YouTube video statuses (source of truth)."""
            from core.youtube_uploader import get_channel_upload_video_statuses
            current_now = datetime.now(JST)
            cutoff_dt = current_now - timedelta(days=90)
            if statuses is None:
                try:
                    statuses = get_channel_upload_video_statuses()
                except Exception:
                    statuses = {}

            new_rows = []
            seen: set[tuple] = set()
            for video_id, status in statuses.items():
                vt = str(status.get("video_type") or "").lower()
                if vt not in ("shorts", "long"):
                    continue
                title = str(status.get("title") or "").strip()
                if not title:
                    continue
                privacy = str(status.get("privacyStatus") or "").lower()
                pub_at_raw = str(status.get("publishAt") or "").strip()
                published_at_raw = str(status.get("publishedAt") or "").strip()

                if privacy == "public":
                    dt = _schedule_dt(published_at_raw) if published_at_raw else None
                    if not dt or dt < cutoff_dt:
                        continue
                    row_status = "公開済"
                    iso_key = dt.isoformat()
                elif privacy in ("private", "unlisted") and pub_at_raw:
                    dt = _schedule_dt(pub_at_raw)
                    if not dt or dt <= current_now:
                        continue
                    row_status = "予定"
                    iso_key = dt.isoformat()
                else:
                    continue

                key = (vt, iso_key[:16])
                if key in seen:
                    continue
                seen.add(key)
                label = "Shorts" if vt == "shorts" else "Long"
                new_rows.append((dt, label, title, row_status, vt, iso_key, "", ""))

            new_rows.sort(key=lambda r: r[0], reverse=True)
            return new_rows

        rows = [] if auto_sync else build_rows()

        dialog = tk.Toplevel(self.root)
        dialog.title("アップロードスケジュール")
        dialog.geometry("1020x420")
        dialog.resizable(True, True)
        dialog.transient(self.root)

        ttk.Label(dialog, text="アップロード済み・予約中のスケジュール一覧",
                  font=("Meiryo", 9, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 2))

        filter_frame = ttk.Frame(dialog)
        filter_frame.pack(anchor=tk.W, padx=12, pady=(0, 4))
        filter_var = tk.StringVar(value="すべて")
        status_filter_var = tk.StringVar(value="予定")
        for _txt in ("すべて", "Shorts", "Long"):
            ttk.Radiobutton(filter_frame, text=_txt, variable=filter_var, value=_txt,
                            command=lambda: refresh_tree()).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Separator(filter_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(filter_frame, text="状態:").pack(side=tk.LEFT, padx=(0, 4))
        def _on_status_filter_change():
            # 予定→昇順（近い順）、公開済み/すべて→降順（新しい順）
            if sort_state["col"] == "日時":
                sort_state["reverse"] = status_filter_var.get() != "予定"
                _update_headings()
            refresh_tree()

        for _txt in ("すべて", "予定", "公開済"):
            ttk.Radiobutton(filter_frame, text=_txt, variable=status_filter_var, value=_txt,
                            command=_on_status_filter_change).pack(side=tk.LEFT, padx=(0, 12))
        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        cols = ("日時", "種別", "タイトル", "状態", "区分", "パターン")
        _heading_base = {
            "日時":     "公開/予約日時 (JST)",
            "種別":     "種別",
            "タイトル": "タイトル",
            "状態":     "状態",
            "区分":     "生成区分",
            "パターン": "キャラ",
        }
        # col → row tuple index
        _col_data_idx = {"日時": 0, "種別": 1, "タイトル": 2, "状態": 3, "区分": 6, "パターン": 7}
        # default: 日時 昇順（予定表示時は近い順、公開済み切替時はヘッダーで変更）
        sort_state = {"col": "日時", "reverse": False}

        tree = ttk.Treeview(frame, columns=cols, show="headings", height=14)
        tree.column("日時",    width=160, stretch=False, anchor=tk.CENTER)
        tree.column("種別",    width=60,  stretch=False, anchor=tk.CENTER)
        tree.column("タイトル", width=380, stretch=True,  anchor=tk.W)
        tree.column("状態",    width=62,  stretch=False, anchor=tk.CENTER)
        tree.column("区分",    width=90,  stretch=False, anchor=tk.CENTER)
        tree.column("パターン", width=110, stretch=False, anchor=tk.CENTER)

        tree.tag_configure("done",      foreground="#aaaaaa", background="#f5f5f5")
        tree.tag_configure("upcoming",  foreground="#0984e3", font=("Meiryo", 9, "bold"))
        tree.tag_configure("published", foreground="#27ae60")

        def _update_headings():
            for col in cols:
                ind = (" ▼" if sort_state["reverse"] else " ▲") if sort_state["col"] == col else ""
                anchor = tk.W if col == "タイトル" else tk.CENTER
                tree.heading(col, text=_heading_base[col] + ind, anchor=anchor,
                             command=lambda c=col: _on_header_click(c))

        def _on_header_click(col):
            if sort_state["col"] == col:
                sort_state["reverse"] = not sort_state["reverse"]
            else:
                sort_state["col"] = col
                sort_state["reverse"] = col == "日時"  # 日時だけデフォルト降順
            _update_headings()
            refresh_tree()

        _update_headings()

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        row_by_iid = {}
        count_var = tk.StringVar()

        def refresh_tree():
            if not tree.winfo_exists():
                return
            tree.delete(*tree.get_children())
            row_by_iid.clear()
            filt = filter_var.get()
            status_filt = status_filter_var.get()
            visible_rows = [
                r for r in rows
                if (filt == "すべて" or r[1] == filt)
                and (status_filt == "すべて" or r[3] == status_filt)
            ]
            idx = _col_data_idx[sort_state["col"]]
            visible_rows.sort(
                key=lambda r: (r[idx] if r[idx] is not None else ""),
                reverse=sort_state["reverse"],
            )
            for enum_idx, (dt, label, title, status, vt, iso, gen_kind, char_pat) in enumerate(visible_rows):
                dt_str = dt.strftime("%Y/%m/%d %H:%M")
                if status == "公開済":
                    tag = "published"
                elif status == "済":
                    tag = "done"
                else:
                    tag = "upcoming"
                iid = str(enum_idx)
                row_by_iid[iid] = {
                    "dt": dt,
                    "label": label,
                    "title": title,
                    "status": status,
                    "video_type": vt,
                    "iso": iso,
                }
                tree.insert("", tk.END, iid=iid, values=(dt_str, label, title, status, gen_kind, char_pat), tags=(tag,))
            n_upcoming  = sum(1 for r in visible_rows if r[3] == "予定")
            n_published = sum(1 for r in visible_rows if r[3] == "公開済")
            count_var.set(
                f"合計 {len(visible_rows)} 件  /  予定 {n_upcoming} 件  /  公開済 {n_published} 件 (直近90日・YouTube同期値)"
            )

        if auto_sync:
            count_var.set("YouTube同期中...")
        else:
            refresh_tree()

        if auto_sync:
            if self._schedule_sync_running:
                self.log("YouTube取得はすでに実行中です。", "info")
            else:
                self._schedule_sync_running = True

                def sync_worker():
                    from core.youtube_uploader import get_channel_upload_video_statuses
                    try:
                        statuses = get_channel_upload_video_statuses()
                        def done(statuses=statuses):
                            self.log(f"YouTube確認: {len(statuses)}件", "info")
                            if dialog.winfo_exists():
                                rows[:] = build_rows(statuses)
                                refresh_tree()
                        self.root.after(0, done)
                    except Exception as e:
                        def failed(e=e):
                            self.log(f"YouTube取得に失敗しました: {e}", "warning")
                            rows[:] = build_rows({})
                            refresh_tree()
                        self.root.after(0, failed)
                    finally:
                        self._schedule_sync_running = False

                threading.Thread(target=sync_worker, daemon=True).start()
        else:
            refresh_tree()

        # 削除・手動公開済みボタン
        def delete_selected():
            sel = tree.selection()
            if not sel:
                return
            if not messagebox.askyesno("削除確認", f"{len(sel)}件のスケジュールを削除しますか？", parent=dialog):
                return
            for item in sel:
                row = row_by_iid.get(item)
                if row:
                    record, record_path = self._find_upload_record_for_schedule(row["title"], row["video_type"], row["dt"])
                    if record and record_path:
                        record["publish_at"] = None
                        record["publish_status"] = "private"
                        try:
                            self._write_upload_record_data(record_path, record)
                        except Exception as e:
                            self.log(f"  ⚠ upload_record更新失敗: {e}", "warning")
                tree.delete(item)
            self.log(f"🗑 スケジュール {len(sel)}件を削除しました", "info")

        def mark_manual_published():
            sel = tree.selection()
            if not sel:
                return
            if not messagebox.askyesno(
                "手動公開済みにする",
                "選択した動画をYouTube Studio側で手動公開済みとして処理しますか？\n\n"
                "・予約スケジュールから削除します\n"
                "・アップロード履歴にタイトルを追記します",
                parent=dialog,
            ):
                return

            published_titles = []
            for item in sel:
                row = row_by_iid.get(item)
                title = row["title"] if row else tree.item(item, "values")[2]
                if row:
                    record, record_path = self._find_upload_record_for_schedule(row["title"], row["video_type"], row["dt"])
                    if record and record_path:
                        record["publish_at"] = None
                        record["publish_status"] = "published"
                        try:
                            self._write_upload_record_data(record_path, record)
                        except Exception as e:
                            self.log(f"  ⚠ upload_record更新失敗: {e}", "warning")
                if title:
                    published_titles.append(str(title).strip())
                tree.delete(item)

            added = self._append_uploaded_titles(published_titles)
            self.refresh_history()
            self.log(f"✅ 手動公開済みとして処理しました: {len(sel)}件（履歴追記 {added}件）", "success")

        def change_publish_time():
            def allowed_schedule_hours(video_type, dt):
                if video_type == "long":
                    return [12, 21] if dt.weekday() in (5, 6) else [21]
                return [7, 12, 19]

            def allowed_schedule_label(video_type, dt):
                hours = allowed_schedule_hours(video_type, dt)
                return " / ".join(f"{h}:00" for h in hours)

            sel = tree.selection()
            if len(sel) != 1:
                messagebox.showwarning("選択エラー", "公開予定を変更する動画を1件だけ選択してください。", parent=dialog)
                return
            row = row_by_iid.get(sel[0])
            if not row:
                return
            if row["status"] != "予定":
                messagebox.showwarning("変更不可", "過去のスケジュールは変更できません。", parent=dialog)
                return

            edit = tk.Toplevel(dialog)
            edit.title("公開予定を変更")
            edit.geometry("440x210")
            edit.transient(dialog)
            edit.grab_set()

            ttk.Label(edit, text=row["title"], wraplength=380, font=("Meiryo", 9, "bold")).pack(anchor=tk.W, padx=12, pady=(12, 6))
            ttk.Label(edit, text="新しい公開予定日時 (JST)").pack(anchor=tk.W, padx=12)
            ttk.Label(
                edit,
                text="指定できる時刻: Shorts 7:00/12:00/19:00、Long 平日21:00・土日12:00/21:00",
                font=("Meiryo", 8),
                foreground="#636e72",
                wraplength=380,
            ).pack(anchor=tk.W, padx=12, pady=(2, 0))

            picker = ttk.Frame(edit)
            picker.pack(anchor=tk.W, padx=12, pady=(8, 8))
            ttk.Label(picker, text="日付").pack(side=tk.LEFT)
            date_values = [
                (now.date() + timedelta(days=i)).strftime("%Y/%m/%d")
                for i in range(90)
            ]
            date_var = tk.StringVar(value=row["dt"].strftime("%Y/%m/%d"))
            date_combo = ttk.Combobox(picker, textvariable=date_var, values=date_values, state="readonly", width=12)
            date_combo.pack(side=tk.LEFT, padx=(4, 12))
            ttk.Label(picker, text="時間").pack(side=tk.LEFT)
            time_var = tk.StringVar()
            time_combo = ttk.Combobox(picker, textvariable=time_var, state="readonly", width=8)
            time_combo.pack(side=tk.LEFT, padx=(4, 0))

            def selected_date():
                return datetime.strptime(date_var.get(), "%Y/%m/%d").date()

            def refresh_time_values(*_):
                date = selected_date()
                sample_dt = datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=JST)
                values = [f"{h:02d}:00" for h in allowed_schedule_hours(row["video_type"], sample_dt)]
                time_combo.config(values=values)
                current = time_var.get()
                preferred = row["dt"].strftime("%H:%M") if date == row["dt"].date() else values[0]
                time_var.set(current if current in values else preferred if preferred in values else values[0])

            date_combo.bind("<<ComboboxSelected>>", refresh_time_values)
            refresh_time_values()
            if row["dt"].strftime("%H:%M") in time_combo.cget("values"):
                time_var.set(row["dt"].strftime("%H:%M"))

            def apply_change():
                try:
                    new_dt = datetime.strptime(f"{date_var.get()} {time_var.get()}", "%Y/%m/%d %H:%M").replace(tzinfo=JST)
                except ValueError:
                    messagebox.showerror("日時エラー", "日付と時間を選択してください。", parent=edit)
                    return
                if new_dt <= now + timedelta(minutes=5):
                    messagebox.showerror("日時エラー", "現在時刻の5分後より先を指定してください。", parent=edit)
                    return
                allowed_hours = allowed_schedule_hours(row["video_type"], new_dt)
                if new_dt.minute != 0 or new_dt.hour not in allowed_hours:
                    messagebox.showerror(
                        "予約枠エラー",
                        f"この種別・曜日で指定できる時刻は {allowed_schedule_label(row['video_type'], new_dt)} だけです。",
                        parent=edit,
                    )
                    return

                from core.upload_scheduler import format_slot
                vt = row["video_type"]
                conflicts = [
                    r for r in rows
                    if r[4] == vt and r[3] == "予定" and r[0] == new_dt and r[5] != row["iso"]
                ]
                if len(conflicts) > 1:
                    messagebox.showerror(
                        "入れ替え不可",
                        "変更先の枠に複数の予約があります。先にスケジュール同期で整理してください。",
                        parent=edit,
                    )
                    return
                conflict_title = conflicts[0][2] if conflicts else None

                record, record_path = self._find_upload_record_for_schedule(row["title"], vt, row["dt"])
                if not record:
                    messagebox.showerror("動画IDなし", "対応するupload_record.json/video_idが見つかりません。", parent=edit)
                    return
                video_id = record.get("video_id")
                swap_record = None
                swap_record_path = None
                if conflict_title:
                    swap_record, swap_record_path = self._find_upload_record_for_schedule(conflict_title, vt, new_dt)
                    if not swap_record:
                        messagebox.showerror(
                            "入れ替え不可",
                            "変更先の枠に既存動画がありますが、その動画のupload_record.json/video_idが見つかりません。",
                            parent=edit,
                        )
                        return
                    confirm_text = (
                        "変更先の枠には既存動画があります。\n"
                        "2本の公開予定を入れ替えますか？\n\n"
                        f"移動する動画:\n{row['title']}\n{format_slot(row['dt'])} → {format_slot(new_dt)}\n\n"
                        f"入れ替え先の動画:\n{conflict_title}\n{format_slot(new_dt)} → {format_slot(row['dt'])}"
                    )
                    if not messagebox.askyesno("公開予定を入れ替え", confirm_text, parent=edit):
                        return
                else:
                    if not messagebox.askyesno(
                        "公開予定を変更",
                        f"YouTube側の公開予定も変更します。\n\n{row['title']}\n{format_slot(row['dt'])} → {format_slot(new_dt)}",
                        parent=edit,
                    ):
                        return

                def worker():
                    from core.youtube_uploader import update_video_publish_time
                    if conflict_title:
                        ok_swap = update_video_publish_time(swap_record.get("video_id"), row["dt"], progress_callback=self.log)
                        ok = update_video_publish_time(video_id, new_dt, progress_callback=self.log) if ok_swap else False
                    else:
                        ok_swap = True
                        ok = update_video_publish_time(video_id, new_dt, progress_callback=self.log)

                    def done():
                        if not ok_swap or not ok:
                            messagebox.showerror("変更失敗", "YouTube側の公開予定変更に失敗しました。ログを確認してください。", parent=edit)
                            return
                        record["publish_at"] = new_dt.isoformat()
                        record["publish_status"] = "scheduled"
                        if conflict_title:
                            swap_record["publish_at"] = row["dt"].isoformat()
                            swap_record["publish_status"] = "scheduled"
                        try:
                            self._write_upload_record_data(record_path, record)
                            if conflict_title:
                                self._write_upload_record_data(swap_record_path, swap_record)
                        except Exception as e:
                            self.log(f"  ⚠ upload_record.json更新失敗: {e}", "warning")
                        if conflict_title:
                            self.log(
                                f"✅ 公開予定を入れ替え: {row['title']} {format_slot(row['dt'])} → {format_slot(new_dt)} / "
                                f"{conflict_title} {format_slot(new_dt)} → {format_slot(row['dt'])}",
                                "success",
                            )
                        else:
                            self.log(f"✅ 公開予定を変更: {row['title']} {format_slot(row['dt'])} → {format_slot(new_dt)}", "success")
                        edit.destroy()
                        dialog.destroy()
                        self.show_upload_schedule_dialog(auto_sync=False)

                    self.root.after(0, done)

                threading.Thread(target=worker, daemon=True).start()

            btns2 = ttk.Frame(edit)
            btns2.pack(fill=tk.X, padx=12, pady=(0, 10))
            ttk.Button(btns2, text="キャンセル", command=edit.destroy).pack(side=tk.RIGHT)
            ttk.Button(btns2, text="変更する", style="Accent.TButton", command=apply_change).pack(side=tk.RIGHT, padx=(0, 8))

        def rebalance():
            future_count = sum(1 for r in rows if r[3] == "予定")
            if future_count == 0:
                messagebox.showinfo("スロット詰め直し", "詰め直し対象の予約スロットがありません。", parent=dialog)
                return
            if not messagebox.askyesno(
                "スロット詰め直し",
                f"未来の予約スロット {future_count} 件を現在から最速で詰め直します。\n\n"
                "YouTube側の公開予定時刻も自動で更新します。\nよろしいですか？",
                parent=dialog,
            ):
                return

            def worker():
                from core.upload_scheduler import count_rebalance_candidates, rebalance_slots_detailed
                from core.youtube_uploader import update_video_publish_time

                def type_label(vt):
                    return "Shorts" if vt == "shorts" else "Long"

                def fmt_iso(iso):
                    return iso[:16].replace("T", " ") if iso else "未設定"

                all_changes = []
                candidate_counts = {}
                try:
                    for vt in ("shorts", "long"):
                        candidate_counts[vt] = count_rebalance_candidates(vt)
                        changes = rebalance_slots_detailed(vt)
                        all_changes.extend([(vt, *c) for c in changes])
                except Exception as e:
                    self.root.after(0, lambda e=e: (
                        self.log(f"❌ スロット詰め直し失敗: {e}", "error"),
                        messagebox.showerror("エラー", str(e), parent=dialog),
                    ))
                    return

                if not all_changes:
                    self.root.after(0, lambda counts=candidate_counts: self.log(
                        f"📅 スロット詰め直し対象: Shorts {counts.get('shorts', 0)}件 / Long {counts.get('long', 0)}件、移動なし",
                        "info",
                    ))
                    self.root.after(0, lambda: messagebox.showinfo(
                        "スロット詰め直し", "すでに最速スロットに詰まっています。変更なし。", parent=dialog,
                    ))
                    return

                plan_lines = []
                for change in all_changes:
                    vt, old_iso, new_iso, title, _video_id, *_rest = change
                    plan_lines.append(f"  ・[{type_label(vt)}] {title[:45]}: {fmt_iso(old_iso)} → {fmt_iso(new_iso)}")
                self.root.after(0, lambda lines=plan_lines: (
                    self.log(f"📅 スロット詰め直し 移動予定: {len(lines)}件", "info"),
                    [self.log(line, "info") for line in lines],
                ))

                updated_yt = 0
                no_id = []
                for change in all_changes:
                    vt, old_iso, new_iso, title, video_id, *_rest = change
                    short_title = title[:30]
                    old_dt_str = fmt_iso(old_iso)
                    new_dt_str = fmt_iso(new_iso)
                    if not video_id:
                        no_id.append(short_title)
                        self.root.after(0, lambda label=type_label(vt), t=short_title, o=old_dt_str, n=new_dt_str: self.log(
                            f"  ⚠ [{label}] video_id未発見: {t} ({o} → {n})", "warning",
                        ))
                        continue
                    try:
                        new_dt = datetime.fromisoformat(new_iso)
                        ok = update_video_publish_time(video_id, new_dt, progress_callback=self.log)
                        if ok:
                            updated_yt += 1
                            self.root.after(0, lambda label=type_label(vt), t=short_title, o=old_dt_str, n=new_dt_str: self.log(
                                f"  ✅ [{label}] 移動完了: {t} ({o} → {n})", "success",
                            ))
                        else:
                            no_id.append(short_title)
                            self.root.after(0, lambda label=type_label(vt), t=short_title, o=old_dt_str, n=new_dt_str: self.log(
                                f"  ⚠ [{label}] YouTube未更新: {t} ({o} → {n})", "warning",
                            ))
                    except Exception as e:
                        no_id.append(short_title)
                        self.root.after(0, lambda label=type_label(vt), t=short_title, o=old_dt_str, n=new_dt_str, e=e: self.log(
                            f"  ❌ [{label}] YouTube更新失敗: {t} ({o} → {n}) / {e}", "error",
                        ))

                def done():
                    msg = f"YouTube更新: {updated_yt}/{len(all_changes)}件"
                    if no_id:
                        msg += f"\n⚠ YouTube未更新: {', '.join(no_id[:3])}"
                    self.log(msg, "success" if updated_yt else "warning")
                    dialog.destroy()
                    self.show_upload_schedule_dialog(auto_sync=False)

                self.root.after(0, done)

            threading.Thread(target=worker, daemon=True).start()

        def detect_manual_published():
            """予定スロットをYouTube APIで確認し、ローカルをYouTube側に同期する。
            ・public になっていた → 手動公開済みとして処理
            ・publishAt がローカルと異なる → ローカルスケジュールを YouTube 側に合わせる
            """
            if self._schedule_sync_running:
                self.log("YouTube同期はすでに実行中です。", "info")
                return
            # 全予定スロット（フィルター前の rows を使う）
            scheduled_rows_all = [r for r in rows if r[3] == "予定"]
            if not scheduled_rows_all:
                messagebox.showinfo("手動公開を検出", "確認対象の予約スロットがありません。", parent=dialog)
                return

            self._schedule_sync_running = True

            def worker():
                import json as _json
                from datetime import datetime, timedelta, timezone
                from core.youtube_uploader import get_video_statuses
                JST = timezone(timedelta(hours=9))

                # 予定スロットの video_id と record_path を取得
                id_to_info = {}  # video_id → {row, record, record_path}
                no_id_titles = []
                for dt, label, title, status, vt, iso, *_meta in scheduled_rows_all:
                    row_dict = {"dt": dt, "label": label, "title": title, "status": status, "video_type": vt, "iso": iso}
                    record, record_path = self._find_upload_record_for_schedule(title, vt, dt)
                    vid = record.get("video_id") if record else None
                    if vid:
                        id_to_info[vid] = {"row": row_dict, "record": record, "record_path": record_path}
                    else:
                        no_id_titles.append(title[:30])

                if no_id_titles:
                    self.root.after(0, lambda t=no_id_titles: self.log(
                        f"  ⚠ video_id未取得のスロット {len(t)}件をスキップ: {', '.join(t[:3])}", "warning"
                    ))

                if not id_to_info:
                    self.root.after(0, lambda: messagebox.showinfo(
                        "手動公開を検出", "video_idが取得できたスロットがありません。\nアップロード履歴を確認してください。", parent=dialog,
                    ))
                    self._schedule_sync_running = False
                    return

                self.root.after(0, lambda: self.log(f"🔍 YouTube APIでステータス確認中... ({len(id_to_info)}件)", "info"))
                try:
                    statuses = get_video_statuses(list(id_to_info.keys()))
                except Exception as e:
                    self.root.after(0, lambda e=e: (
                        self.log(f"❌ YouTube API エラー: {e}", "error"),
                        messagebox.showerror("エラー", str(e), parent=dialog),
                    ))
                    self._schedule_sync_running = False
                    return

                published_rows = []   # 手動公開済み
                time_mismatch = []    # publishAt がズレている (video_id, yt_iso, local_iso, title)

                for vid, st in statuses.items():
                    if vid not in id_to_info:
                        continue
                    info = id_to_info[vid]
                    row = info["row"]
                    privacy = st.get("privacyStatus")
                    yt_publish_at = st.get("publishAt")  # ISO8601 UTC 文字列 or None

                    if privacy == "public":
                        published_rows.append(info)
                    elif privacy == "private" and yt_publish_at:
                        # YouTube 側の publishAt を JST に変換して比較
                        try:
                            yt_dt = datetime.fromisoformat(yt_publish_at.replace("Z", "+00:00")).astimezone(JST)
                            local_dt = row["dt"]
                            # 1分以上ズレていたら不一致とみなす
                            if abs((yt_dt - local_dt).total_seconds()) >= 60:
                                time_mismatch.append((vid, yt_dt, row, info["record"], info["record_path"]))
                        except Exception:
                            pass

                if not published_rows and not time_mismatch:
                    self.root.after(0, lambda: self.log("✅ スケジュール同期チェック完了: 差異なし", "info"))
                    self._schedule_sync_running = False
                    return

                def apply_sync():
                    published_titles = []

                    for info in published_rows:
                        row = info["row"]
                        record = info.get("record")
                        record_path = info.get("record_path")
                        if record and record_path:
                            try:
                                record["publish_status"] = "published"
                                self._write_upload_record_data(record_path, record)
                            except Exception as e:
                                self.log(f"  ⚠ upload_record更新失敗: {e}", "warning")
                        if row["title"]:
                            published_titles.append(row["title"].strip())
                        self.log(f"  📢 手動公開済み検出: {row['title'][:35]}", "info")

                    for vid, yt_dt, row, record, record_path in time_mismatch:
                        vt = row["video_type"]
                        old_iso = row["iso"]
                        new_iso = yt_dt.isoformat()
                        if record and record_path:
                            try:
                                record["publish_at"] = new_iso
                                record["publish_status"] = "scheduled"
                                self._write_upload_record_data(record_path, record)
                            except Exception as e:
                                self.log(f"  ⚠ upload_record更新失敗: {e}", "warning")
                        self.log(f"  🔄 スロット時刻修正: {row['title'][:25]} {old_iso[:16]} → {new_iso[:16]}", "info")

                    added = 0
                    if published_titles:
                        added = self._append_uploaded_titles(published_titles)
                        self.refresh_history()

                    msgs = []
                    if published_rows:
                        msgs.append(f"手動公開済み処理: {len(published_rows)}件（履歴追記 {added}件）")
                    if time_mismatch:
                        msgs.append(f"スロット時刻修正: {len(time_mismatch)}件")
                    self.log("✅ " + " / ".join(msgs), "success")
                    dialog.destroy()
                    self._schedule_sync_running = False
                    self.show_upload_schedule_dialog(auto_sync=False)

                self.root.after(0, apply_sync)

            threading.Thread(target=worker, daemon=True).start()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=12, pady=(4, 10))
        ttk.Label(btn_frame, textvariable=count_var, font=("Meiryo", 8)).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="閉じる", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="選択を削除", command=delete_selected).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(btn_frame, text="手動公開済みにする", command=mark_manual_published).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(btn_frame, text="公開予定を変更", command=change_publish_time).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(btn_frame, text="スロット詰め直し", command=rebalance).pack(side=tk.RIGHT, padx=(0, 8))

        # YouTube status checks are intentionally manual; auto-sync already runs once on open.

    def _confirm_upload_schedule(self, rows):
        """rows: [(type_label, title, slot_str, score_label), ...] — True で確定、False でキャンセル。"""
        result = {"ok": False}

        dialog = tk.Toplevel(self.root)
        dialog.title("アップロードスケジュール確認")
        dialog.geometry("860x320")
        dialog.resizable(True, True)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="以下のスケジュールでアップロードします。確認してOKを押してください。",
                  font=("Meiryo", 9)).pack(anchor=tk.W, padx=12, pady=(10, 4))

        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        cols = ("#", "種別", "タイトル", "スコア", "予約日時")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=8)
        tree.heading("#",    text="#",    anchor=tk.CENTER)
        tree.heading("種別", text="種別", anchor=tk.CENTER)
        tree.heading("タイトル", text="タイトル", anchor=tk.W)
        tree.heading("スコア", text="スコア", anchor=tk.CENTER)
        tree.heading("予約日時", text="予約日時 (JST)", anchor=tk.CENTER)
        tree.column("#",    width=36,  stretch=False, anchor=tk.CENTER)
        tree.column("種別", width=60,  stretch=False, anchor=tk.CENTER)
        tree.column("タイトル", width=280, stretch=True, anchor=tk.W)
        tree.column("スコア", width=160, stretch=False, anchor=tk.CENTER)
        tree.column("予約日時", width=180, stretch=False, anchor=tk.CENTER)

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        for i, row in enumerate(rows, 1):
            label, title, slot_str = row[0], row[1], row[2]
            score_label = row[3] if len(row) > 3 else "-"
            slot_disp = slot_str.replace(" (JST)", "")
            tree.insert("", tk.END, values=(i, label, title, score_label, slot_disp))

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=12, pady=(4, 10))

        def do_ok():
            result["ok"] = True
            dialog.destroy()

        ttk.Button(btn_frame, text="キャンセル", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="OK・アップロード開始", style="Accent.TButton",
                   command=do_ok).pack(side=tk.RIGHT, padx=(0, 8))

        self.root.wait_window(dialog)
        return result["ok"]

    def _run_upload_batch(self, jobs):
        from core.upload_scheduler import format_slot
        total = len(jobs)
        try:
            for idx, (mp4_path, title, description, tags, thumb, output_dir, publish_at, video_type, fixed_comment) in enumerate(jobs, start=1):
                slot_str = format_slot(publish_at)
                label = "Shorts" if video_type == "shorts" else "Long"
                self.log(f"📤 アップロード [{idx}/{total}] [{label}]: {title}  →  {slot_str}", "batch")
                self._run_upload(mp4_path, title, description, tags, thumb, output_dir,
                                 publish_at=publish_at, video_type=video_type,
                                 fixed_comment=fixed_comment, restore_button=False)
            self.log(f"✅ YouTubeアップロード完了: {total}件", "success")
        finally:
            self.root.after(0, lambda: self.upload_btn.config(state=tk.NORMAL))
            self.root.after(0, self.refresh_history)

    def _open_studio(self):
        import webbrowser
        webbrowser.open(self._studio_url or "https://studio.youtube.com/")

    @staticmethod
    def _write_upload_record(output_dir, video_id, title, video_type, publish_at):
        """アップロード結果＋スコアを upload_record.json に書き込む。"""
        import json as _json
        from datetime import datetime, timezone

        meta_dir = os.path.join(output_dir, "_meta")

        def _read(name):
            p = os.path.join(meta_dir, name)
            if not os.path.exists(p):
                return {}
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return _json.load(f)
            except Exception:
                return {}

        opening = _read("opening_review.json")
        duration = _read("duration_review.json")
        final = _read("final_review.json")
        cta_policy = _read("cta_policy.json")
        render_info = _read("render_info.json")

        record = {
            "video_id": video_id,
            "title": title,
            "video_type": video_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "publish_at": publish_at.isoformat() if hasattr(publish_at, "isoformat") else str(publish_at) if publish_at else None,
            "publish_status": "scheduled" if publish_at else "private",
            "opening_score": opening.get("final_score"),
            "opening_status": opening.get("final_status"),
            "duration_sec": duration.get("seconds"),
            "duration_status": duration.get("status"),
            "final_score": final.get("final_score") if not final.get("skipped") and not final.get("error") else None,
            "publish_ok": final.get("publish_ok") if not final.get("skipped") and not final.get("error") else None,
            "risk": final.get("risk") if not final.get("skipped") and not final.get("error") else None,
            "must_fix": (final.get("must_fix") or []) if not final.get("skipped") and not final.get("error") else [],
            "render_engine": render_info.get("render_engine", ""),
        }
        if cta_policy:
            record.update(cta_policy)
        try:
            parser_items = ScriptParser.parse(os.path.join(output_dir, "script.txt"))
            script_meta = {
                it["type"]: it["text"]
                for it in parser_items
                if it["type"] in ScriptParser.META_TYPES
            }
            record.update({
                "generation_kind": script_meta.get("generation_kind", ""),
                "source_video_title": script_meta.get("source_video_title", ""),
                "generation_purpose": script_meta.get("generation_purpose", ""),
                "character_pattern": script_meta.get("character_pattern", ""),
                "genre_group": script_meta.get("genre_group", ""),
                "fixed_comment_text": script_meta.get("fixed_comment", ""),
            })
        except Exception:
            pass
        os.makedirs(meta_dir, exist_ok=True)
        path = os.path.join(meta_dir, "upload_record.json")
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(record, f, ensure_ascii=False, indent=2)
        return path

    def _run_upload(self, mp4_path, title, description, tags, thumb, output_dir,
                    publish_at=None, video_type="long", fixed_comment="", restore_button=True):
        try:
            from config import LONG_UPLOAD_PLAYLIST_NAME
            from core.youtube_uploader import add_video_to_playlist_by_name, upload_video, post_comment
            from core.upload_scheduler import mark_slot_used, format_slot
            title = self._strip_video_type_prefix(title)
            video_id = upload_video(mp4_path, title, description, tags,
                                    thumbnail_path=thumb, privacy="private",
                                    publish_at=publish_at,
                                    progress_callback=self.log)

            if video_id:
                self._studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
                if video_type == "long":
                    ab_manifest = record_uploaded_video_id_for_thumbnail_ab_test(output_dir, video_id)
                    if ab_manifest:
                        self.log(f"  thumbnail A/B manifest updated: {ab_manifest}", "success")
                if publish_at:
                    mark_slot_used(publish_at, title, video_type)
                    self.log(f"📅 予約登録: {format_slot(publish_at)}", "success")
                try:
                    rec_path = self._write_upload_record(output_dir, video_id, title, video_type, publish_at)
                    self.log(f"  📋 アップロード記録: {os.path.basename(rec_path)}", "info")
                except Exception as e:
                    rec_path = None
                    self.log(f"  ⚠ upload_record.json 書き込み失敗(無視): {e}")
                if video_type == "long" and LONG_UPLOAD_PLAYLIST_NAME:
                    self.log(f"  📚 再生リスト登録中: {LONG_UPLOAD_PLAYLIST_NAME}", "info")
                    playlist_result = add_video_to_playlist_by_name(
                        video_id,
                        LONG_UPLOAD_PLAYLIST_NAME,
                        progress_callback=self.log,
                    )
                    if playlist_result.get("ok"):
                        if playlist_result.get("skipped"):
                            self.log(f"  📚 再生リスト登録済み: {LONG_UPLOAD_PLAYLIST_NAME}", "info")
                        else:
                            self.log(f"  📚 再生リスト登録完了: {LONG_UPLOAD_PLAYLIST_NAME}", "success")
                    else:
                        self.log(
                            f"  ⚠ 再生リスト登録失敗: {LONG_UPLOAD_PLAYLIST_NAME} / {playlist_result.get('reason', '')}",
                            "warning",
                        )
                    try:
                        self._update_upload_record_fields(rec_path, {
                            "playlist_name": playlist_result.get("playlist_name"),
                            "playlist_id": playlist_result.get("playlist_id"),
                            "playlist_item_id": playlist_result.get("playlist_item_id"),
                            "playlist_added": bool(playlist_result.get("ok")),
                            "playlist_skipped": bool(playlist_result.get("skipped")),
                            "playlist_result": playlist_result.get("reason"),
                        })
                    except Exception as e:
                        self.log(f"  ⚠ 再生リスト結果の記録に失敗: {e}", "warning")
                # 固定コメント投稿は現在無効（APIエラーのため）
                # if fixed_comment:
                #     self.log("💬 固定コメントを投稿中...")
                #     comment_id = post_comment(video_id, fixed_comment, progress_callback=self.log)
                #     if comment_id:
                #         self.log("  ✅ コメント投稿完了（YouTube Studioでピン留めできます）", "success")

            # アップロード成功 → 000_uploaded/ へ移動（既に中にある場合はスキップ）
            if output_dir and os.path.exists(output_dir):
                uploaded_base = os.path.abspath(os.path.join("output", "000_uploaded"))
                abs_output = os.path.abspath(output_dir)
                if not abs_output.startswith(uploaded_base + os.sep):
                    os.makedirs(uploaded_base, exist_ok=True)
                    folder_name = os.path.basename(output_dir)
                    dest = os.path.join(uploaded_base, folder_name)
                    if os.path.exists(dest):
                        shutil.rmtree(dest)
                    shutil.move(output_dir, dest)
                    self.log(f"📦 アップロード済みフォルダへ移動: {folder_name}", "success")
                    # MP4 を削除（容量節約）
                    for f in os.listdir(dest):
                        if f.lower().endswith(".mp4"):
                            try:
                                os.remove(os.path.join(dest, f))
                                self.log(f"🗑 MP4 削除: {f}", "info")
                            except Exception:
                                pass
                    # タイトルログに追記（000_uploaded が消えても残るよう台帳ディレクトリに保存）
                    try:
                        self._append_uploaded_titles([folder_name])
                    except Exception:
                        pass
                    try:
                        removed_backups = self._cleanup_uploaded_backups(folder_name)
                        if removed_backups:
                            self.log(f"🧹 アップロード済みバックアップ削除: {removed_backups}件", "info")
                    except Exception as e:
                        self.log(f"  ⚠ バックアップ削除失敗: {e}", "warning")
                self.root.after(0, self.refresh_history)
        except Exception as e:
            self.log(f"❌ アップロードエラー: {e}", "error")
        finally:
            if restore_button:
                self.root.after(0, lambda: self.upload_btn.config(state=tk.NORMAL))

    def _read_meta_from_dir(self, output_dir):
        if not output_dir:
            return {}
        meta_candidates = [
            os.path.join(output_dir, "_meta", "metadata.txt"),
            os.path.join(output_dir, "metadata.txt"),
        ]
        meta_path = next((path for path in meta_candidates if os.path.exists(path)), None)
        if not meta_path:
            return {}
        with open(meta_path, "r", encoding="utf-8") as f:
            content = f.read()
        sections = [
            ("title", "【動画タイトル】"),
            ("thumbnail_text", "【サムネ文字】"),
            ("description", "【説明文】"),
            ("tags", "【タグ】"),
            ("generation_kind", "【生成区分】"),
            ("source_video_title", "【元動画】"),
            ("generation_purpose", "【目的】"),
            ("thumbnail", "【サムネイルプロンプト】"),
            ("fixed_comment", "【固定コメント】"),
        ]
        data = {}
        for i, (key, header) in enumerate(sections):
            start = content.find(header)
            if start == -1:
                continue
            start += len(header)
            end = len(content)
            for _, next_header in sections[i + 1:]:
                pos = content.find(next_header, start)
                if pos != -1 and pos < end:
                    end = pos
            data[key] = content[start:end].strip()

        script_path = os.path.join(output_dir, "script.txt")
        if os.path.exists(script_path):
            try:
                script_items = ScriptParser.parse(script_path)
                script_meta = {
                    it["type"]: it["text"]
                    for it in script_items
                    if it["type"] in ScriptParser.META_TYPES
                }
                data.setdefault("title", script_meta.get("video_title", ""))
                data.setdefault("thumbnail_text", script_meta.get("thumbnail_text", ""))
                data.setdefault("description", script_meta.get("description", ""))
                data.setdefault("tags", script_meta.get("tags", ""))
                data.setdefault("generation_kind", script_meta.get("generation_kind", ""))
                data.setdefault("source_video_title", script_meta.get("source_video_title", ""))
                data.setdefault("generation_purpose", script_meta.get("generation_purpose", ""))
                data.setdefault("character_pattern", script_meta.get("character_pattern", ""))
                data.setdefault("genre_group", script_meta.get("genre_group", ""))
                data.setdefault("thumbnail", script_meta.get("thumbnail", ""))
                data.setdefault("fixed_comment", script_meta.get("fixed_comment", ""))
            except Exception:
                pass
        title_ab_path = os.path.join(output_dir, "_meta", "title_ab_test.json")
        if not os.path.exists(title_ab_path):
            title_ab_path = os.path.join(output_dir, "title_ab_test.json")
        if os.path.exists(title_ab_path):
            try:
                import json
                with open(title_ab_path, "r", encoding="utf-8") as f:
                    title_ab = json.load(f)
                default_variant = title_ab.get("default_variant", "A")
                default_title = next(
                    (
                        item.get("title", "").strip()
                        for item in title_ab.get("title_variants", [])
                        if item.get("variant") == default_variant
                    ),
                    "",
                )
                if default_title:
                    data["title"] = default_title
            except Exception:
                pass
        return data

    @staticmethod
    def _read_score_label(output_dir):
        """output_dir の review JSON からスコアを短い文字列で返す。"""
        import json as _json
        if not output_dir:
            return ""
        _meta = os.path.join(output_dir, "_meta")

        def _read(name):
            p = os.path.join(_meta, name)
            if not os.path.exists(p):
                return {}
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return _json.load(f)
            except Exception:
                return {}

        parts = []
        opening = _read("opening_review.json")
        if opening:
            score = opening.get("final_score")
            if score is not None:
                parts.append(f"冒頭{score}")

        duration = _read("duration_review.json")
        if duration:
            sec = duration.get("seconds")
            status = duration.get("status", "")
            mark = "✅" if status == "ok" else "⚠"
            if sec is not None:
                parts.append(f"{sec}s{mark}")

        final = _read("final_review.json")
        if final and not final.get("skipped") and not final.get("error"):
            fscore = final.get("final_score")
            if fscore is not None:
                parts.append(f"最終{fscore}")

        return " / ".join(parts) if parts else "-"

    @staticmethod
    def _build_verdict_summary(output_dir):
        """opening/duration/final_review.json から総合判定サマリーを生成する。"""
        import json as _json
        if not output_dir:
            return ""
        lines = ["━━━━━━━━ 総合判定 ━━━━━━━━"]
        _meta = os.path.join(output_dir, "_meta")

        def _read(name):
            p = os.path.join(_meta, name)
            if not os.path.exists(p):
                return {}
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return _json.load(f)
            except Exception:
                return {}

        opening = _read("opening_review.json")
        duration = _read("duration_review.json")
        final = _read("final_review.json")

        if opening:
            score = opening.get("final_score", "?")
            status = opening.get("final_status", "")
            llm = opening.get("llm_review") or {}
            model_parts = []
            if llm.get("model"):
                model_parts.append(f"review:{llm.get('model')}")
            if llm.get("rewrite_accepted_model"):
                model_parts.append(f"rewrite:{llm.get('rewrite_accepted_model')}")
            model_text = f" / model {', '.join(model_parts)}" if model_parts else ""
            lines.append(f"冒頭スコア : {score}点 / {status}{model_text}")
            local = opening.get("local_review") or {}
            for iss in (local.get("issues") or [])[:2]:
                lines.append(f"  ・{iss}")

        if duration:
            sec = duration.get("seconds", "?")
            dur_status = duration_status_label(duration.get("status", ""))
            lines.append(f"尺         : {sec}秒 / {dur_status}")

        if final and not final.get("skipped") and not final.get("error"):
            fscore = final.get("final_score", "?")
            ok = final.get("publish_ok", "?")
            risk = final.get("risk", "?")
            lines.append(f"最終スコア : {fscore}点 / 投稿OK={ok} / リスク={risk}")
            must = final.get("must_fix") or []
            if must:
                lines.append("修正必須:")
                for m in must[:3]:
                    lines.append(f"  ・{m}")
            else:
                lines.append("修正必須: なし")

        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def finish_generation(self, message, report, is_error=False):
        self._toggle_ui(True)
        self.progress.config(mode='determinate', value=100 if not is_error else 0)

        if is_error:
            self.status_label.config(foreground="#ff5e57")
            self.status_var.set("❌ エラーにより停止しました")
            messagebox.showerror("エラー", f"生成に失敗しました:\n\n{message}")
        else:
            self.status_label.config(foreground="#05c46b")
            self.status_var.set("✅ すべての処理が完了しました")
            self.log("プロジェクト生成完了！", "success")
            self.refresh_history()

            summary = report.summary() if report else ""
            full_msg = f"{message}\n\n{summary}"

            project_path = None
            if "プロジェクト保存済み: " in message:
                project_path = message.split("プロジェクト保存済み: ")[1].strip()

            if project_path and os.path.exists(project_path):
                self.last_output_dir = os.path.dirname(project_path)

            # 補正済み script.txt をテキストエリアに反映
            if self.last_output_dir:
                script_path = os.path.join(self.last_output_dir, "script.txt")
                if os.path.exists(script_path):
                    with open(script_path, "r", encoding="utf-8") as f:
                        corrected = f.read()
                    self.ref_text.config(state=tk.NORMAL)
                    self.ref_text.delete("1.0", tk.END)
                    self.ref_text.insert("1.0", corrected)

            verdict = self._build_verdict_summary(self.last_output_dir)
            if verdict:
                full_msg = f"{verdict}\n\n{full_msg}"
            messagebox.showinfo("成功", full_msg)


    def start_image_review(self):
        selected = self.select_history_dialog("画像確認する履歴を選択", "画像確認", multi=False)
        if not selected:
            return
        output_dir = os.path.join("output", selected[0])
        self.last_output_dir = output_dir
        self.image_review_btn.config(state=tk.DISABLED)
        self.log(f"🔄 画像確認: {os.path.basename(output_dir)}")
        threading.Thread(
            target=self._run_image_review,
            args=(output_dir, self.debug_var.get(), self.style_var.get(), self.sd_size_var.get()),
            daemon=True,
        ).start()

    def _collect_image_review_specs(self, output_dir):
        specs = []
        script_path = os.path.join(output_dir, "script.txt")
        bg_dir = os.path.join(output_dir, "backgrounds")
        thumb_path = os.path.join(output_dir, "thumbnail.png")
        thumbs_dir = os.path.join(output_dir, "thumbnails")
        thumbs_thumb_path = os.path.join(thumbs_dir, "thumbnail.png")
        if not os.path.exists(thumb_path) and os.path.exists(thumbs_thumb_path):
            thumb_path = thumbs_thumb_path

        def _read_prompt_file(*paths):
            for path in paths:
                if path and os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            text = f.read().strip()
                        if text:
                            return text, path
                    except Exception:
                        pass
            return "", paths[0] if paths else ""

        script_content = ""
        is_shorts = os.path.basename(output_dir).startswith("[Shorts]")
        bg_prompts = []
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                script_content = f.read()
            tmp_items = ScriptParser.parse(script_path)
            meta = {it["type"]: it["text"] for it in tmp_items if it["type"] in ScriptParser.META_TYPES}
            is_shorts = meta.get("video_format", "").strip().lower() in ("shorts", "ショート", "short")
            items = normalize_background_order([it for it in tmp_items if it["type"] not in ScriptParser.META_TYPES])
            bg_prompts = [it.get("text", "").strip() for it in items if it["type"] == "background"]

        if os.path.exists(thumb_path):
            title = self._read_meta_from_dir(output_dir).get("title") or self._folder_name_to_title(os.path.basename(output_dir))
            ratio_tag = "縦9:16のショート動画" if is_shorts else "横16:9のワイドスクリーン"
            safe_zone = (
                "\nセーフゾーン（厳守）: 上下左右30%の範囲にはテキスト・文字・重要な要素を一切配置しないこと。"
            ) if is_shorts else ""
            prompt = (
                f"アスペクト比: {ratio_tag}。{safe_zone}\n"
                f"以下の台本を参考に、YouTubeサムネイル画像を生成してください。\n\n"
                f"{script_content or title}"
            )
            saved_prompt, prompt_file = _read_prompt_file(
                os.path.join(os.path.dirname(thumb_path), "thumbnail_prompt.txt"),
                os.path.join(output_dir, "thumbnail_prompt.txt"),
                os.path.join(thumbs_dir, "thumbnail_prompt.txt"),
            )
            specs.append({
                "kind": "thumbnail",
                "path": thumb_path,
                "prompt": saved_prompt or prompt,
                "prompt_file": prompt_file,
                "label": "サムネイル",
                "is_shorts": is_shorts,
            })

        if not is_shorts:
            title = self._read_meta_from_dir(output_dir).get("title") or self._folder_name_to_title(os.path.basename(output_dir))
            thumbnail_text = meta.get("thumbnail_text", "").strip() if "meta" in locals() else ""
            base_prompt = (
                "Aspect ratio: 16:9 landscape.\n"
                "Generate a YouTube long-video thumbnail from the script below.\n\n"
                f"{script_content or title}"
            )
            common_rules = (
                "\n\nLong video thumbnail A/B test rules: 16:9 landscape. "
                "Put the food large in the center. Place Zundamon at lower left and Shikoku Metan at lower right. "
                "Characters must be smaller than the food. Put 2-8 Japanese characters at the top center. "
                "Use white text, very thick black outline, drop shadow, bold gothic font, readable on smartphones."
            )
            if thumbnail_text:
                common_rules += f' Use this exact thumbnail text at the top center: "{thumbnail_text}".'
            variant_map = {v["variant"]: v for v in LONG_THUMBNAIL_VARIANTS}
            variant_files = []
            manifest_path = os.path.join(output_dir, "_meta", "thumbnail_ab_test.json")
            if os.path.exists(manifest_path):
                try:
                    import json
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    for item in manifest.get("thumbnail_variants", []):
                        filename = item.get("file")
                        variant = item.get("variant")
                        if filename and variant:
                            variant_files.append((variant, filename))
                except Exception:
                    pass
            if not variant_files:
                import glob
                _thumb_glob_dirs = [os.path.join(output_dir, "thumbnails"), output_dir]
                for path in sorted(p for d in _thumb_glob_dirs for p in glob.glob(os.path.join(d, "*_thumbnail_?.png"))):
                    stem = os.path.splitext(os.path.basename(path))[0]
                    variant = stem.rsplit("_", 1)[-1].upper()
                    if variant in variant_map:
                        variant_files.append((variant, os.path.basename(path)))
            seen_variants = set()
            for variant, filename in variant_files:
                if variant in seen_variants:
                    continue
                seen_variants.add(variant)
                path = os.path.join(output_dir, filename)
                if not os.path.exists(path):
                    path = os.path.join(thumbs_dir, filename)
                if not os.path.exists(path):
                    continue
                variant_info = variant_map.get(variant, {})
                default_prompt = f"{base_prompt}{common_rules}\n\n{variant_info.get('prompt', '')}"
                saved_prompt, prompt_file = _read_prompt_file(
                    os.path.join(os.path.dirname(path), f"thumbnail_{variant}_prompt.txt"),
                    os.path.join(output_dir, f"thumbnail_{variant}_prompt.txt"),
                    os.path.join(thumbs_dir, f"thumbnail_{variant}_prompt.txt"),
                )
                specs.append({
                    "kind": "thumbnail_variant",
                    "path": path,
                    "prompt": saved_prompt or default_prompt,
                    "prompt_file": prompt_file,
                    "label": f"thumbnail {variant}",
                    "variant": variant,
                    "is_shorts": False,
                })
            if seen_variants:
                specs = [
                    spec for spec in specs
                    if not (spec.get("kind") == "thumbnail" and spec.get("path") == thumb_path)
                ]

        if os.path.isdir(bg_dir):
            bg_files = sorted(
                f for f in os.listdir(bg_dir)
                if f.lower().endswith(".png") and f.lower().startswith("bg_")
            )
            for idx, filename in enumerate(bg_files):
                bg_prompt = bg_prompts[idx] if idx < len(bg_prompts) else ""
                prompt = (
                    f"以下の台本を参考に、「{bg_prompt or filename}」のシーンの背景画像を生成してください。\n\n"
                    f"【台本】\n{script_content}"
                )
                specs.append({
                    "kind": "background",
                    "path": os.path.join(bg_dir, filename),
                    "prompt": prompt,
                    "label": f"背景 {idx + 1}",
                    "scene": bg_prompt,
                    "is_shorts": is_shorts,
                })
        return specs

    def _run_image_review(self, output_dir, debug_mode=False, image_style="通常", sd_size_mode=False):
        try:
            specs = self._collect_image_review_specs(output_dir)
            if not specs:
                self.log("⚠ 確認できる画像が見つかりません。", "error")
                return

            while True:
                regen_set = self._run_on_ui_sync(lambda s=specs: self.confirm_images_bulk(s))
                if not regen_set:
                    break

                self.log(f"🔄 選択画像を再生成中: {len(regen_set)}枚", "batch")
                for idx in sorted(regen_set):
                    spec = specs[idx]
                    try:
                        before_hash = _file_digest(spec["path"])
                        width, height = (1080, 1920) if spec.get("is_shorts") else (1920, 1080)
                        img_gen = ImageGenerator(width=width, height=height, debug=debug_mode, image_style=image_style, sd_size_mode=sd_size_mode)
                        target_dir = os.path.dirname(spec["path"])
                        regen_stamp = time.strftime("%Y%m%d_%H%M%S")
                        regen_prompt = (
                            f"{spec['prompt']}\n\n"
                            f"【再生成指示】前回画像の単純な焼き直しにしない。構図、カメラ距離、主役の配置、"
                            f"背景小物、文字配置、色の印象を明確に変えた別案にする。"
                            f"再生成ID: {regen_stamp}-{idx}"
                        )
                        if spec["kind"] in ("thumbnail", "thumbnail_variant"):
                            char_refs = [p for p in THUMBNAIL_CHARACTER_PNGS.values() if os.path.exists(p)]
                            thumb_gen = ImageGenerator(width=width, height=height, debug=debug_mode, image_style="nanobanana2", sd_size_mode=sd_size_mode)
                            generated = thumb_gen.generate_background(
                                regen_prompt,
                                target_dir=target_dir,
                                raw=True,
                                reference_image_paths=char_refs or None,
                                fname=os.path.basename(spec["path"]),
                            )
                        else:
                            generated = img_gen.generate_background(
                                regen_prompt,
                                target_dir=target_dir,
                                raw=False,
                                fname=os.path.basename(spec["path"]),
                            )
                        if generated:
                            src = os.path.join(target_dir, generated)
                            if os.path.abspath(src) != os.path.abspath(spec["path"]):
                                shutil.copyfile(src, spec["path"])
                            try:
                                os.utime(spec["path"], None)
                            except OSError:
                                pass
                            if os.path.abspath(src) != os.path.abspath(spec["path"]):
                                try:
                                    os.remove(src)
                                except OSError:
                                    pass
                            if spec["kind"] == "thumbnail_variant" and spec.get("variant") == "A":
                                root_thumb = os.path.join(output_dir, "thumbnail.png")
                                shutil.copyfile(spec["path"], root_thumb)
                                try:
                                    os.utime(root_thumb, None)
                                except OSError:
                                    pass
                            # プロンプトをファイルに保存
                            try:
                                if spec["kind"] == "background":
                                    bg_stem = os.path.splitext(os.path.basename(spec["path"]))[0]
                                    prompt_file = os.path.join(target_dir, f"prompt_{bg_stem}.txt")
                                elif spec["kind"] == "thumbnail_variant":
                                    prompt_file = os.path.join(target_dir, f"thumbnail_{spec.get('variant', 'variant')}_prompt.txt")
                                else:
                                    prompt_file = os.path.join(target_dir, "thumbnail_prompt.txt")
                                with open(prompt_file, "w", encoding="utf-8") as pf:
                                    pf.write(regen_prompt)
                            except Exception:
                                pass
                            after_hash = _file_digest(spec["path"])
                            try:
                                updated_at = time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(spec["path"])))
                                size_kb = os.path.getsize(spec["path"]) // 1024
                            except OSError:
                                updated_at = "?"
                                size_kb = 0
                            if before_hash and after_hash and before_hash == after_hash:
                                self.log(f"  ⚠ 再生成後も画像内容が同一です: {spec['label']}", "warning")
                            else:
                                self.log(
                                    f"  ✅ 再生成: {spec['label']} ({updated_at} / {size_kb}KB / {after_hash[:8]})",
                                    "success",
                                )
                    except Exception as e:
                        self.log(f"  ❌ 再生成失敗: {spec['label']}: {e}", "error")

                specs = self._collect_image_review_specs(output_dir)

            self.log("✅ 画像確認完了", "success")
        except Exception as e:
            self.log(f"❌ 画像確認エラー: {e}", "error")
        finally:
            self.root.after(0, lambda: self.image_review_btn.config(state=tk.NORMAL))

    def confirm_images_bulk(self, specs):
        if not Image or not ImageTk or not specs:
            messagebox.showwarning("画像確認不可", "Pillow が利用できないため画像を表示できません。")
            return set()

        result = {"regen": set()}
        toggle_states = [False] * len(specs)
        btn_refs = {}

        # 各画像の実寸を取得し、最大高さ240pxに合わせたサイズを計算
        max_display_h = 240
        display_sizes = []
        for spec in specs:
            try:
                img = _load_image_copy(spec["path"])
                try:
                    w, h = img.size
                finally:
                    img.close()
                scale = max_display_h / h
                display_sizes.append((int(w * scale), int(h * scale)))
            except Exception:
                display_sizes.append((int(max_display_h * 16 / 9), max_display_h))

        cell_w = max(s[0] for s in display_sizes)
        cell_h = max(s[1] for s in display_sizes)

        dialog = tk.Toplevel(self.root)
        dialog.title(f"画像一括確認 ({len(specs)}枚)")
        dialog.transient(self.root)
        dialog.grab_set()

        screen_w = dialog.winfo_screenwidth()
        screen_h = dialog.winfo_screenheight()
        dialog_w = min((cell_w + 16) * len(specs) + 30, screen_w - 80)
        dialog_h = min(cell_h + 260, screen_h - 80)
        dialog.geometry(f"{dialog_w}x{dialog_h}")

        container = ttk.Frame(dialog)
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        canvas = tk.Canvas(container)
        scrollbar = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(xscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        inner = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_inner_configure(*_):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(e):
            canvas.itemconfig(canvas_window, height=e.height)

        inner.bind("<Configure>", on_inner_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        def _on_mousewheel(e):
            if canvas.winfo_exists():
                canvas.xview_scroll(-1 * (e.delta // 120), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        dialog.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        style = ttk.Style()
        style.configure("OK.TButton", foreground="green")
        style.configure("Regen.TButton", foreground="red")

        photo_refs = []

        def toggle(idx):
            toggle_states[idx] = not toggle_states[idx]
            btn_refs[idx].config(
                text="🔄 再生成" if toggle_states[idx] else "✅ OK",
                style="Regen.TButton" if toggle_states[idx] else "OK.TButton",
            )

        def show_enlarged(path):
            win = tk.Toplevel(dialog)
            win.title("拡大表示")
            win.transient(dialog)
            try:
                img = _load_image_copy(path)
                img.thumbnail((900, 900), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                img.close()
                lbl = tk.Label(win, image=photo)
                lbl.image = photo
                lbl.pack()
            except Exception as e:
                ttk.Label(win, text=f"読込失敗: {e}").pack(padx=20, pady=20)
            ttk.Button(win, text="閉じる", command=win.destroy).pack(pady=6)

        def edit_prompt(idx):
            spec = specs[idx]
            win = tk.Toplevel(dialog)
            win.title(f"プロンプト編集 - {spec.get('label', idx + 1)}")
            win.geometry("900x620")
            win.transient(dialog)
            win.grab_set()

            ttk.Label(
                win,
                text="このプロンプトで再生成します。必要な部分だけ手で変更してください。",
                font=("Meiryo", 9, "bold"),
            ).pack(anchor=tk.W, padx=10, pady=(10, 4))

            text = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Meiryo", 9))
            text.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)
            text.insert("1.0", spec.get("prompt", ""))

            btn_frame = ttk.Frame(win)
            btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

            def save_prompt():
                new_prompt = text.get("1.0", tk.END).strip()
                if not new_prompt:
                    messagebox.showwarning("プロンプト空", "プロンプトが空です。")
                    return
                spec["prompt"] = new_prompt
                prompt_file = spec.get("prompt_file")
                if prompt_file:
                    try:
                        os.makedirs(os.path.dirname(prompt_file), exist_ok=True)
                        with open(prompt_file, "w", encoding="utf-8") as f:
                            f.write(new_prompt)
                    except Exception as e:
                        self.log(f"  ⚠ プロンプト保存失敗: {e}", "warning")
                toggle_states[idx] = True
                btn_refs[idx].config(text="🔄 再生成", style="Regen.TButton")
                self.log(f"  ✏ サムネイルプロンプトを編集: {spec.get('label', idx + 1)}", "info")
                win.destroy()

            ttk.Button(btn_frame, text="キャンセル", command=win.destroy).pack(side=tk.RIGHT)
            ttk.Button(btn_frame, text="保存して再生成対象にする", command=save_prompt).pack(side=tk.RIGHT, padx=(0, 8))

        for idx, spec in enumerate(specs):
            cell = ttk.Frame(inner, relief=tk.RIDGE, borderwidth=1)
            cell.grid(row=0, column=idx, padx=5, pady=5, sticky="n")
            ttk.Label(cell, text=spec.get("label", f"画像 {idx + 1}"), font=("", 9, "bold")).pack()

            img_frame = ttk.Frame(cell, width=cell_w, height=cell_h)
            img_frame.pack_propagate(False)
            img_frame.pack()

            try:
                img = _load_image_copy(spec["path"])
                img.thumbnail((cell_w, cell_h), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                img.close()
                photo_refs.append(photo)
                lbl = ttk.Label(img_frame, image=photo, cursor="hand2", anchor="center")
                lbl.place(relx=0.5, rely=0.5, anchor="center")
                lbl.bind("<Button-1>", lambda e, p=spec["path"]: show_enlarged(p))
            except Exception:
                photo_refs.append(None)
                ttk.Label(img_frame, text="(読込失敗)", anchor="center").place(relx=0.5, rely=0.5, anchor="center")

            scene = spec.get("scene") or ""
            if scene:
                display_scene = scene if len(scene) <= 60 else scene[:58] + "…"
                ttk.Label(cell, text=display_scene, wraplength=cell_w, foreground="#0984e3").pack()
            try:
                file_info = (
                    f"{time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(spec['path'])))} / "
                    f"{os.path.getsize(spec['path']) // 1024}KB / {_file_digest(spec['path'])[:8]}"
                )
                ttk.Label(cell, text=file_info, font=("Meiryo", 8), foreground="#636e72").pack()
            except Exception:
                pass
            btn = ttk.Button(cell, text="✅ OK", style="OK.TButton", command=lambda i=idx: toggle(i))
            btn.pack(pady=4)
            btn_refs[idx] = btn
            if spec.get("kind") in ("thumbnail", "thumbnail_variant"):
                ttk.Button(cell, text="✏ プロンプト編集", command=lambda i=idx: edit_prompt(i)).pack(pady=(0, 4))

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=8)

        def do_ok():
            result["regen"] = set()
            dialog.destroy()

        def do_regen():
            result["regen"] = {i for i, selected in enumerate(toggle_states) if selected}
            dialog.destroy()

        ttk.Button(btn_frame, text="全部このままOK", command=do_ok).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_frame, text="選択した画像を再生成", command=do_regen).pack(side=tk.LEFT, padx=8)

        self.root.wait_window(dialog)
        return result["regen"]

    def _toggle_ui(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.generate_btn.config(state=state)
        self.native_generate_btn.config(state=state)
        self.llm_check_btn.config(state=state)
        self.history_batch_btn.config(state=state)
        self.cancel_btn.config(state=tk.DISABLED if enabled else tk.NORMAL)
        self.comment_btn.config(state=state)
        self.image_review_btn.config(state=state)
        self.native_render_history_btn.config(state=state)
        self.ref_text.config(state=state)
        if enabled: self.progress.stop()
        else: self.progress.start(10)

    _DOCUMENTS_SEARCH_DIR = r"C:\Users\benyb\OneDrive\Documents"

    def _find_and_move_mp4(self, output_dir, folder_name):
        """output_dir に MP4 がない場合、Documents から .ymmp と同名の MP4 を探して移動する。"""
        src = self._external_mp4_candidate(output_dir)
        if src:
            os.makedirs(output_dir, exist_ok=True)
            mp4_name = os.path.basename(src)
            dest = os.path.join(output_dir, mp4_name)
            shutil.move(src, dest)
            self.log(f"📦 MP4 を Documents から移動: {mp4_name}", "info")
            return dest
        return None

    def open_output_dir(self):
        out_dir = os.path.abspath("output")
        os.makedirs(out_dir, exist_ok=True)
        os.startfile(out_dir)

if __name__ == "__main__":
    root = tk.Tk()
    app = YMM4AutoGui(root)
    root.mainloop()
