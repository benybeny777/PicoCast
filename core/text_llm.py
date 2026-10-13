"""文章生成AIの窓口。設定 TEXT_LLM_BACKEND に従って1回の文章生成を行う。

- gemini: Google Gemini API（API キーが必要・従量課金）
- claude_cli: 手元の Claude Code CLI（`claude -p`）。ログイン済みのサブスクリプションで動く
- codex_cli: 手元の Codex CLI（`codex exec`）。ログイン済みのサブスクリプションで動く
- ollama: ローカルの Ollama

CLI の起動方法は PicoAgent（providers/agent_cli.rs）で検証済みの安全指定に揃える。
CLI 自身のファイル編集・コマンド実行ツールは封じ、台本作成の事実確認に使う Web 検索だけを
必要なときに許可する。プロンプトはコマンドライン引数ではなく標準入力で渡す。Windows の
`claude.cmd` / `codex.cmd` は cmd.exe 経由で起動されるため、引数に台本の記号や改行を入れると
誤って解釈されるうえ、コマンドライン長の上限にも当たるため。

失敗時に別の AI へ切り替えない（フォールバック禁止）。理由付きの AppError で止める。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config import config as cfg
from core.error_codes import AppError

_logger = logging.getLogger(__name__)

BACKENDS = ("gemini", "claude_cli", "codex_cli", "ollama")
BACKEND_LABELS = {
    "gemini": "Gemini API",
    "claude_cli": "Claude Code CLI",
    "codex_cli": "Codex CLI",
    "ollama": "Ollama（ローカル）",
}

# モデル名として受け付ける文字。設定値をそのまま CLI 引数へ渡すため記号を制限する。
_MODEL_NAME = re.compile(r"^[A-Za-z0-9._:/\-\[\]]+$")


def current_backend() -> str:
    backend = str(getattr(cfg, "TEXT_LLM_BACKEND", "gemini") or "gemini").strip().lower()
    if backend not in BACKENDS:
        raise AppError("E-LLM-BACKEND", f"TEXT_LLM_BACKEND={backend}")
    return backend


def generate(prompt: str, *, system: str = "", web_search: bool = False, backend: str | None = None) -> str:
    """文章を1回生成して本文を返す。空の応答も失敗として扱う。"""
    selected = backend or current_backend()
    if selected not in BACKENDS:
        raise AppError("E-LLM-BACKEND", f"TEXT_LLM_BACKEND={selected}")
    if not prompt.strip():
        raise ValueError("文章生成AIへ渡す内容が空です")
    if selected == "gemini":
        text = _generate_gemini(prompt, system=system, web_search=web_search)
    elif selected == "ollama":
        text = _generate_ollama(_join(system, prompt))
    else:
        text = _generate_cli(selected, _join(system, prompt), web_search=web_search)
    text = (text or "").strip()
    if not text:
        _logger.error("文章生成AIが空の応答を返しました: backend=%s", selected)
        raise AppError("E-LLM-FAILED", f"{BACKEND_LABELS[selected]} が空の応答を返しました")
    return text


def _join(system: str, prompt: str) -> str:
    """CLI と Ollama は system 指示を持たないため、本文の前に置く。"""
    if not system.strip():
        return prompt
    return f"{system.strip()}\n\n---\n\n{prompt}"


# ── Gemini ────────────────────────────────────────────────────────────────

def _generate_gemini(prompt: str, *, system: str, web_search: bool) -> str:
    from google import genai
    from core.secret_store import has_secret, load_secret, require_current_profile_id

    profile_id = require_current_profile_id()
    if not has_secret("google_api_key", profile_id=profile_id):
        raise AppError("E-SECRET-MISSING", "Google API キー（設定画面の「認証情報」から登録）")
    config: dict = {}
    if system.strip():
        config["system_instruction"] = system
    if web_search:
        config["tools"] = [{"google_search": {}}]
    client = genai.Client(api_key=load_secret("google_api_key", profile_id=profile_id))
    try:
        response = client.models.generate_content(model=cfg.GEMINI_MODEL, contents=prompt, config=config or None)
    except Exception as exc:
        _logger.error("Gemini の文章生成に失敗しました: model=%s", cfg.GEMINI_MODEL, exc_info=True)
        raise AppError("E-LLM-FAILED", f"Gemini（{type(exc).__name__}）", cause=exc) from exc
    finally:
        if hasattr(client, "close"):
            client.close()
    return (response.text or "") if response else ""


# ── Ollama ────────────────────────────────────────────────────────────────

def _generate_ollama(prompt: str) -> str:
    import requests
    from core.opening_quality import ensure_ollama_server

    try:
        ensure_ollama_server()
        body = {"model": cfg.OLLAMA_TEXT_MODEL, "prompt": prompt, "stream": False, "think": False}
        with requests.post(
            f"{cfg.OLLAMA_BASE_URL.rstrip('/')}/api/generate", json=body, timeout=cfg.TEXT_LLM_TIMEOUT_SEC,
        ) as response:
            response.raise_for_status()
            return str(response.json().get("response", ""))
    except requests.exceptions.ConnectionError as exc:
        _logger.error("文章生成用 Ollama に接続できません: url=%s", cfg.OLLAMA_BASE_URL, exc_info=True)
        raise AppError("E-OLLAMA-DOWN", "文章生成AIに Ollama を選んでいます。", cause=exc) from exc
    except Exception as exc:
        _logger.error("Ollama の文章生成に失敗しました: model=%s", cfg.OLLAMA_TEXT_MODEL, exc_info=True)
        raise AppError("E-LLM-FAILED", f"Ollama {cfg.OLLAMA_TEXT_MODEL}（{type(exc).__name__}）", cause=exc) from exc


# ── Claude Code / Codex CLI ───────────────────────────────────────────────

def _program(backend: str) -> str:
    return cfg.CLAUDE_CLI_PATH if backend == "claude_cli" else cfg.CODEX_CLI_PATH


def resolve_cli(backend: str) -> str | None:
    """CLI の実行ファイルを絶対パスで返す。見つからなければ None。"""
    program = (_program(backend) or "").strip()
    if not program:
        return None
    if os.path.isabs(program):
        return program if os.path.isfile(program) else None
    return shutil.which(program)


def cli_model(backend: str) -> str:
    model = cfg.CLAUDE_CLI_MODEL if backend == "claude_cli" else cfg.CODEX_CLI_MODEL
    if not model and backend == "codex_cli":
        model = codex_default_model() or ""
    if model and not _MODEL_NAME.match(model):
        raise AppError("E-LLM-BACKEND", f"CLI のモデル名に使えない文字があります: {model}")
    return model


def codex_default_model() -> str | None:
    """Codex の既定モデルを ~/.codex/config.toml（profile 指定を含む）から読む。

    CLI には利用者の設定ファイル全体を読ませない（--ignore-user-config）ため、モデル選択だけ引き継ぐ。
    """
    import tomllib

    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    path = home / "config.toml"
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _logger.error("Codex の config.toml を読めません: path=%s", path, exc_info=True)
        raise AppError("E-LLM-BACKEND", "Codex の config.toml を読めません", cause=exc) from exc
    profile = data.get("profile")
    if isinstance(profile, str):
        model = data.get("profiles", {}).get(profile, {}).get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
    model = data.get("model")
    return model.strip() if isinstance(model, str) and model.strip() else None


def cli_args(backend: str, *, web_search: bool) -> list[str]:
    """プロンプト以外の引数。プロンプトは標準入力で渡す。"""
    model = cli_model(backend)
    if backend == "claude_cli":
        args = [
            "-p",
            "--safe-mode",
            # 台本の事実確認に使う読み取り専用の Web 検索だけを許可する。ファイル編集・コマンド実行は封じる。
            "--tools", "WebSearch" if web_search else "",
            "--permission-mode", "plan",
            "--no-session-persistence",
        ]
    elif backend == "codex_cli":
        args = [
            "exec",
            "--ignore-user-config",
            "--sandbox", "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
        ]
    else:
        raise AppError("E-LLM-BACKEND", f"CLI ではない文章生成AIです: {backend}")
    if model:
        args.extend(["--model", model])
    if backend == "codex_cli":
        args.append("-")  # 標準入力からプロンプトを読む
    return args


def _generate_cli(backend: str, prompt: str, *, web_search: bool) -> str:
    label = BACKEND_LABELS[backend]
    program = resolve_cli(backend)
    if program is None:
        _logger.error("%s が見つかりません: path=%s", label, _program(backend))
        raise AppError("E-LLM-CLI-MISSING", f"{label}（{_program(backend)}）")
    command = [program, *cli_args(backend, web_search=web_search)]
    stdout, stderr, returncode = run_cli(command, prompt, cfg.TEXT_LLM_TIMEOUT_SEC, label)
    if returncode != 0:
        _logger.error(
            "%s が失敗しました: exit=%s stderr=%s", label, returncode, stderr.strip()[-2000:],
        )
        raise AppError("E-LLM-FAILED", f"{label} が終了コード {returncode} で失敗しました")
    return stdout


def run_cli(
    command: list[str], stdin_text: str, timeout: int, label: str, *,
    cwd: str | None = None, env: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """CLI を起動して標準入力を渡し、(stdout, stderr, 終了コード) を返す。時間切れなら子孫プロセスごと止める。"""
    import psutil

    popen_extra: dict = {}
    if sys.platform == "win32":
        popen_extra["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        popen_extra["start_new_session"] = True
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **popen_extra,
    )
    try:
        stdout, stderr = proc.communicate(stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _logger.error("%s が %s 秒以内に終わらなかったため停止します", label, timeout, exc_info=True)
        _kill_tree(proc, psutil)
        raise AppError("E-LLM-TIMEOUT", f"{label}（{timeout} 秒）", cause=exc) from exc
    except BaseException:
        _logger.error("%s の実行が中断されたため停止します", label, exc_info=True)
        _kill_tree(proc, psutil)
        raise
    return stdout, stderr, proc.returncode


def _kill_tree(proc: subprocess.Popen, psutil) -> None:
    try:
        parent = psutil.Process(proc.pid)
        members = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        _logger.info("停止対象の CLI は既に終了しています: pid=%s", proc.pid, exc_info=True)
        members = []
    for member in members:
        try:
            member.kill()
        except psutil.NoSuchProcess:
            _logger.info("CLI の子プロセスは既に終了しています: pid=%s", member.pid, exc_info=True)
    psutil.wait_procs(members, timeout=10)
    proc.communicate()


def available_backends() -> list[dict]:
    """設定画面・生成画面に出す、各文章生成AIの利用可否。"""
    result = []
    for backend in BACKENDS:
        if backend in ("claude_cli", "codex_cli"):
            ready = resolve_cli(backend) is not None
            note = "" if ready else f"{_program(backend)} が見つかりません"
        else:
            ready = True
            note = ""
        result.append({"backend": backend, "label": BACKEND_LABELS[backend], "ready": ready, "note": note})
    return result
