"""目的別作業の最終ローカル検証をまとめて実行する。

使い方: python tools/verify.py
各段を途中で失敗しても最後まで実行し、末尾に結果をまとめて表示する。
ルール違反の機械検査は tests/test_rule_guards.py にあり、pytest の段で実行される。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STEPS: list[tuple[str, list[str]]] = [
    ("テスト（ルール検査を含む）", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]),
    ("ジョブ監視のJS回帰テスト", ["node", "--test", *[str(p) for p in sorted((ROOT / "tests").glob("*.mjs"))]]),
    ("共通JSの構文（app.js）", ["node", "--check", "web_app/static/app.js"]),
    ("共通JSの構文（job_poll.js）", ["node", "--check", "web_app/static/job_poll.js"]),
    ("空白・改行の誤り（git diff --check）", ["git", "diff", "--check", "HEAD"]),
]


def main() -> int:
    results: list[tuple[str, int]] = []
    for name, cmd in STEPS:
        print(f"\n=== {name} ===", flush=True)
        code = subprocess.run(cmd, cwd=ROOT).returncode
        results.append((name, code))

    print("\n=== 結果 ===")
    for name, code in results:
        print(f"{'成功' if code == 0 else f'失敗（終了コード {code}）'}: {name}")
    return 0 if all(code == 0 for _, code in results) else 1


if __name__ == "__main__":
    sys.exit(main())
