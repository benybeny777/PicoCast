import logging
import os
import re
import subprocess

from config import config as cfg

_logger = logging.getLogger(__name__)


SHORTS_DIRECT_NAVIGATION_NG = [
    "次回は",
    "次は",
    "次の動画",
    "他の動画も見て",
    "チャンネル登録して待って",
    "登録して待って",
    "高評価お願いします",
    "チャンネル登録お願いします",
]


def normalize_video_type(video_type: str | None) -> str:
    text = str(video_type or "").strip().lower()
    if text in {"shorts", "short"}:
        return "Shorts"
    if text in {"long", "ロング"}:
        return "Long"
    return str(video_type or "").strip()


def is_shorts_video_type(video_type: str | None) -> bool:
    return normalize_video_type(video_type) == "Shorts"


def normalize_generation_kind(generation_kind: str | None) -> str:
    text = str(generation_kind or "").strip()
    aliases = {
        "新規": "新規",
        "横展開": "横展開",
        "品質改善": "品質改善版",
        "品質改善版": "品質改善版",
        "改善再挑戦": "再挑戦",
        "再挑戦": "再挑戦",
    }
    return aliases.get(text, text)


def is_topic_request_cta_candidate(video_type: str | None, generation_kind: str | None) -> bool:
    return is_shorts_video_type(video_type) and normalize_generation_kind(generation_kind) in {"新規", "横展開"}


def topic_request_cta_interval() -> int:
    return int(getattr(cfg, "TOPIC_REQUEST_CTA_EVERY_N", 0) or 0)


def should_allow_topic_request_cta(
    video_type: str,
    generation_kind: str,
    batch_index: int,
    batch_size: int,
    already_allowed_in_batch: bool,
) -> bool:
    # batch_index は対象Shortsの通算0始まり位置として扱う。
    # batch_size / already_allowed_in_batch は旧呼び出し互換のため受ける。
    del batch_size, already_allowed_in_batch
    if not is_topic_request_cta_candidate(video_type, generation_kind):
        return False
    interval = topic_request_cta_interval()
    if interval <= 0:
        return False
    if batch_index < 0:
        return False
    return (batch_index + 1) % interval == 0


def topic_request_cta_reason(
    video_type: str,
    generation_kind: str,
    batch_index: int,
    batch_size: int,
    already_allowed_in_batch: bool,
) -> str:
    if not is_shorts_video_type(video_type):
        return "LongまたはShorts以外のため禁止"
    kind = normalize_generation_kind(generation_kind)
    if kind not in {"新規", "横展開"}:
        return f"生成区分={kind or '未設定'} のため禁止"
    interval = topic_request_cta_interval()
    if interval <= 0:
        return "TOPIC_REQUEST_CTA_EVERY_N=0 のためネタ募集CTA自動付与なし"
    if should_allow_topic_request_cta(video_type, generation_kind, batch_index, batch_size, already_allowed_in_batch):
        return f"通算{batch_index + 1}本目の対象Shorts（{interval}本に1本）"
    return f"通算{batch_index + 1}本目の対象Shortsのため禁止（{interval}本に1本のみ許可）"


def _script_meta_from_text(script_text: str) -> dict[str, str]:
    try:
        from core.parser import ScriptParser

        return {
            item["type"]: item["text"]
            for item in ScriptParser.parse_string(script_text)
            if item["type"] in ScriptParser.META_TYPES
        }
    except Exception:
        # フォールバック許可: CTA方針用のメタ抽出は補助機能。パース失敗で生成全体を止めない。
        _logger.warning("CTA方針用の台本メタ抽出に失敗。空メタで続行します", exc_info=True)
        return {}


def count_existing_topic_request_candidates(output_dir: str | None = None) -> int:
    """既存のネタ募集CTA候補（新規/横展開 の Shorts）の本数を metadata.db から数える。

    台本本文・メタは DB（`video_metadata`）を正本とし、ディスクの script.txt は走査しない。
    `output_dir` 引数は後方互換のため受けるが未使用（DB は active profile 単位）。
    """
    del output_dir
    from core.metadata_db import ManagedConnection, initialize_db, is_initialized
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        rows = conn.execute(
            "SELECT video_format, generation_type FROM video_metadata"
        ).fetchall()
    return sum(
        1 for r in rows
        if is_topic_request_cta_candidate(r["video_format"], r["generation_type"])
    )


def apply_topic_request_cta_policy_to_scripts(
    scripts: list[str],
    existing_candidate_count: int | None = None,
    output_dir: str | None = None,
) -> list[str]:
    base_count = (
        count_existing_topic_request_candidates(output_dir)
        if existing_candidate_count is None
        else int(existing_candidate_count)
    )
    eligible_seen = 0
    updated_scripts: list[str] = []
    for script in scripts:
        meta = _script_meta_from_text(script)
        video_type = meta.get("video_format", "")
        generation_kind = meta.get("generation_kind", "")
        if is_topic_request_cta_candidate(video_type, generation_kind):
            sequence_index = base_count + eligible_seen
            allowed = should_allow_topic_request_cta(
                video_type=video_type,
                generation_kind=generation_kind,
                batch_index=sequence_index,
                batch_size=len(scripts),
                already_allowed_in_batch=False,
            )
            reason = topic_request_cta_reason(
                video_type=video_type,
                generation_kind=generation_kind,
                batch_index=sequence_index,
                batch_size=len(scripts),
                already_allowed_in_batch=False,
            )
            eligible_seen += 1
        else:
            allowed = False
            reason = topic_request_cta_reason(
                video_type=video_type,
                generation_kind=generation_kind,
                batch_index=base_count + eligible_seen,
                batch_size=len(scripts),
                already_allowed_in_batch=False,
            )
        text = update_script_topic_request_cta(script, allowed, reason)
        text = ensure_topic_request_fixed_comment(text, allowed)
        updated_scripts.append(text)
    return updated_scripts


def check_shorts_navigation_ng(script_text: str, video_type: str) -> list[str]:
    if not is_shorts_video_type(video_type):
        return []
    text = str(script_text or "")
    return [phrase for phrase in SHORTS_DIRECT_NAVIGATION_NG if phrase in text]


def build_cta_policy(
    video_type: str,
    generation_kind: str = "",
    topic_request_allowed: bool = False,
    topic_request_reason: str = "",
    final_cta_type: str = "",
) -> dict:
    is_shorts = is_shorts_video_type(video_type)
    topic_state = "allowed" if topic_request_allowed else "blocked"
    policy = {
        "cta_policy": {
            "shorts_loop_priority": is_shorts,
            "direct_next_video_promo_allowed": not is_shorts,
            "topic_request_cta": topic_state,
            "topic_request_cta_reason": topic_request_reason,
            "final_cta_type": final_cta_type or ("topic_request" if topic_request_allowed else "loop"),
        }
    }
    if not is_shorts:
        policy["long_policy"] = {
            "related_video_navigation_allowed": True,
            "vidiq_title_adjustment_allowed": True,
            "youtube_chapters_added": False,
        }
    return policy


def update_script_topic_request_cta(
    script_text: str,
    allowed: bool,
    reason: str = "",
) -> str:
    value = "許可" if allowed else "禁止"
    line = f"ネタ募集CTA: {value}"
    text = str(script_text or "").replace("\r\n", "\n")
    if re.search(r"(?m)^ネタ募集CTA\s*[:：].*$", text):
        text = re.sub(r"(?m)^ネタ募集CTA\s*[:：].*$", line, text)
    else:
        lines = text.splitlines()
        insert_at = 0
        for idx, raw in enumerate(lines[:24]):
            if re.match(r"^(?:動画形式|Format|動画タイトル|Title|サムネ文字|説明文|Description|タグ|Tags|固定コメント|生成区分|GenerationKind)\s*[:：]", raw.strip()):
                insert_at = idx + 1
        lines.insert(insert_at, line)
        text = "\n".join(lines)
    if reason:
        reason_line = f"ネタ募集CTA理由: {reason}"
        if re.search(r"(?m)^ネタ募集CTA理由\s*[:：].*$", text):
            text = re.sub(r"(?m)^ネタ募集CTA理由\s*[:：].*$", reason_line, text)
        else:
            text = text.replace(line, f"{line}\n{reason_line}", 1)
    return text


def default_topic_request_fixed_comment() -> str:
    return "次に見たい食べ物雑学ありますか？気になる食べ物をコメントで教えてね！"


def ensure_topic_request_fixed_comment(script_text: str, allowed: bool) -> str:
    if not allowed:
        return script_text
    text = str(script_text or "")
    if re.search(r"(?m)^固定コメント\s*[:：].+", text):
        return text
    comment = default_topic_request_fixed_comment()
    lines = text.splitlines()
    insert_at = 0
    for idx, raw in enumerate(lines[:24]):
        if re.match(r"^(?:動画形式|Format|動画タイトル|Title|サムネ文字|説明文|Description|タグ|Tags|ネタ募集CTA|ネタ募集CTA理由)\s*[:：]", raw.strip()):
            insert_at = idx + 1
    lines.insert(insert_at, f"固定コメント: {comment}")
    return "\n".join(lines)


def extract_chapter_names(script_text: str) -> list[str]:
    text = str(script_text or "")
    patterns = [
        r"(?m)^チャプター\s*[:：]\s*(.+)$",
        r"(?m)^Chapters?\s*[:：]\s*(.+)$",
    ]
    raw = ""
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            break
    if not raw:
        return []
    parts = re.split(r"\s*/\s*|\s*[、,]\s*", raw)
    names = []
    for part in parts:
        name = re.sub(r"^\s*\d+[.．、:：\s]*", "", part).strip()
        if name:
            names.append(name)
    return names


def build_youtube_chapters(chapter_names: list[str], duration_sec: int | None) -> str:
    names = [str(name).strip() for name in chapter_names if str(name).strip()]
    if len(names) < 3:
        return ""
    if not duration_sec or duration_sec <= 0:
        if len(names) <= 5:
            fallback = [0, 40, 100, 160, 230]
        else:
            fallback = [0, 40, 100, 160, 230, 290]
        lines = ["【目次】"]
        for idx, name in enumerate(names[: len(fallback)]):
            sec = fallback[idx]
            lines.append(f"{sec // 60}:{sec % 60:02d} {name}")
        return "\n".join(lines)

    max_time = max(30, int(duration_sec * 0.85))
    step = max(10, max_time // len(names))
    lines = ["【目次】"]
    for i, name in enumerate(names):
        sec = i * step
        lines.append(f"{sec // 60}:{sec % 60:02d} {name}")
    return "\n".join(lines)


def has_youtube_chapters(description: str) -> bool:
    return bool(re.search(r"(?m)^\d+:\d{2}\s+\S+", str(description or "")))


def append_long_youtube_chapters(description: str, script_text: str, duration_sec: int | None = None) -> tuple[str, bool]:
    desc = str(description or "").rstrip()
    if has_youtube_chapters(desc):
        return desc, False
    names = extract_chapter_names(script_text)
    if not names:
        return desc, False
    chapters = build_youtube_chapters(names, duration_sec)
    if not chapters:
        return desc, False
    return (desc + "\n\n" + chapters).strip(), True


def probe_duration_sec(media_path: str) -> int | None:
    if not media_path or not os.path.exists(media_path):
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                media_path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return int(float(proc.stdout.strip()))
    except Exception:
        # フォールバック許可: 尺は補助情報。ffprobe 失敗時は「不明(None)」として続行する。
        _logger.warning("ffprobe による尺取得に失敗: %s", media_path, exc_info=True)
        return None


def read_policy_file(output_dir: str) -> dict:
    local_id = os.path.basename(os.path.abspath(output_dir))
    from core.metadata_db import get_cta_policy, is_initialized, initialize_db
    if not is_initialized():
        initialize_db()
    return get_cta_policy(local_id)


def write_policy_file(output_dir: str, policy: dict) -> str:
    local_id = os.path.basename(os.path.abspath(output_dir))
    from core.metadata_db import upsert_cta_policy, is_initialized, initialize_db
    if not is_initialized():
        initialize_db()
    upsert_cta_policy(local_id, policy)
    return local_id
