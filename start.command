#!/bin/sh
set -eu

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "エラー: .venv/bin/python が見つかりません。先に python3 -m venv .venv と .venv/bin/python -m pip install --upgrade -r requirements.txt を実行してください。"
  exit 1
fi

exec ".venv/bin/python" -m web_app.app --open-browser
