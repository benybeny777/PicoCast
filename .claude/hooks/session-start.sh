#!/bin/bash
# Claude Code on the web などリモート環境で、テストに必要な依存パッケージを用意する。
# 利用者のPCでは何もしない（.venv を勝手に書き換えない）。
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
cd "$CLAUDE_PROJECT_DIR"
python3 -m pip install --quiet --disable-pip-version-check -r config/requirements-dev.txt
