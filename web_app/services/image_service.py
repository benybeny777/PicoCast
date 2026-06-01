"""
画像確認・再生成サービス。
output/{history_name}/backgrounds/ および thumbnails/ を走査する。
再生成はジョブ化して実行。パストラバーサル対策は security.py 経由で行う。
"""
import os
from typing import Any

from core.output_paths import get_output_videos_dir
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import find_history_dir


def _detect_is_shorts_from_dir(theme_dir: str) -> bool:
    """script.txt の動画形式行から Shorts か判定する。読めなければ Shorts として扱う。"""
    import logging
    script_path = os.path.join(theme_dir, "script.txt")
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        from workers.main import _detect_is_shorts
        return _detect_is_shorts(content)
    except Exception as e:
        # フォールバック許可: script.txt が読めない場合は画像再生成を止めず Shorts として扱う
        logging.warning("_detect_is_shorts_from_dir: script.txt 読み取り失敗 (%s) - Shorts として処理します: %s", theme_dir, e)
        return True


def list_images(history_name: str) -> dict[str, Any]:
    """指定履歴の画像一覧を返す。"""
    theme_dir = _resolve_dir(history_name)

    replacements = _replacement_map(history_name)
    thumbnails = []
    thumbs_dir = os.path.join(theme_dir, "thumbnails")
    if os.path.isdir(thumbs_dir):
        for fname in sorted(os.listdir(thumbs_dir)):
            if fname.endswith(".png"):
                key = f"thumbnails/{fname}"
                thumbnails.append({
                    "key": key,
                    "filename": fname,
                    "is_main": fname == "thumbnail.png",
                    **_image_meta(os.path.join(thumbs_dir, fname), replacements.get(key)),
                })

    backgrounds = []
    bg_dir = os.path.join(theme_dir, "backgrounds")
    if os.path.isdir(bg_dir):
        for fname in sorted(os.listdir(bg_dir)):
            if fname.endswith(".png"):
                prompt = _read_bg_prompt(bg_dir, fname)
                key = f"backgrounds/{fname}"
                backgrounds.append({
                    "key": key,
                    "filename": fname,
                    "prompt": prompt,
                    **_image_meta(os.path.join(bg_dir, fname), replacements.get(key)),
                })

    return {
        "history_name": history_name,
        "thumbnails": thumbnails,
        "backgrounds": backgrounds,
    }


def _read_bg_prompt(bg_dir: str, fname: str) -> str:
    """prompt_bg_XXXX.txt を読む。【台本】以降の台本全文は除去してシーン説明のみ返す。"""
    try:
        bg_num = int(fname.split("_")[1])
        path = os.path.join(bg_dir, f"prompt_bg_{bg_num:04d}.txt")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        # 「以下の台本を参考に、「○○」のシーンの背景画像を生成してください。\n\n【台本】\n<script>」
        # → シーン説明部分のみ表示する
        if "【台本】" in content:
            content = content.split("【台本】")[0].strip()
        return content
    except Exception:
        return ""


def _image_meta(path: str, replacement: dict[str, Any] | None = None) -> dict[str, Any]:
    from PIL import Image
    width = height = None
    try:
        with Image.open(path) as img:
            width, height = img.size
    except Exception:
        pass
    return {
        "width": width,
        "height": height,
        "last_replacement_at": replacement.get("created_at") if replacement else "",
        "last_replacement_source": replacement.get("source_type") if replacement else "",
        "last_replacement_id": replacement.get("id") if replacement else None,
    }


def _replacement_map(history_name: str) -> dict[str, dict[str, Any]]:
    try:
        from core.metadata_db import list_image_replacements
        local_id = os.path.basename(history_name.replace("\\", "/"))
        rows = list_image_replacements(local_id)
        result = {}
        for row in rows:
            key = row.get("target_rel_path")
            if key and key not in result:
                result[key] = row
        return result
    except Exception:
        return {}


def save_bg_prompts(history_name: str, prompts: dict[str, str]) -> list[str]:
    """
    {key: prompt_text} を受け取り backgrounds/prompt_bg_XXXX.txt に書き込む。
    保存済みキーの一覧を返す。
    """
    theme_dir = _resolve_dir(history_name)
    bg_dir = os.path.join(theme_dir, "backgrounds")
    saved = []
    for key, text in prompts.items():
        if not key.startswith("backgrounds/"):
            continue
        fname = os.path.basename(key)
        try:
            bg_num = int(fname.split("_")[1])
        except (ValueError, IndexError):
            continue
        prompt_path = os.path.join(bg_dir, f"prompt_bg_{bg_num:04d}.txt")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(text)
        saved.append(key)
    return saved


def submit_regenerate_job(
    history_name: str,
    image_keys: list[str],
    prompts: dict[str, str] | None = None,
    background_engine: str = "",
    sd_size_mode: bool = False,
) -> str:
    _validate_name(history_name)
    mgr = get_job_manager()
    job = mgr.create_job("image_regenerate")
    _log(job, f"画像再生成ジョブを登録: {len(image_keys)}枚", "info")
    mgr.submit(job, _run_regenerate, history_name, image_keys, prompts or {}, background_engine, sd_size_mode)
    return job.job_id


def _run_regenerate(
    job: Job,
    history_name: str,
    image_keys: list[str],
    prompts: dict[str, str],
    background_engine: str = "",
    sd_size_mode: bool = False,
) -> dict[str, Any]:
    """
    背景画像: prompts に上書きがあればそれを使用、なければ prompt_bg_XXXX.txt を読む。
    サムネイル: main.regenerate_thumbnail_only() を使用。
    """
    from core.image_generator import ImageGenerator
    from workers.main import regenerate_thumbnail_only

    theme_dir = _resolve_dir(history_name)
    bg_dir = os.path.join(theme_dir, "backgrounds")

    is_shorts = _detect_is_shorts_from_dir(theme_dir)
    width = 1080 if is_shorts else 1920
    height = 1920 if is_shorts else 1080

    engine = background_engine.strip() or None

    _log(job, f"画像再生成開始: {len(image_keys)}枚 ({'Shorts' if is_shorts else 'Long'})", "info")

    regenerated: list[str] = []
    failed: list[str] = []

    for key in image_keys:
        if job.cancel_event.is_set():
            _log(job, "キャンセルされました", "warning")
            break

        try:
            if key.startswith("backgrounds/"):
                fname = os.path.basename(key)
                try:
                    bg_num = int(fname.split("_")[1])
                except (ValueError, IndexError):
                    raise ValueError(f"ファイル名からbg番号を解析できません: {fname}")

                # フォームで編集済みのプロンプトがあればそれを優先、なければファイルから読む
                if key in prompts and prompts[key].strip():
                    prompt = prompts[key].strip()
                    _log(job, f"編集済みプロンプトを使用: {fname}", "info")
                else:
                    prompt_file = os.path.join(bg_dir, f"prompt_bg_{bg_num:04d}.txt")
                    if not os.path.isfile(prompt_file):
                        raise FileNotFoundError(f"プロンプトファイルが見つかりません: prompt_bg_{bg_num:04d}.txt")
                    with open(prompt_file, "r", encoding="utf-8") as pf:
                        prompt = pf.read()

                _log(job, f"背景再生成中: {fname}", "info")
                with ImageGenerator(width=width, height=height, background_engine=engine, sd_size_mode=sd_size_mode) as img_gen:
                    if img_gen.background_engine == "nanobanana":
                        _log(job, img_gen.nanobanana_request_summary(), "info")
                    img_gen.generate_background(prompt, target_dir=bg_dir, fname=fname)
                _log(job, f"背景再生成完了: {fname}", "success")
                regenerated.append(key)

            elif key.startswith("thumbnails/"):
                _log(job, "サムネイル再生成中...", "info")
                thumb_path = regenerate_thumbnail_only(
                    theme_dir,
                    progress_callback=lambda msg, tag="info": _log(job, msg, tag),
                    background_engine=engine,
                    sd_size_mode=sd_size_mode,
                )
                _log(job, f"サムネイル再生成完了: {os.path.basename(thumb_path)}", "success")
                regenerated.append(key)

            else:
                raise ValueError(f"未対応のキー: {key}")

        except Exception as e:
            _log(job, f"再生成エラー ({key}): {e}", "error")
            failed.append(key)

    if failed:
        _log(job, f"完了: 成功{len(regenerated)}枚 / 失敗{len(failed)}枚", "warning")
    else:
        _log(job, f"完了: {len(regenerated)}枚すべて成功", "success")

    return {"regenerated": regenerated, "failed": failed}


def _validate_name(name: str) -> None:
    if ".." in name or "/" in name or "\\" in name:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")


def _resolve_dir(history_name: str) -> str:
    """履歴名を検証し、実体のテーマフォルダ（videos/・000_uploaded/）を解決する。"""
    _validate_name(history_name)
    theme_dir = find_history_dir(history_name)
    if theme_dir is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")
    return theme_dir
