"""Codex CLI の画像生成（image_generation 機能・gpt-image）で1枚作る。

ChatGPT のサブスクリプションでログイン済みの `codex exec` に、内蔵の画像生成で画像を作り
作業フォルダへ保存するよう頼む。API キーは使わない。生成は OpenAI のサーバーで行われる
（ローカル生成ではない）。画像1枚でサブスクリプションの使用枠を文章の数倍使うため、
枚数の多い背景より、1本に数枚のサムネイル向け。

安全のための約束（core/text_llm.py の文章生成と同じ方針）:
- 作業フォルダは専用の一時フォルダだけ。保存させるため `--sandbox workspace-write` にするが、
  書き込める場所はその一時フォルダ（と Codex 既定の /tmp）に限られる。
- `--ignore-user-config` で利用者の MCP やツール設定を読ませない。
- 環境変数 `OPENAI_API_KEY` を外して起動する。残っていると API の従量課金に切り替わるため。
- プロンプトは標準入力で渡す。参照画像（立ち絵）は `--image=` で添付する。
- 決めたファイル名（output.png）が無ければ失敗にする。別の場所を探して代わりに使わない。
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile

from config import config as cfg
from core import text_llm
from core.error_codes import AppError

_logger = logging.getLogger(__name__)

OUTPUT_NAME = "output.png"
_LABEL = "Codex CLI（画像生成）"


def build_instruction(prompt: str, *, width: int, height: int, reference_names: list[str]) -> str:
    orientation = "縦長（9:16）" if height > width else "横長（16:9）"
    refs = ""
    if reference_names:
        refs = (
            f"添付した画像（{', '.join(reference_names)}）はキャラクターの参照です。"
            "指示に従って参照してください。\n"
        )
    return (
        "画像生成ツールで次の画像を1枚だけ生成し、現在の作業フォルダ直下に "
        f"`{OUTPUT_NAME}` という名前の PNG で保存してください。"
        "ほかのファイルは作らず、保存できたら「保存しました」とだけ答えてください。\n"
        f"向き: {orientation}\n"
        f"{refs}"
        "--- 画像の指示 ---\n"
        f"{prompt}"
    )


def command(program: str, workdir: str, reference_paths: list[str]) -> list[str]:
    args = [
        program,
        "exec",
        "--ignore-user-config",
        "--sandbox", "workspace-write",
        "--ephemeral",
        "--skip-git-repo-check",
        "--cd", workdir,
    ]
    model = text_llm.cli_model("codex_cli")
    if model:
        args.extend(["--model", model])
    # `--image a b` の形だと後ろの `-` まで画像として読まれうるため、1枚ずつ = で渡す
    args.extend(f"--image={path}" for path in reference_paths)
    args.append("-")  # 標準入力からプロンプトを読む
    return args


def subscription_env() -> dict[str, str]:
    """OPENAI_API_KEY を外した環境変数（ChatGPT のサブスクリプションで動かすため）。"""
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    return env


def generate_png(prompt: str, *, width: int, height: int, reference_paths: list[str] | None = None) -> bytes:
    """画像を1枚生成して PNG のバイト列を返す。"""
    program = text_llm.resolve_cli("codex_cli")
    if program is None:
        _logger.error("画像生成に使う Codex CLI が見つかりません: path=%s", cfg.CODEX_CLI_PATH)
        raise AppError("E-LLM-CLI-MISSING", f"Codex CLI（{cfg.CODEX_CLI_PATH}）")
    workdir = tempfile.mkdtemp(prefix="yukkurijidou_codex_image_")
    try:
        names = []
        for index, path in enumerate(reference_paths or []):
            name = f"reference_{index + 1}{os.path.splitext(path)[1] or '.png'}"
            shutil.copyfile(path, os.path.join(workdir, name))
            names.append(name)
        stdout, stderr, returncode = text_llm.run_cli(
            command(program, workdir, [os.path.join(workdir, n) for n in names]),
            build_instruction(prompt, width=width, height=height, reference_names=names),
            cfg.CODEX_IMAGE_TIMEOUT_SEC,
            _LABEL,
            cwd=workdir,
            env=subscription_env(),
        )
        if returncode != 0:
            _logger.error("%s が失敗しました: exit=%s stderr=%s", _LABEL, returncode, stderr.strip()[-2000:])
            raise AppError("E-LLM-FAILED", f"{_LABEL} が終了コード {returncode} で失敗しました")
        output = os.path.join(workdir, OUTPUT_NAME)
        if not os.path.isfile(output):
            _logger.error("%s が %s を保存しませんでした: stdout=%s", _LABEL, OUTPUT_NAME, stdout.strip()[-2000:])
            raise AppError("E-CODEX-IMAGE-MISSING", "Codex の応答に画像ファイルがありません")
        with open(output, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
