import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import re
import os
import sys
import subprocess
import traceback
import time
import shutil
from main import run_pipeline, regenerate_thumbnail_only
from core.ai_generator import AIGenerator
from core.ng_words import NG_WORD_PROMPT
from core.script_prompts import build_vidiq_prompt
from config import VOICEVOX_URL, VOICEVOX_PATH
import requests

VIDIQ_PROMPT = build_vidiq_prompt()


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

        ttk.Label(opt_frame, text="履歴:").pack(side=tk.LEFT, padx=(10, 2))
        self.history_combo = ttk.Combobox(opt_frame, state="readonly", width=22, font=("Meiryo", 9))
        self.history_combo.set("履歴から選択")
        self.history_combo.pack(side=tk.LEFT, padx=2)
        self.history_combo.bind("<<ComboboxSelected>>", self.on_history_selected)

        # Sub buttons row
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 4))
        self.upload_btn = ttk.Button(btn_frame, text="📤 YouTubeアップ", command=self.start_youtube_upload)
        self.upload_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.open_folder_btn = ttk.Button(btn_frame, text="📁 出力フォルダを開く", command=self.open_output_dir)
        self.open_folder_btn.pack(side=tk.LEFT)
        self.regen_thumb_btn = ttk.Button(btn_frame, text="🖼 サムネ再生成", command=self.start_regen_thumbnail)
        self.regen_thumb_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._studio_url = None
        self.studio_btn = ttk.Button(btn_frame, text="🌐 YouTube Studio", command=self._open_studio)
        self.studio_btn.pack(side=tk.LEFT, padx=(8, 0))


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
        self.history_combo['values'] = history

    def on_history_selected(self, event):
        selected = self.history_combo.get()
        if not selected:
            return
        output_dir = os.path.join("output", selected)
        script_path = os.path.join(output_dir, "script.txt")
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                self.ref_text.delete("1.0", tk.END)
                self.ref_text.insert("1.0", f.read())
            self.log(f"履歴 '{selected}' から台本を読み込みました")
        if os.path.exists(os.path.join(output_dir, "metadata.txt")):
            self.last_output_dir = output_dir
            self._update_meta_preview()

    def start_generation(self):
        raw_scripts = self.ref_text.get("1.0", tk.END).strip()
        scripts = [s.strip() for s in re.split(r'\n-{3,}\n', raw_scripts) if s.strip()]

        if not scripts:
            messagebox.showwarning("Error", "台本を入力してください")
            return

        self._toggle_ui(False)
        self.log(f"一括処理開始: 合計 {len(scripts)} 件")
        threading.Thread(target=self._run_batch, args=(scripts,), daemon=True).start()

    def _run_batch(self, scripts):
        count = len(scripts)
        is_batch = count > 1

        for idx, script in enumerate(scripts):
            try:
                # Derive topic from 動画タイトル: line, fallback to first line
                topic = None
                for line in script.split("\n"):
                    line = line.strip().replace("**", "")
                    m = re.match(r'^(?:動画タイトル|Title)[:：]\s*(.+)$', line, re.IGNORECASE)
                    if m:
                        topic = m.group(1).strip()[:50]
                        break
                if not topic:
                    first_line = script.split("\n")[0].strip()
                    topic = re.sub(r'^[#*【]|\s*[:：].*$', '', first_line).strip()[:30]
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
                )

                self.log(f"成功: {topic}", "success")
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

        if is_batch:
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
        from tkinter import filedialog
        mp4_path = filedialog.askopenfilename(
            title="アップロードする動画ファイルを選択",
            initialdir="output",
            filetypes=[("MP4 動画", "*.mp4"), ("すべてのファイル", "*.*")]
        )
        if not mp4_path:
            return

        output_dir = os.path.dirname(mp4_path)
        meta = self._read_meta_from_dir(output_dir)
        title = meta.get("title", os.path.basename(output_dir))
        description = meta.get("description", "")
        tags = meta.get("tags", "")
        is_shorts = os.path.basename(output_dir).startswith("[Shorts]")
        thumb = None if is_shorts else os.path.join(output_dir, "thumbnail.png")

        privacy = "private"
        self.upload_btn.config(state=tk.DISABLED)
        threading.Thread(
            target=self._run_upload,
            args=(mp4_path, title, description, tags, thumb, privacy, output_dir),
            daemon=True
        ).start()

    def _open_studio(self):
        import webbrowser
        webbrowser.open(self._studio_url or "https://studio.youtube.com/")

    def _run_upload(self, mp4_path, title, description, tags, thumb, privacy, output_dir):
        try:
            from core.youtube_uploader import upload_video
            from core.ai_generator import AIGenerator
            self.log("✍️  説明文をGeminiで整形中...")
            description = AIGenerator().format_description(description)
            video_id = upload_video(mp4_path, title, description, tags,
                                    thumbnail_path=thumb, privacy=privacy,
                                    progress_callback=self.log)

            if video_id:
                self._studio_url = f"https://studio.youtube.com/video/{video_id}/edit"

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

    def _toggle_ui(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.generate_btn.config(state=state)
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
