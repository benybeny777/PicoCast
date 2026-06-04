"""起動中プロセス・既知ポートから外部依存サービスのパス/URLを自動検出する。

`/setup` の「プロセスを走査して自動設定」ボタンから利用する。検出結果は
EDITABLE_CONFIG のキー（VOICEVOX_PATH / VOICEVOX_URL / OLLAMA_BASE_URL /
SD_WEBUI_BASE_URL / FFMPEG_BIN）への適用候補として返す。秘密情報は扱わない。
"""
from __future__ import annotations

import shutil

import psutil

from config import config

# 外部依存ソフトの入手先・インストール手順カタログ。
# `/setup` のインストール案内と、未検出サービスのダウンロードリンク提示に使う。
# URL は config.py（環境で差し替え可能）から引く。手順テキストは表示用の固定文。
# install_hint=一行サマリ（検出表の列用）、steps=詳細手順（インストール案内カード用）。
_INSTALL_GUIDE: dict[str, dict] = {
    "voicevox": {
        "label": "VOICEVOX",
        "required": True,
        "purpose": "ずんだもん・四国めたんなどの音声合成（必須）",
        "download_url": config.VOICEVOX_DOWNLOAD_URL,
        "install_hint": "公式サイトからインストーラを入手して起動し、エンジンを立ち上げた状態で再診断してください（既定ポート 50021）。",
        "steps": [
            "公式サイトからインストーラー（GPU版 / CPU版）をダウンロードする。",
            "インストーラーを実行してインストールする。",
            "VOICEVOX を起動し、エンジンが立ち上がるまで待つ（既定ポート 50021）。",
            "起動した状態で下の「プロセスを走査して自動設定」を押すと自動検出されます。",
        ],
        "note": "起動していないと音声生成でエラー（E-VOICEVOX-DOWN）になります。動画生成中は起動したままにしてください。",
    },
    "ffmpeg": {
        "label": "ffmpeg",
        "required": True,
        "purpose": "音声・背景・字幕を合成して MP4 を書き出す（必須）",
        "download_url": config.FFMPEG_DOWNLOAD_URL,
        "install_hint": "ビルド版を解凍し、bin フォルダを PATH に通すか、解凍した ffmpeg.exe のパスを設定画面の FFMPEG_BIN に指定してください。",
        "steps": [
            "配布サイトから Windows 用ビルド（full 版）をダウンロードする。",
            "任意のフォルダに解凍する（例: C:\\ffmpeg）。",
            "解凍した bin フォルダを環境変数 PATH に追加する。または設定画面の FFMPEG_BIN に bin\\ffmpeg.exe のフルパスを指定する。",
            "下の「プロセスを走査して自動設定」または「再診断」で検出を確認する。",
        ],
        "note": "GPU（NVENC）が使えない環境でも自動で CPU エンコード（libx264）に切り替わります。",
    },
    "ollama": {
        "label": "Ollama",
        "required": False,
        "purpose": "台本の冒頭品質レビュー・リライト（任意・ローカルLLM）",
        "download_url": config.OLLAMA_DOWNLOAD_URL,
        "install_hint": "台本の品質レビューに使います（任意）。インストール後 `ollama pull qwen3:8b` でモデルを取得し、起動した状態で再診断してください。",
        "steps": [
            "公式サイトからインストーラーをダウンロードしてインストールする。",
            "コマンドプロンプトで `ollama pull qwen3:8b` を実行し、レビュー用モデルを取得する。",
            "Ollama を起動した状態にする（既定ポート 11434）。",
            "下の「再診断」で接続を確認する。",
        ],
        "note": "未導入でも動画生成は可能です。品質レビュー機能を使う場合のみ必要です。",
    },
    "sd_webui": {
        "label": "Stable Diffusion WebUI",
        "required": False,
        "purpose": "背景・サムネイル画像のローカル生成（任意・Gemini の代替）",
        "download_url": config.SD_WEBUI_DOWNLOAD_URL,
        "install_hint": "Gemini 画像生成の代替として使えます（任意）。`--api` 付きで起動した状態で再診断してください（既定ポート 7860）。",
        "steps": [
            "配布元から Stable Diffusion WebUI を入手してインストールする。",
            "API を有効にするため `--api` を付けて起動する（既定ポート 7860）。",
            "設定画面で画像生成バックエンドを Stable Diffusion WebUI に切り替える。",
            "下の「再診断」で接続を確認する。",
        ],
        "note": "未導入でも Gemini（Google API キー）で画像生成できます。ローカル生成したい場合のみ必要です。",
    },
}

# インストール案内の表示順（必須を先に）
_GUIDE_ORDER = ["voicevox", "ffmpeg", "ollama", "sd_webui"]


def get_installation_guides() -> list[dict]:
    """各外部依存ソフトのインストール案内（入手先・手順・必須/任意）を表示順で返す。

    `/setup` のインストール案内カードで使う。秘密情報は含まない。
    """
    guides: list[dict] = []
    for key in _GUIDE_ORDER:
        g = _INSTALL_GUIDE[key]
        guides.append({
            "key": key,
            "label": g["label"],
            "required": g["required"],
            "purpose": g["purpose"],
            "download_url": g["download_url"],
            "steps": list(g["steps"]),
            "note": g.get("note", ""),
        })
    return guides


def _listening_ports() -> dict[int, int]:
    """LISTEN中の TCP ポート -> pid のマップ。

    psutil の権限不足やプロセス消失は「検出できなかった」状態として扱い、
    例外ではなく空/欠落として返す（バグ握り潰しではなく走査の正常な結果）。
    """
    ports: dict[int, int] = {}
    try:
        conns = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, PermissionError):
        return ports
    for conn in conns:
        if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.pid:
            ports.setdefault(conn.laddr.port, conn.pid)
    return ports


def _proc_exe(pid: int | None) -> str:
    if not pid:
        return ""
    try:
        return psutil.Process(pid).exe() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return ""


def _find_process_exe_by_keyword(keywords: list[str]) -> str:
    kws = [k.lower() for k in keywords]
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            exe = proc.info.get("exe") or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        hay = f"{name} {exe.lower()}"
        if exe and any(k in hay for k in kws):
            return exe
    return ""


def _local_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def detect_services() -> dict:
    """外部依存サービスを走査し、検出状況と設定適用候補を返す。

    戻り値: {"services": [...], "proposed": {CONFIG_KEY: value, ...}}
    """
    ports = _listening_ports()
    services: list[dict] = []
    proposed: dict[str, str] = {}

    def _add(service: dict) -> None:
        # 未検出サービスにダウンロードリンク・インストール手順・必須/任意を付与する
        guide = _INSTALL_GUIDE.get(service.get("key", ""), {})
        service["required"] = guide.get("required", False)
        if not service.get("running"):
            service["download_url"] = guide.get("download_url", "")
            service["install_hint"] = guide.get("install_hint", "")
        services.append(service)
        proposed.update(service.get("config", {}))

    # ── VOICEVOX（既定ポート 50021 / 実行ファイル） ──
    vv: dict = {"key": "voicevox", "label": "VOICEVOX", "running": False, "config": {}, "detail": ""}
    if 50021 in ports:
        vv["running"] = True
        vv["config"]["VOICEVOX_URL"] = _local_url(50021)
        exe = _proc_exe(ports[50021])
        if exe:
            vv["process_exe"] = exe
    vv_exe = _find_process_exe_by_keyword(["voicevox"])
    if vv_exe:
        vv["running"] = True
        vv["config"]["VOICEVOX_PATH"] = vv_exe
        vv.setdefault("process_exe", vv_exe)
    vv["detail"] = "起動中を検出" if vv["running"] else "プロセス・ポート未検出"
    _add(vv)

    # ── Ollama（既定ポート 11434） ──
    ol: dict = {"key": "ollama", "label": "Ollama", "running": False, "config": {}, "detail": ""}
    if 11434 in ports:
        ol["running"] = True
        ol["config"]["OLLAMA_BASE_URL"] = _local_url(11434)
        exe = _proc_exe(ports[11434])
        if exe:
            ol["process_exe"] = exe
    ol["detail"] = "起動中を検出" if ol["running"] else "ポート 11434 未検出"
    _add(ol)

    # ── Stable Diffusion WebUI（既定ポート 7860） ──
    sd: dict = {"key": "sd_webui", "label": "Stable Diffusion WebUI", "running": False, "config": {}, "detail": ""}
    if 7860 in ports:
        sd["running"] = True
        sd["config"]["SD_WEBUI_BASE_URL"] = _local_url(7860)
        exe = _proc_exe(ports[7860])
        if exe:
            sd["process_exe"] = exe
    sd["detail"] = "起動中を検出" if sd["running"] else "ポート 7860 未検出"
    _add(sd)

    # ── ffmpeg（PATH 上のバイナリ） ──
    ff: dict = {"key": "ffmpeg", "label": "ffmpeg", "running": False, "config": {}, "detail": ""}
    ff_path = shutil.which("ffmpeg")
    if ff_path:
        ff["running"] = True
        ff["config"]["FFMPEG_BIN"] = ff_path
        ff["process_exe"] = ff_path
        ff["detail"] = "PATH 上に検出"
    else:
        ff["detail"] = "PATH 上に未検出"
    _add(ff)

    return {"services": services, "proposed": proposed}


def apply_detected(updates: dict) -> list[str]:
    """検出した設定値を EDITABLE_CONFIG 経由で保存・即時反映する。

    戻り値: バリデーションエラーのリスト（空なら成功）。
    """
    from web_app.services.config_service import save_config
    clean = {str(k): str(v) for k, v in (updates or {}).items() if str(v).strip()}
    if not clean:
        return ["適用できる検出値がありません"]
    return save_config(clean)
