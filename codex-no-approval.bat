@echo off
cd /d "%~dp0"
codex --ask-for-approval never --sandbox danger-full-access -C "%~dp0"
