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
from main import run_pipeline, regenerate_thumbnail_only, normalize_background_order
from core.ai_generator import AIGenerator
from core.image_generator import ImageGenerator
from core.ng_words import NG_WORD_PROMPT
from core.parser import ScriptParser
from core.script_prompts import build_vidiq_prompt
from config import VOICEVOX_URL, VOICEVOX_PATH
import requests

try:
    from PIL import Image, ImageTk
except Exception:
    Image = ImageTk = None

VIDIQ_PROMPT = build_vidiq_prompt()


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
            requests.get(url, timeout=0.8)
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

print(f"\n--- [System Startup Check] ---")
for n, u, p in [("VOICEVOX", VOICEVOX_URL, VOICEVOX_PATH)]:
    res = unified_check(n, u, p)
    c_status = f"[Conn: OK ({res['url']})]" if res['connected'] else "[Conn: ERR]"
    f_status = "[File: OK]" if res['file_ok'] else "[File: ERR]"
    print(f"{res['name']:<10}: {c_status:<35} {f_status}")
print(f"------------------------------\n")

class YMM4AutoGui:
    def __init__(self, root):
        self.root = root
        self.root.title("YMM4 Auto Video Factory")
        self.root.geometry("920x780")
        self.root.minsize(800, 620)
        self.root.configure(bg="#f5f7fa")

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
        ttk.Label(top_frame, text="🚀 YMM4 自動動画生成ファクトリー", style="Header.TLabel").pack(side=tk.LEFT)
        self.generate_btn = ttk.Button(top_frame, text="🎬 生成 🚀", style="Accent.TButton", command=self.start_generation)
        self.generate_btn.pack(side=tk.RIGHT, padx=(4, 0), ipady=4)
        self.cancel_btn = ttk.Button(top_frame, text="作業中止", command=self.request_cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(top_frame, text="AI台本作成", command=self.copy_vidiq_prompt).pack(side=tk.RIGHT)
        ttk.Button(top_frame, text="クリア", width=6, command=self.clear_script).pack(side=tk.RIGHT, padx=4)

        # Script area
        self.ref_text = scrolledtext.ScrolledText(main_frame, height=6, font=("Consolas", 10), bg="#fdfdfd", borderwidth=1, relief="solid", highlightthickness=1, highlightbackground="#dfe6e9", highlightcolor="#0984e3")
        self.ref_text.pack(fill=tk.X, expand=False, pady=(0, 4))

        # Options row (all in one line)
        opt_frame = ttk.Frame(main_frame)
        opt_frame.pack(fill=tk.X, pady=2)

        self.auto_open_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="完成後に開く", variable=self.auto_open_var).pack(side=tk.LEFT, padx=4)

        self.debug_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="デバッグ", variable=self.debug_var).pack(side=tk.LEFT, padx=4)

        self.reuse_bg_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="背景再利用", variable=self.reuse_bg_var).pack(side=tk.LEFT, padx=4)

        self.batch_api_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="Batch API", variable=self.batch_api_var).pack(side=tk.LEFT, padx=4)

        ttk.Label(opt_frame, text="画風:").pack(side=tk.LEFT, padx=(12, 2))
        self.style_var = tk.StringVar(value="nanobanana2")
        self.style_combo = ttk.Combobox(opt_frame, textvariable=self.style_var, values=["nanobanana2", "nanobanana pro"], state="readonly", width=14)
        self.style_combo.pack(side=tk.LEFT, padx=2)

        self.history_batch_btn = ttk.Button(opt_frame, text="履歴から複数生成", command=self.open_history_batch_dialog)
        self.history_batch_btn.pack(side=tk.LEFT, padx=(10, 0))

        # Sub buttons row
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 4))
        self.upload_btn = ttk.Button(btn_frame, text="📤 YouTubeアップ", command=self.start_youtube_upload)
        self.upload_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.open_folder_btn = ttk.Button(btn_frame, text="📁 出力フォルダを開く", command=self.open_output_dir)
        self.open_folder_btn.pack(side=tk.LEFT)
        self.regen_thumb_btn = ttk.Button(btn_frame, text="🖼 サムネ再生成", command=self.start_regen_thumbnail)
        self.regen_thumb_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.image_review_btn = ttk.Button(btn_frame, text="🔄 画像確認", command=self.start_image_review)
        self.image_review_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._studio_url = None
        self.studio_btn = ttk.Button(btn_frame, text="🌐 YouTube Studio", command=self._open_studio)
        self.studio_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.schedule_btn = ttk.Button(btn_frame, text="📅 スケジュール", command=self.show_upload_schedule_dialog)
        self.schedule_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.copy_titles_btn = ttk.Button(btn_frame, text="📋 タイトル一覧コピー", command=self.copy_titles_to_clipboard)
        self.copy_titles_btn.pack(side=tk.LEFT, padx=(8, 0))


        # Metadata preview
        ttk.Label(main_frame, text="メタデータ:").pack(anchor=tk.W)
        self.meta_preview = scrolledtext.ScrolledText(main_frame, height=4, font=("Meiryo", 8), bg="#fdfdfd", borderwidth=1, relief="solid", state=tk.DISABLED)
        self.meta_preview.pack(fill=tk.X, pady=(2, 4))

        # Status + progress
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(main_frame, textvariable=self.status_var, font=("Meiryo", 8, "italic"))
        self.status_label.pack(anchor=tk.W)
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill=tk.X, pady=(2, 4))

        # Log（最下部・残りスペースを埋める）
        ttk.Label(main_frame, text="実行ログ:").pack(anchor=tk.W)
        self.log_area = scrolledtext.ScrolledText(main_frame, height=6, font=("Meiryo", 9), bg="#1e272e", fg="#d2dae2")
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.log_area.tag_config("info", foreground="#00d8d6")
        self.log_area.tag_config("error", foreground="#ff5e57")
        self.log_area.tag_config("success", foreground="#05c46b")
        self.log_area.tag_config("batch", foreground="#ef57ff", font=("Meiryo", 9, "bold"))

        self.last_output_dir = None
        self.cancel_event = threading.Event()

        self.refresh_history()
        threading.Thread(target=self.check_engines_startup, daemon=True).start()

    def check_engines_startup(self):
        self.log("--- システム接続確認 ---")
        ai = AIGenerator(debug=self.debug_var.get())
        g_status = "接続OK (Gemini / Nano Banana)" if ai.client else "未設定 (configを確認してください)"
        self.log(f"Google AI : {g_status}", "info" if ai.client else "error")

        for n, u, p in [("VOICEVOX", VOICEVOX_URL, VOICEVOX_PATH)]:
            res = unified_check(n, u, p)
            status = "OK" if res['connected'] else "ERR"
            style = "success" if res['connected'] else "error"
            self.log(f"{res['name']:<10}: {status} ({res['url']})", style)
        self.log("----------------------")

    def copy_vidiq_prompt(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(VIDIQ_PROMPT + "\n\n" + NG_WORD_PROMPT)
        self.root.update()
        self.log("VidIQプロンプトをクリップボードにコピーしました ✅", "success")

    def clear_script(self):
        self.ref_text.delete("1.0", tk.END)
        self.log("台本をクリアしました")

    def request_cancel(self):
        self.cancel_event.set()
        self.cancel_btn.config(state=tk.DISABLED)
        self.log("⏹ 作業中止をリクエストしました。現在の処理区切りで停止します。", "error")

    def log(self, message, tag="info"):
        self.root.after(0, lambda: self._log_ui(message, tag))

    def _log_ui(self, message, tag):
        self.log_area.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n", tag)
        if int(self.log_area.index("end-1c").split(".")[0]) > 500:
            self.log_area.delete("1.0", "101.0")
        self.log_area.see(tk.END)
        self.status_var.set(message)

    def refresh_history(self):
        if not os.path.exists("output"): os.makedirs("output", exist_ok=True)
        history = [d for d in os.listdir("output") if os.path.isdir(os.path.join("output", d)) and d != "000_uploaded"]
        history.sort(key=lambda d: os.path.getmtime(os.path.join("output", d)), reverse=True)
        self.history_items = history

    def copy_titles_to_clipboard(self):
        self.refresh_history()
        histories = getattr(self, "history_items", [])
        if not histories:
            messagebox.showinfo("タイトルなし", "出力フォルダに動画がありません。")
            return
        # フォルダ名から [Shorts] などのプレフィックスを除いたタイトルを列挙
        titles = []
        for name in histories:
            title = name
            for prefix in ("[Shorts]", "[Long]", "[SHORT]", "[LONG]"):
                if title.startswith(prefix):
                    title = title[len(prefix):].strip()
                    break
            titles.append(title)
        text = "\n".join(titles)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.log(f"📋 タイトル {len(titles)} 件をクリップボードにコピーしました")

    def open_history_batch_dialog(self):
        self.refresh_history()
        histories = getattr(self, "history_items", [])
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
            history_list.insert(tk.END, f"{edited_at}  {name}{suffix}")

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

        # 全スクリプトを処理開始前に一括バリデーション
        errors = []
        for i, script in enumerate(scripts, 1):
            items = ScriptParser.parse_string(script)
            is_valid, messages = ScriptParser.validate(items)
            if not is_valid:
                prefix = f"[台本{i}] " if len(scripts) > 1 else ""
                errors.extend(f"{prefix}{m}" for m in messages if not m.startswith("⚠"))
        if errors:
            messagebox.showerror("台本形式エラー", "\n".join(errors))
            return

        self._toggle_ui(False)
        self.cancel_event.clear()
        self.log(f"履歴一括処理開始: 合計 {len(scripts)} 件", "batch")
        threading.Thread(target=self._run_batch, args=(scripts,), daemon=True).start()

    def select_history_dialog(self, title, action_text, multi=False):
        self.refresh_history()
        histories = getattr(self, "history_items", [])
        if not histories:
            messagebox.showinfo("履歴なし", "選択できる履歴がありません。")
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
                os.path.exists(os.path.join(output_dir, "thumbnail.png"))
                or os.path.isdir(os.path.join(output_dir, "backgrounds"))
            ) else "  (画像なし)"
            mp4_suffix = "" if any(f.lower().endswith(".mp4") for f in os.listdir(output_dir)) else "  (MP4なし)"
            history_list.insert(tk.END, f"{edited_at}  {name}{script_suffix}{image_suffix}{mp4_suffix}")

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

    def start_generation(self):
        from core.parser import ScriptParser
        raw_scripts = self.ref_text.get("1.0", tk.END).strip()
        scripts = split_input_scripts(raw_scripts)

        if not scripts:
            messagebox.showwarning("Error", "台本を入力してください")
            return

        # 全スクリプトを処理開始前に一括バリデーション
        errors = []
        for i, script in enumerate(scripts, 1):
            items = ScriptParser.parse_string(script)
            is_valid, messages = ScriptParser.validate(items)
            if not is_valid:
                prefix = f"[台本{i}] " if len(scripts) > 1 else ""
                errors.extend(f"{prefix}{m}" for m in messages if not m.startswith("⚠"))
        if errors:
            messagebox.showerror("台本形式エラー", "\n".join(errors))
            return

        self._toggle_ui(False)
        self.cancel_event.clear()
        self.log(f"一括処理開始: 合計 {len(scripts)} 件")
        threading.Thread(target=self._run_batch, args=(scripts,), daemon=True).start()

    def _run_batch(self, scripts):
        count = len(scripts)
        is_batch = count > 1

        for idx, script in enumerate(scripts):
            if self.cancel_event.is_set():
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
                    self.root.after(0, lambda v=int((idx/count)*100): self.progress.config(value=v))

                msg, report = run_pipeline(
                    topic,
                    pregenerated_script=script,
                    debug_mode=self.debug_var.get(),
                    image_style=self.style_var.get(),
                    progress_callback=self.log,
                    reuse_backgrounds=self.reuse_bg_var.get(),
                    use_batch_api=self.batch_api_var.get(),
                    cancel_event=self.cancel_event,
                )

                self.log(f"成功: {topic}", "success")
                if self.cancel_event.is_set():
                    self.log("⏹ 中止しました。残りの履歴/台本は処理しません。", "error")
                    break
                if not is_batch:
                    self.root.after(0, lambda m=msg, r=report: self.finish_generation(m, r))
                    return

            except Exception as e:
                err_msg = str(e)
                if self.debug_var.get():
                    self.log(traceback.format_exc(), "error")
                self.log(f"❌ エラー: {err_msg}", "error")
                if not is_batch:
                    self.root.after(0, lambda m=err_msg: self.finish_generation(m, None, is_error=True))
                    return

        if self.cancel_event.is_set():
            self.root.after(0, lambda: self.progress.config(value=100))
            self.log("\n⏹ 処理を中止しました。", "error")
            if is_batch:
                messagebox.showinfo("中止", "一括処理を中止しました。")
            self.root.after(0, lambda: self._toggle_ui(True))
        elif is_batch:
            self.root.after(0, lambda: self.progress.config(value=100))
            self.log("\n✅ 全ての一括処理が完了しました！", "success")
            messagebox.showinfo("一括完了", f"{count}件の処理が完了しました。")
            self.root.after(0, lambda: self._toggle_ui(True))

    def _update_meta_preview(self):
        if not self.last_output_dir:
            return
        meta_path = os.path.join(self.last_output_dir, "metadata.txt")
        if not os.path.exists(meta_path):
            return
        with open(meta_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.meta_preview.config(state=tk.NORMAL)
        self.meta_preview.delete("1.0", tk.END)
        self.meta_preview.insert("1.0", content)
        self.meta_preview.config(state=tk.DISABLED)


    def start_youtube_upload(self):
        selected = self.select_history_dialog("YouTubeアップロードする履歴を選択", "アップロード", multi=True)
        if not selected:
            return

        base_jobs = []
        skipped = []
        for name in selected:
            output_dir = os.path.join("output", name)
            mp4_candidates = [
                os.path.join(output_dir, f)
                for f in os.listdir(output_dir)
                if f.lower().endswith(".mp4")
            ] if os.path.isdir(output_dir) else []
            if not mp4_candidates:
                skipped.append(name)
                continue
            mp4_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            mp4_path = mp4_candidates[0]

            meta = self._read_meta_from_dir(output_dir)
            title = meta.get("title", os.path.basename(output_dir))
            description = meta.get("description", "")
            tags = meta.get("tags", "")
            is_shorts = os.path.basename(output_dir).startswith("[Shorts]")
            thumb = None if is_shorts else os.path.join(output_dir, "thumbnail.png")
            base_jobs.append((mp4_path, title, description, tags, thumb, output_dir))

        if skipped:
            self.log(f"⚠ MP4なしの履歴をスキップ: {len(skipped)}件", "error")
        if not base_jobs:
            messagebox.showwarning("MP4なし", "選択した履歴フォルダにアップロード可能なMP4がありません。")
            return

        # Shorts / Long をタイプ別にスロット割り当て
        from core.upload_scheduler import assign_slots, format_slot

        shorts_jobs = [(j, "shorts") for j in base_jobs if os.path.basename(j[5]).startswith("[Shorts]")]
        long_jobs   = [(j, "long")   for j in base_jobs if not os.path.basename(j[5]).startswith("[Shorts]")]

        shorts_slots = assign_slots(len(shorts_jobs), "shorts")
        long_slots   = assign_slots(len(long_jobs),   "long")

        # (job, video_type, slot) を結合して元の選択順に並べ替え
        slot_map = {}
        for (j, vt), slot in zip(shorts_jobs, shorts_slots):
            slot_map[id(j)] = (vt, slot)
        for (j, vt), slot in zip(long_jobs, long_slots):
            slot_map[id(j)] = (vt, slot)

        # 確認ダイアログ
        rows = []
        for j in base_jobs:
            vt, slot = slot_map[id(j)]
            rows.append(("Shorts" if vt == "shorts" else "Long", j[1], format_slot(slot)))
        if not self._confirm_upload_schedule(rows):
            return

        jobs = [
            (mp4, title, desc, tags, thumb, output_dir, slot_map[id(j)][1], slot_map[id(j)][0])
            for j in base_jobs
            for mp4, title, desc, tags, thumb, output_dir in [j]
        ]

        self.upload_btn.config(state=tk.DISABLED)
        threading.Thread(
            target=self._run_upload_batch,
            args=(jobs,),
            daemon=True
        ).start()

    def show_upload_schedule_dialog(self):
        from core.upload_scheduler import list_schedule, format_slot
        from datetime import datetime, timedelta, timezone
        JST = timezone(timedelta(hours=9))
        now = datetime.now(JST)

        # Shorts / Long を統合してソート
        schedule = list_schedule()
        rows = []
        for vt, entries in schedule.items():
            label = "Shorts" if vt == "shorts" else "Long"
            for iso, title in entries.items():
                try:
                    dt = datetime.fromisoformat(iso)
                except ValueError:
                    continue
                status = "済" if dt < now else "予定"
                rows.append((dt, label, title.split("\n")[0], status))
        rows.sort(key=lambda r: r[0])

        dialog = tk.Toplevel(self.root)
        dialog.title("アップロードスケジュール")
        dialog.geometry("780x420")
        dialog.resizable(True, True)
        dialog.transient(self.root)

        ttk.Label(dialog, text="アップロード済み・予約中のスケジュール一覧",
                  font=("Meiryo", 9, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 4))

        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        cols = ("日時", "種別", "タイトル", "状態")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=14)
        tree.heading("日時",   text="予約日時 (JST)", anchor=tk.CENTER)
        tree.heading("種別",   text="種別",           anchor=tk.CENTER)
        tree.heading("タイトル", text="タイトル",     anchor=tk.W)
        tree.heading("状態",   text="状態",           anchor=tk.CENTER)
        tree.column("日時",    width=160, stretch=False, anchor=tk.CENTER)
        tree.column("種別",    width=60,  stretch=False, anchor=tk.CENTER)
        tree.column("タイトル", width=440, stretch=True,  anchor=tk.W)
        tree.column("状態",    width=48,  stretch=False, anchor=tk.CENTER)

        tree.tag_configure("done",     foreground="#aaaaaa", background="#f5f5f5")
        tree.tag_configure("upcoming", foreground="#0984e3", font=("Meiryo", 9, "bold"))

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        for dt, label, title, status in rows:
            dt_str = dt.strftime("%Y/%m/%d %H:%M")
            tag = "done" if status == "済" else "upcoming"
            tree.insert("", tk.END, values=(dt_str, label, title, status), tags=(tag,))

        # 削除ボタン
        def delete_selected():
            sel = tree.selection()
            if not sel:
                return
            if not messagebox.askyesno("削除確認", f"{len(sel)}件のスケジュールを削除しますか？", parent=dialog):
                return
            from core.upload_scheduler import _load, _save
            schedules = {vt: _load(vt) for vt in ("shorts", "long")}
            for item in sel:
                vals = tree.item(item, "values")
                dt_str, label = vals[0], vals[1]
                vt = "shorts" if label == "Shorts" else "long"
                # ISO キーを再構築
                try:
                    dt = datetime.strptime(dt_str, "%Y/%m/%d %H:%M").replace(tzinfo=JST)
                    schedules[vt].pop(dt.isoformat(), None)
                except Exception:
                    pass
                tree.delete(item)
            for vt, data in schedules.items():
                _save(data, vt)
            self.log(f"🗑 スケジュール {len(sel)}件を削除しました", "info")

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=12, pady=(4, 10))
        ttk.Label(btn_frame, text=f"合計 {len(rows)} 件  /  予定 {sum(1 for r in rows if r[3]=='予定')} 件  /  済 {sum(1 for r in rows if r[3]=='済')} 件",
                  font=("Meiryo", 8)).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="閉じる", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="選択を削除", command=delete_selected).pack(side=tk.RIGHT, padx=(0, 8))

    def _confirm_upload_schedule(self, rows):
        """rows: [(type_label, title, slot_str), ...] — True で確定、False でキャンセル。"""
        result = {"ok": False}

        dialog = tk.Toplevel(self.root)
        dialog.title("アップロードスケジュール確認")
        dialog.geometry("700x320")
        dialog.resizable(True, True)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="以下のスケジュールでアップロードします。確認してOKを押してください。",
                  font=("Meiryo", 9)).pack(anchor=tk.W, padx=12, pady=(10, 4))

        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        cols = ("#", "種別", "タイトル", "予約日時")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=8)
        tree.heading("#",    text="#",    anchor=tk.CENTER)
        tree.heading("種別", text="種別", anchor=tk.CENTER)
        tree.heading("タイトル", text="タイトル", anchor=tk.W)
        tree.heading("予約日時", text="予約日時 (JST)", anchor=tk.CENTER)
        tree.column("#",    width=36,  stretch=False, anchor=tk.CENTER)
        tree.column("種別", width=60,  stretch=False, anchor=tk.CENTER)
        tree.column("タイトル", width=340, stretch=True, anchor=tk.W)
        tree.column("予約日時", width=180, stretch=False, anchor=tk.CENTER)

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        for i, (label, title, slot_str) in enumerate(rows, 1):
            # 予約日時から (JST) を除いて表示
            slot_disp = slot_str.replace(" (JST)", "")
            tree.insert("", tk.END, values=(i, label, title, slot_disp))

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
            for idx, (mp4_path, title, description, tags, thumb, output_dir, publish_at, video_type) in enumerate(jobs, start=1):
                slot_str = format_slot(publish_at)
                label = "Shorts" if video_type == "shorts" else "Long"
                self.log(f"📤 アップロード [{idx}/{total}] [{label}]: {title}  →  {slot_str}", "batch")
                self._run_upload(mp4_path, title, description, tags, thumb, output_dir,
                                 publish_at=publish_at, video_type=video_type, restore_button=False)
            self.log(f"✅ YouTubeアップロード完了: {total}件", "success")
        finally:
            self.root.after(0, lambda: self.upload_btn.config(state=tk.NORMAL))
            self.root.after(0, self.refresh_history)

    def _open_studio(self):
        import webbrowser
        webbrowser.open(self._studio_url or "https://studio.youtube.com/")

    def _run_upload(self, mp4_path, title, description, tags, thumb, output_dir,
                    publish_at=None, video_type="long", restore_button=True):
        try:
            from core.youtube_uploader import upload_video
            from core.upload_scheduler import mark_slot_used, format_slot
            video_id = upload_video(mp4_path, title, description, tags,
                                    thumbnail_path=thumb, privacy="private",
                                    publish_at=publish_at,
                                    progress_callback=self.log)

            if video_id:
                self._studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
                if publish_at:
                    mark_slot_used(publish_at, title, video_type)
                    self.log(f"📅 予約登録: {format_slot(publish_at)}", "success")

            # アップロード成功 → 000_uploaded/ へ移動（既に中にある場合はスキップ）
            if output_dir and os.path.exists(output_dir):
                uploaded_base = os.path.abspath(os.path.join("output", "000_uploaded"))
                abs_output = os.path.abspath(output_dir)
                if not abs_output.startswith(uploaded_base + os.sep):
                    os.makedirs(uploaded_base, exist_ok=True)
                    dest = os.path.join(uploaded_base, os.path.basename(output_dir))
                    if os.path.exists(dest):
                        shutil.rmtree(dest)
                    shutil.move(output_dir, dest)
                    self.log(f"📦 アップロード済みフォルダへ移動: {os.path.basename(output_dir)}", "success")
                self.root.after(0, self.refresh_history)
        except Exception as e:
            self.log(f"❌ アップロードエラー: {e}", "error")
        finally:
            if restore_button:
                self.root.after(0, lambda: self.upload_btn.config(state=tk.NORMAL))

    def _read_meta_from_dir(self, output_dir):
        if not output_dir:
            return {}
        meta_path = os.path.join(output_dir, "metadata.txt")
        if not os.path.exists(meta_path):
            return {}
        with open(meta_path, "r", encoding="utf-8") as f:
            content = f.read()
        sections = [
            ("title", "【動画タイトル】"),
            ("thumbnail_text", "【サムネ文字】"),
            ("description", "【説明文】"),
            ("tags", "【タグ】"),
            ("thumbnail", "【サムネイルプロンプト】"),
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
        return data

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

            self._update_meta_preview()

            # 補正済み script.txt をテキストエリアに反映
            if self.last_output_dir:
                script_path = os.path.join(self.last_output_dir, "script.txt")
                if os.path.exists(script_path):
                    with open(script_path, "r", encoding="utf-8") as f:
                        corrected = f.read()
                    self.ref_text.config(state=tk.NORMAL)
                    self.ref_text.delete("1.0", tk.END)
                    self.ref_text.insert("1.0", corrected)

            messagebox.showinfo("成功", full_msg)


    def start_regen_thumbnail(self):
        output_dir = self.last_output_dir
        if not output_dir or not os.path.exists(output_dir):
            messagebox.showwarning("エラー", "対象フォルダが選択されていません。履歴から選択してください。")
            return
        self.regen_thumb_btn.config(state=tk.DISABLED)
        self.log(f"🖼 サムネイル再生成開始: {os.path.basename(output_dir)}")
        threading.Thread(target=self._run_regen_thumbnail, args=(output_dir,), daemon=True).start()

    def _run_regen_thumbnail(self, output_dir):
        try:
            thumb_path = regenerate_thumbnail_only(
                output_dir,
                image_style=self.style_var.get(),
                debug=self.debug_var.get(),
                progress_callback=self.log,
            )
            self.log(f"✅ サムネイル保存: {thumb_path}", "success")
        except Exception as e:
            self.log(f"❌ サムネイル再生成エラー: {e}", "error")
        finally:
            self.root.after(0, lambda: self.regen_thumb_btn.config(state=tk.NORMAL))

    def start_image_review(self):
        selected = self.select_history_dialog("画像確認する履歴を選択", "画像確認", multi=False)
        if not selected:
            return
        output_dir = os.path.join("output", selected[0])
        self.last_output_dir = output_dir
        self.image_review_btn.config(state=tk.DISABLED)
        self.log(f"🔄 画像確認: {os.path.basename(output_dir)}")
        threading.Thread(target=self._run_image_review, args=(output_dir,), daemon=True).start()

    def _collect_image_review_specs(self, output_dir):
        specs = []
        script_path = os.path.join(output_dir, "script.txt")
        bg_dir = os.path.join(output_dir, "backgrounds")
        thumb_path = os.path.join(output_dir, "thumbnail.png")

        script_content = ""
        is_shorts = os.path.basename(output_dir).startswith("[Shorts]")
        bg_prompts = []
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                script_content = f.read()
            tmp_items = ScriptParser.parse(script_path)
            meta_types = {"thumbnail", "video_title", "description", "tags", "video_format"}
            meta = {it["type"]: it["text"] for it in tmp_items if it["type"] in meta_types}
            is_shorts = meta.get("video_format", "").strip().lower() in ("shorts", "ショート", "short")
            items = normalize_background_order([it for it in tmp_items if it["type"] not in meta_types])
            bg_prompts = [it.get("text", "").strip() for it in items if it["type"] == "background"]

        if os.path.exists(thumb_path):
            title = self._read_meta_from_dir(output_dir).get("title", os.path.basename(output_dir))
            prompt = (
                f"以下の台本を参考に、YouTubeサムネイル画像を生成してください。\n\n"
                f"{script_content or title}"
            )
            specs.append({
                "kind": "thumbnail",
                "path": thumb_path,
                "prompt": prompt,
                "label": "サムネイル",
                "is_shorts": is_shorts,
            })

        if os.path.isdir(bg_dir):
            bg_files = sorted(
                f for f in os.listdir(bg_dir)
                if f.startswith("bg_") and f.lower().endswith(".png")
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

    def _run_image_review(self, output_dir):
        try:
            specs = self._collect_image_review_specs(output_dir)
            if not specs:
                self.log("⚠ 確認できる画像が見つかりません。", "error")
                return

            while True:
                regen_set = self.confirm_images_bulk(specs)
                if not regen_set:
                    break

                self.log(f"🔄 選択画像を再生成中: {len(regen_set)}枚", "batch")
                for idx in sorted(regen_set):
                    spec = specs[idx]
                    try:
                        width, height = (1080, 1920) if spec.get("is_shorts") else (1920, 1080)
                        img_gen = ImageGenerator(width=width, height=height, debug=self.debug_var.get(), image_style=self.style_var.get())
                        target_dir = os.path.dirname(spec["path"])
                        generated = img_gen.generate_background(
                            spec["prompt"],
                            target_dir=target_dir,
                            raw=(spec["kind"] == "thumbnail"),
                        )
                        if generated:
                            src = os.path.join(target_dir, generated)
                            shutil.copy2(src, spec["path"])
                            if os.path.abspath(src) != os.path.abspath(spec["path"]):
                                try:
                                    os.remove(src)
                                except OSError:
                                    pass
                            self.log(f"  ✅ 再生成: {spec['label']}", "success")
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
                with Image.open(spec["path"]) as img:
                    w, h = img.size
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
                img = Image.open(path)
                img.thumbnail((900, 900), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                lbl = tk.Label(win, image=photo)
                lbl.image = photo
                lbl.pack()
            except Exception as e:
                ttk.Label(win, text=f"読込失敗: {e}").pack(padx=20, pady=20)
            ttk.Button(win, text="閉じる", command=win.destroy).pack(pady=6)

        for idx, spec in enumerate(specs):
            cell = ttk.Frame(inner, relief=tk.RIDGE, borderwidth=1)
            cell.grid(row=0, column=idx, padx=5, pady=5, sticky="n")
            ttk.Label(cell, text=spec.get("label", f"画像 {idx + 1}"), font=("", 9, "bold")).pack()

            img_frame = ttk.Frame(cell, width=cell_w, height=cell_h)
            img_frame.pack_propagate(False)
            img_frame.pack()

            try:
                img = Image.open(spec["path"])
                img.thumbnail((cell_w, cell_h), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
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
            btn = ttk.Button(cell, text="✅ OK", style="OK.TButton", command=lambda i=idx: toggle(i))
            btn.pack(pady=4)
            btn_refs[idx] = btn

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
        self.history_batch_btn.config(state=state)
        self.cancel_btn.config(state=tk.DISABLED if enabled else tk.NORMAL)
        self.image_review_btn.config(state=state)
        self.ref_text.config(state=state)
        if enabled: self.progress.stop()
        else: self.progress.start(10)

    def open_output_dir(self):
        out_dir = os.path.abspath("output")
        os.makedirs(out_dir, exist_ok=True)
        os.startfile(out_dir)

if __name__ == "__main__":
    root = tk.Tk()
    app = YMM4AutoGui(root)
    root.mainloop()
