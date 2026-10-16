#!/bin/sh
set -eu

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "エラー: uv がありません。セットアップ手順で導入してください。"
  exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
  echo "エラー: Python環境がありません。uv sync --locked --group build --group dev を実行してください。"
  exit 1
fi
if [ "$(.venv/bin/python -I -S -c 'import sys; print(*sys.version_info[:2],sep=chr(46))')" != "3.12" ]; then
  echo "エラー: Python 3.12環境が必要です。既存環境とDBを退避してから移行してください。"
  exit 1
fi

exec uv run --locked --no-sync python -m web_app.app --open-browser
