import logging
import re
from config import CHARACTERS, CHARACTER_EXPRESSION_PNGS

class ScriptParser:
    _bg_re = re.compile(r'^(?:背景|Background|シーン|Scene)\d*[:：](.*)$', re.IGNORECASE)
    _dialogue_re = re.compile(r'^([^:：(（\[\]【]+)(?:\s*[（(]([^)）]+)[）)])?(?:\s*\[([^\]]+)\])?\s*[:：]\s*(.*)$')
    _telop_re = re.compile(r'^(?:テロップ|Telop)[:：](.*)$', re.IGNORECASE)
    _thumb_re = re.compile(r'^(?:サムネイル|Thumbnail)[:：](.*)$', re.IGNORECASE)
    _thumb_text_re = re.compile(r'^(?:サムネ文字|サムネテキスト)[:：](.*)$', re.IGNORECASE)
    _title_re = re.compile(r'^(?:動画タイトル|Title)[:：](.*)$', re.IGNORECASE)
    _desc_re = re.compile(r'^(?:説明文|Description)[:：](.*)$', re.IGNORECASE)
    _tags_re = re.compile(r'^(?:タグ|Tags?)[:：](.*)$', re.IGNORECASE)
    _format_re = re.compile(r'^(?:動画形式|Format)[:：](.*)$', re.IGNORECASE)
    _fixed_comment_re = re.compile(r'^(?:固定コメント|PinnedComment)[:：](.*)$', re.IGNORECASE)
    _generation_kind_re = re.compile(r'^(?:生成区分|GenerationKind)[:：](.*)$', re.IGNORECASE)
    _source_video_re = re.compile(r'^(?:元動画|派生元|SourceVideo)[:：](.*)$', re.IGNORECASE)
    _generation_purpose_re = re.compile(r'^(?:目的|生成目的|GenerationPurpose)[:：](.*)$', re.IGNORECASE)
    _character_pattern_re = re.compile(r'^(?:キャラパターン|CharacterPattern)[:：](.*)$', re.IGNORECASE)
    _genre_group_re = re.compile(r'^(?:ジャンル|Genre(?:Group)?)[:：](.*)$', re.IGNORECASE)
    _topic_request_cta_re = re.compile(r'^(?:ネタ募集CTA|TopicRequestCTA)[:：](.*)$', re.IGNORECASE)
    _topic_request_cta_reason_re = re.compile(r'^(?:ネタ募集CTA理由|TopicRequestCTAReason)[:：](.*)$', re.IGNORECASE)
    _screen_format_re = re.compile(r'^(?:画面形式|ScreenFormat)[:：](.*)$', re.IGNORECASE)
    _playlist_re = re.compile(r'^(?:再生リスト|Playlist)[:：](.*)$', re.IGNORECASE)
    _meeting_candidates_re = re.compile(r'^(?:候補ネタ|MeetingCandidates|Candidates)[:：](.*)$', re.IGNORECASE)
    _candidate_num_re = re.compile(r'^候補番号[:：](.*)$', re.IGNORECASE)
    _poll_options_re = re.compile(r'^(?:アンケート設定案|アンケート手動設定用|PollOptions)[:：]', re.IGNORECASE)
    _poll_options_marker_re = re.compile(r'^---\s*(?:アンケート設定案|アンケート手動設定用)\s*---')
    _chapter_re = re.compile(r'^(?:チャプター|チャプター一覧|Chapter(?:s|List)?)[:：]', re.IGNORECASE)
    _bracket_meta_re = re.compile(
        r'^【\s*(動画形式|Format|動画タイトル|Title|サムネ文字|サムネテキスト|サムネイル|Thumbnail|説明文|Description|タグ|Tags?|固定コメント|PinnedComment|生成区分|GenerationKind|元動画|派生元|SourceVideo|目的|生成目的|GenerationPurpose|ネタ募集CTA|TopicRequestCTA|ネタ募集CTA理由|TopicRequestCTAReason|候補ネタ|MeetingCandidates|Candidates)\s*】\s*(.*)$',
        re.IGNORECASE,
    )
    _bracket_meta_types = {
        "動画形式": "video_format",
        "format": "video_format",
        "動画タイトル": "video_title",
        "title": "video_title",
        "サムネ文字": "thumbnail_text",
        "サムネテキスト": "thumbnail_text",
        "サムネイル": "thumbnail",
        "thumbnail": "thumbnail",
        "説明文": "description",
        "description": "description",
        "タグ": "tags",
        "tags": "tags",
        "固定コメント": "fixed_comment",
        "pinnedcomment": "fixed_comment",
        "生成区分": "generation_kind",
        "generationkind": "generation_kind",
        "元動画": "source_video_title",
        "派生元": "source_video_title",
        "sourcevideo": "source_video_title",
        "目的": "generation_purpose",
        "生成目的": "generation_purpose",
        "generationpurpose": "generation_purpose",
        "キャラパターン": "character_pattern",
        "characterpattern": "character_pattern",
        "ジャンル": "genre_group",
        "genre": "genre_group",
        "genregroup": "genre_group",
        "ネタ募集cta": "topic_request_cta",
        "topicrequestcta": "topic_request_cta",
        "ネタ募集cta理由": "topic_request_cta_reason",
        "topicrequestctareason": "topic_request_cta_reason",
        "候補ネタ": "meeting_candidates",
        "meetingcandidates": "meeting_candidates",
        "candidates": "meeting_candidates",
    }
    _ignore_patterns = [
        re.compile(r'^```.*$'),
        re.compile(r'^━+.*━+$'),
        re.compile(r'^#.*$'),
        re.compile(r'^---.*$'),
        re.compile(r'^[（(].*[）)]$'),
        re.compile(r'^【.*】$'),
        re.compile(r'^\*.*\*$'),
        re.compile(r'^\s*$'),
    ]

    # Web UI / main.py で共通利用するメタタイプセット
    META_TYPES = frozenset({
        "thumbnail", "video_title", "description", "tags",
        "video_format", "screen_format", "thumbnail_text", "fixed_comment",
        "generation_kind", "source_video_title", "generation_purpose",
        "character_pattern", "genre_group", "topic_request_cta", "topic_request_cta_reason",
        "meeting_candidates", "poll_options", "playlist_categories",
    })

    @staticmethod
    def _parse_lines(line_iter):
        """行イテラブルから解析してアイテムリストを返す（parse/parse_string 共通コア）。"""
        bg_re = ScriptParser._bg_re
        dialogue_re = ScriptParser._dialogue_re
        telop_re = ScriptParser._telop_re
        thumb_re = ScriptParser._thumb_re
        thumb_text_re = ScriptParser._thumb_text_re
        title_re = ScriptParser._title_re
        desc_re = ScriptParser._desc_re
        tags_re = ScriptParser._tags_re
        format_re = ScriptParser._format_re
        fixed_comment_re = ScriptParser._fixed_comment_re
        generation_kind_re = ScriptParser._generation_kind_re
        source_video_re = ScriptParser._source_video_re
        generation_purpose_re = ScriptParser._generation_purpose_re
        character_pattern_re = ScriptParser._character_pattern_re
        genre_group_re = ScriptParser._genre_group_re
        topic_request_cta_re = ScriptParser._topic_request_cta_re
        topic_request_cta_reason_re = ScriptParser._topic_request_cta_reason_re
        meeting_candidates_re = ScriptParser._meeting_candidates_re
        candidate_num_re = ScriptParser._candidate_num_re
        poll_options_re = ScriptParser._poll_options_re
        poll_options_marker_re = ScriptParser._poll_options_marker_re
        bracket_meta_re = ScriptParser._bracket_meta_re
        ignore_patterns = ScriptParser._ignore_patterns

        lines = []
        last_dialogue = None
        last_meta = None

        for line in line_iter:
                line = line.strip()
                if not line:
                    continue

                # AI出力に含まれる装飾記号を除去
                line = line.replace("**", "").replace("__", "")

                # 【メタ項目名】値 形式の行を解析
                m = bracket_meta_re.match(line)
                if m:
                    label = m.group(1).strip().lower()
                    meta_type = ScriptParser._bracket_meta_types.get(label)
                    if meta_type:
                        item = {"type": meta_type, "text": m.group(2).strip()}
                        lines.append(item)
                        last_dialogue = None
                        last_meta = item
                        continue

                # メタ値の続き（description/meeting_candidates/fixed_comment/poll_options は複数行）
                if last_meta:
                    # アンケートマーカーは最優先でコンテキストを切り替える
                    if poll_options_marker_re.match(line):
                        last_meta = None
                        item = {"type": "poll_options", "text": ""}
                        lines.append(item)
                        last_dialogue = None
                        last_meta = item
                        continue
                    _multiline_types = ("description", "meeting_candidates", "fixed_comment", "poll_options")
                    _dialogue_safe_types = ("meeting_candidates", "fixed_comment", "poll_options")
                    is_keyword = any(r.match(line) for r in [bg_re, thumb_re, thumb_text_re, title_re, desc_re, tags_re, telop_re, format_re, fixed_comment_re, generation_kind_re, source_video_re, generation_purpose_re, character_pattern_re, genre_group_re, topic_request_cta_re, topic_request_cta_reason_re, ScriptParser._playlist_re, meeting_candidates_re, candidate_num_re, poll_options_re, bracket_meta_re])
                    is_dialogue = bool(dialogue_re.match(line))
                    is_ignore = any(p.match(line) for p in ignore_patterns)
                    if not is_keyword and (not is_dialogue or last_meta["type"] in _dialogue_safe_types) and (not is_ignore or last_meta["type"] in _multiline_types):
                        if last_meta["type"] in _multiline_types:
                            last_meta["text"] = (last_meta["text"] + "\n" + line).strip()
                            continue
                        elif not last_meta["text"]:
                            # 値が空の単一行フィールド：次の行を値として取り込む
                            val = line.strip()
                            last_meta["text"] = val.strip("()（）") if last_meta["type"] == "background" else val
                            last_meta = None
                            continue
                    last_meta = None  # キーワード処理へ

                # アンケートブロック開始（---アンケート設定案--- / ---アンケート手動設定用--- 形式）
                if poll_options_marker_re.match(line):
                    item = {"type": "poll_options", "text": ""}
                    lines.append(item)
                    last_dialogue = None
                    last_meta = item
                    continue

                # アンケートブロック開始（アンケート設定案: 形式）
                if poll_options_re.match(line):
                    item = {"type": "poll_options", "text": ""}
                    lines.append(item)
                    last_dialogue = None
                    last_meta = item
                    continue

                # 無視パターンに一致する行をスキップ
                if any(p.match(line) for p in ignore_patterns):
                    last_dialogue = None
                    last_meta = None
                    continue

                # チャプターマーカー（Longのみ・メタ扱い・無視）
                if ScriptParser._chapter_re.match(line):
                    last_dialogue = None
                    last_meta = None
                    continue

                # 背景
                m = bg_re.match(line)
                if m:
                    bg_text = m.group(1).strip().strip("()（）")
                    item = {"type": "background", "text": bg_text}
                    lines.append(item)
                    last_dialogue = None
                    last_meta = item if not bg_text else None
                    continue

                # メタデータ: thumbnail / video_title / description / tags
                matched_meta = False
                for meta_re, meta_type in [
                    (format_re, "video_format"),
                    (thumb_re, "thumbnail"),
                    (thumb_text_re, "thumbnail_text"),
                    (title_re, "video_title"),
                    (desc_re, "description"),
                    (tags_re, "tags"),
                    (fixed_comment_re, "fixed_comment"),
                    (generation_kind_re, "generation_kind"),
                    (source_video_re, "source_video_title"),
                    (generation_purpose_re, "generation_purpose"),
                    (character_pattern_re, "character_pattern"),
                    (genre_group_re, "genre_group"),
                    (topic_request_cta_re, "topic_request_cta"),
                    (topic_request_cta_reason_re, "topic_request_cta_reason"),
                    (ScriptParser._screen_format_re, "screen_format"),
                    (ScriptParser._playlist_re, "playlist_categories"),
                    (meeting_candidates_re, "meeting_candidates"),
                ]:
                    m = meta_re.match(line)
                    if m:
                        item = {"type": meta_type, "text": m.group(1).strip()}
                        lines.append(item)
                        last_dialogue = None
                        last_meta = item
                        matched_meta = True
                        break
                if matched_meta:
                    continue

                # 候補番号: → 既存 meeting_candidates に追記、なければ新規作成
                if not matched_meta and candidate_num_re.match(line):
                    existing_mc = next((it for it in reversed(lines) if it["type"] == "meeting_candidates"), None)
                    if existing_mc:
                        existing_mc["text"] = (existing_mc["text"] + "\n" + line).strip()
                        last_meta = existing_mc
                    else:
                        item = {"type": "meeting_candidates", "text": line}
                        lines.append(item)
                        last_meta = item
                    last_dialogue = None
                    continue

                # テロップ
                m = telop_re.match(line)
                if m:
                    lines.append({"type": "telop", "text": m.group(1).strip()})
                    last_dialogue = None
                    last_meta = None
                    continue

                # セリフ行
                m = dialogue_re.match(line)
                if m:
                    char_name = m.group(1).strip()
                    emotion = m.group(2) if m.group(2) else None
                    expression = m.group(3).strip() if m.group(3) else None
                    text = m.group(4).strip()

                    # 右括弧のみの誤字補正 (例: 四国めたん)[驚き]: )
                    if char_name.endswith(")") or char_name.endswith("）"):
                        char_name = char_name[:-1].strip()
                        if not emotion:
                            emotion = "ツンツン" if "めたん" in char_name else "ノーマル"
                            logging.getLogger(__name__).warning(f"台本形式を補正: {m.group(1).strip()}[{expression or ''}] → {char_name}({emotion})[{expression or ''}]")
                    
                    if not emotion:
                        emotion = "ノーマル"

                    # セリフ本文に混入した感情タグの分離 (例: 四国めたん(ツンツン): [驚き]セリフ )
                    m_exp = re.match(r'^\[([^\]]+)\]\s*(.*)$', text)
                    if m_exp and not expression:
                        expression = m_exp.group(1).strip()
                        text = m_exp.group(2).strip()

                    # キャラ名を正規化
                    found_char_name = "ずんだもん"  # デフォルト
                    for key in CHARACTERS:
                        if key in char_name:
                            found_char_name = CHARACTERS[key]["name"]
                            break

                    # 句読点・記号のみのセリフは読み上げ不能なのでスキップ
                    if not text.strip("。、！？…・〜　 "):
                        last_meta = None
                        continue

                    new_item = {
                        "type": "dialogue",
                        "character": found_char_name,
                        "emotion": emotion,
                        "expression": expression,
                        "text": text,
                    }
                    lines.append(new_item)
                    last_dialogue = new_item
                    last_meta = None
                    continue

                # 直前のセリフの続き行
                if last_dialogue and not any(p.match(line) for p in ignore_patterns):
                    if line.startswith(('*', '-', '・')):
                        last_dialogue = None
                        continue
                    if line:
                        separator = "" if last_dialogue["text"].endswith(('。', '！', '？', '.', '!', '?')) else " "
                        last_dialogue["text"] += separator + line

        return lines

    @staticmethod
    def parse(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return ScriptParser._parse_lines(line.strip() for line in f)

    @staticmethod
    def parse_meeting_candidates(text: str) -> list:
        candidates = []
        current = {}
        for line in text.splitlines():
            line = line.strip()
            if not line: continue
            
            m_num = re.match(r'^候補番号[:：]\s*(.+)$', line)
            if m_num:
                if current:
                    candidates.append(current)
                    current = {}
                current["number"] = m_num.group(1).strip()
                continue
                
            if m_title := re.match(r'^候補タイトル[:：]\s*(.+)$', line):
                current["title"] = m_title.group(1).strip()
            elif m_cat := re.match(r'^分類[:：]\s*(.+)$', line):
                current["category"] = m_cat.group(1).strip()
            elif m_src := re.match(r'^横展開元[:：]\s*(.+)$', line):
                current["source_video"] = m_src.group(1).strip()
            elif m_evi := re.match(r'^実績根拠[:：]\s*(.+)$', line):
                current["evidence"] = m_evi.group(1).strip()
            elif m_risk := re.match(r'^既存重複リスク[:：]\s*(.+)$', line):
                current["duplicate_risk"] = m_risk.group(1).strip()
            elif m_thumb := re.match(r'^サムネ一言[:：]\s*(.+)$', line):
                current["thumbnail_word"] = m_thumb.group(1).strip()
            elif m_hook := re.match(r'^冒頭1秒案[:：]\s*(.+)$', line):
                current["opening_hook"] = m_hook.group(1).strip()
            elif m_judg := re.match(r'^めたん判定[:：]\s*(.+)$', line):
                current["metan_judgement"] = m_judg.group(1).strip()
                    
        if current:
            candidates.append(current)
        return candidates

    @staticmethod
    def parse_poll_options(text: str) -> dict:
        """poll_options メタテキストから question / options / memo を抽出する。"""
        question = ""
        options: list[str] = []
        memo = ""
        current_key: str | None = None
        pending: str = ""

        def _flush():
            nonlocal question, memo, pending, current_key
            val = pending.strip()
            if not val or not current_key:
                return
            if current_key == "question":
                question = val
            elif current_key == "option":
                options.append(val)
            elif current_key == "memo":
                memo = val
            pending = ""
            current_key = None

        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                _flush()
                continue
            if re.match(r'^質問[:：](.*)', line):
                _flush()
                val = re.sub(r'^質問[:：]\s*', '', line)
                if val:
                    question = val
                else:
                    current_key = "question"
            elif m := re.match(r'^選択肢\d+[:：](.*)', line):
                _flush()
                val = m.group(1).strip()
                if val:
                    options.append(val)
                else:
                    current_key = "option"
            elif re.match(r'^メモ[:：](.*)', line):
                _flush()
                val = re.sub(r'^メモ[:：]\s*', '', line)
                if val:
                    memo = val
                else:
                    current_key = "memo"
            else:
                if current_key:
                    pending = (pending + "\n" + line).strip() if pending else line
        _flush()

        # YouTubeライブ投票は最大4択
        extra = [o for o in options[4:] if o]
        options = [o for o in options[:4] if o]
        if extra:
            suffix = "5件目以降: " + " / ".join(extra)
            memo = (memo + " / " + suffix) if memo else suffix

        return {"question": question, "options": options, "memo": memo}

    @staticmethod
    def format_poll_copy(poll_data: dict) -> str:
        """poll_options dict を YouTube アンケート用コピーテキストに整形する。"""
        lines: list[str] = []
        if poll_data.get("question"):
            lines.append(poll_data["question"])
            lines.append("")
        for i, opt in enumerate(poll_data.get("options", []), 1):
            lines.append(f"{i}. {opt}")
        if poll_data.get("memo"):
            lines.append("")
            lines.append(f"※{poll_data['memo']}")
        return "\n".join(lines)

    # ブロック境界パターン（extract_non_body_blocks 用）
    _BODY_START_RE = re.compile(r'^(?:背景|Background|シーン|Scene)\d*[:：]', re.IGNORECASE)
    _FC_START_RE = re.compile(r'^固定コメント[:：](.*)', re.IGNORECASE)
    _POLL_START_RE = re.compile(r'^(?:アンケート設定案|アンケート手動設定用|PollOptions)[:：]', re.IGNORECASE)
    _POLL_MARKER_RE = re.compile(r'^---\s*(?:アンケート設定案|アンケート手動設定用)\s*---')
    _CANDIDATE_START_RE = re.compile(r'^候補番号[:：]', re.IGNORECASE)

    @staticmethod
    def extract_non_body_blocks(raw_text: str) -> dict:
        """台本テキストから本編（body_text）と非本編ブロックを分離して返す。

        戻り値キー:
          body_text            ScriptParser に渡す本編テキスト（ヘッダ + 本編セリフのみ）
          candidates_text      候補一覧ブロックの生テキスト
          fixed_comment_text   固定コメントブロックの本文（ヘッダ行を除いた値）
          poll_options_text    アンケートブロックの生テキスト
          has_candidates       bool
          has_fixed_comment    bool
          has_poll_options     bool
        """
        BODY_START = ScriptParser._BODY_START_RE
        FC_START = ScriptParser._FC_START_RE
        POLL_START = ScriptParser._POLL_START_RE
        POLL_MARKER = ScriptParser._POLL_MARKER_RE
        CAND_START = ScriptParser._CANDIDATE_START_RE

        lines = raw_text.splitlines()

        header_lines: list[str] = []
        candidate_lines: list[str] = []
        body_lines: list[str] = []
        fc_lines: list[str] = []
        poll_lines: list[str] = []

        # state: "pre_body" | "candidates" | "body" | "fixed_comment" | "poll"
        state = "pre_body"

        for line in lines:
            s = line.strip()

            # ──── 状態遷移チェック ────
            # 本編開始（背景: 行）
            if state in ("pre_body", "candidates") and BODY_START.match(s):
                state = "body"
                body_lines.append(line)
                continue

            # 本編終了：固定コメント
            if state == "body" and FC_START.match(s):
                state = "fixed_comment"
                m = FC_START.match(s)
                inline = m.group(1).strip() if m else ""
                if inline:
                    fc_lines.append(inline)
                continue

            # 本編/固定コメント終了：アンケート
            if state in ("body", "fixed_comment") and (POLL_START.match(s) or POLL_MARKER.match(s)):
                state = "poll"
                # マーカー行自体は保持（parse_poll_options が使う）
                poll_lines.append(line)
                continue

            # ──── 各状態でラインを振り分け ────
            if state == "pre_body":
                if CAND_START.match(s):
                    state = "candidates"
                    candidate_lines.append(line)
                else:
                    header_lines.append(line)

            elif state == "candidates":
                candidate_lines.append(line)

            elif state == "body":
                body_lines.append(line)

            elif state == "fixed_comment":
                fc_lines.append(line)

            elif state == "poll":
                poll_lines.append(line)

        # ──── body_text を構築 ────
        if state == "pre_body":
            # 背景: が一度も出なかった = 通常台本または未生成 → 全文をそのまま返す
            return {
                "body_text": raw_text,
                "candidates_text": "",
                "fixed_comment_text": "",
                "poll_options_text": "",
                "has_candidates": False,
                "has_fixed_comment": False,
                "has_poll_options": False,
            }

        candidates_text = "\n".join(candidate_lines).strip()
        fixed_comment_text = "\n".join(fc_lines).strip()
        poll_options_text = "\n".join(poll_lines).strip()

        # header + 候補ブロック（meeting_candidates メタ化）+ 本編
        body_parts: list[str] = ["\n".join(header_lines)]
        if candidates_text:
            # ScriptParser の meeting_candidates 継続パースに乗せる
            body_parts.append("候補ネタ:\n" + candidates_text)
        body_parts.append("\n".join(body_lines))
        body_text = "\n".join(p for p in body_parts if p.strip()).strip()

        return {
            "body_text": body_text,
            "candidates_text": candidates_text,
            "fixed_comment_text": fixed_comment_text,
            "poll_options_text": poll_options_text,
            "has_candidates": bool(candidates_text),
            "has_fixed_comment": bool(fixed_comment_text),
            "has_poll_options": bool(poll_options_text),
        }

    @staticmethod
    def parse_string(text: str):
        return ScriptParser._parse_lines(line.strip() for line in text.splitlines())

    @staticmethod
    def validate(items):
        """パース済みアイテムを検証し (is_valid, messages) を返す。"""
        errors = []
        warnings = []

        if not items:
            errors.append("台本が空、または正しく読み取れませんでした。フォーマットを確認してください。")
            return False, errors

        dialogue_count = sum(1 for item in items if item["type"] == "dialogue")
        bg_count = sum(1 for item in items if item["type"] == "background")

        # セリフなし
        if dialogue_count == 0:
            errors.append("セリフが一つも見つかりませんでした。「キャラ名(感情): セリフ」の形式になっているか確認してください。")

        # セリフが極端に少ない（パース失敗の可能性）
        if 0 < dialogue_count < 5:
            errors.append(f"セリフ数が{dialogue_count}行しかありません。パースに失敗している可能性があります。")

        # 空のセリフ
        empty_dialogues = [i for i, it in enumerate(items) if it["type"] == "dialogue" and not it["text"].strip()]
        if empty_dialogues:
            errors.append(f"セリフのテキストが空の行があります（{len(empty_dialogues)}箇所）。フォーマットを確認してください。")

        # タイトルが空・または不正な内容（パース失敗）
        title_items = [it for it in items if it["type"] == "video_title"]
        if title_items:
            title_text = title_items[0]["text"].strip()
            if not title_text:
                errors.append("動画タイトルが取得できませんでした。「動画タイトル: タイトル」の形式を確認してください。")
            elif "[Shorts]" in title_text or "Shorts_" in title_text or "動画形式" in title_text or "サムネ文字" in title_text or "【" in title_text:
                errors.append(f"動画タイトルに不正な内容が含まれています: 「{title_text}」。パースに失敗している可能性があります。")
            elif "\n" in title_text or len(title_text) > 100:
                errors.append(f"動画タイトルに改行または不正な内容が含まれています: 「{title_text[:50]}...」。「動画タイトル: タイトル」を1行に収めてください。")

        # 背景なし
        if bg_count == 0:
            warnings.append("背景(背景: ...)が設定されていません。")

        # 背景テキストが空（次行形式のパース失敗）
        empty_bgs = [i for i, it in enumerate(items) if it["type"] == "background" and not it["text"].strip()]
        if empty_bgs:
            errors.append(f"背景プロンプトが空の箇所があります（{len(empty_bgs)}箇所）。「背景: プロンプト」の形式を確認してください。")

        # 不明キャラクター
        known_names = [info["name"] for info in CHARACTERS.values()]
        unknown = set()
        for item in items:
            if item["type"] == "dialogue" and item["character"] not in known_names:
                unknown.add(item["character"])
        if unknown:
            warnings.append(f"不明なキャラクター名が見つかりました: {', '.join(unknown)}")

        known_expressions = {
            char_name: set(expressions.keys())
            for char_name, expressions in CHARACTER_EXPRESSION_PNGS.items()
        }
        unknown_expressions = set()
        expression_count = 0
        for item in items:
            if item["type"] != "dialogue":
                continue
            expression = str(item.get("expression") or "").strip()
            if not expression:
                continue
            expression_count += 1
            if expression not in known_expressions.get(item.get("character"), set()):
                unknown_expressions.add(f"{item.get('character')}[{expression}]")
        if unknown_expressions:
            warnings.append(f"不明な表情指定が見つかりました（nativeでは既定表情にフォールバックします）: {', '.join(sorted(unknown_expressions))}")
        if expression_count >= 6:
            warnings.append(f"表情指定が{expression_count}回あります。Shortsでは強い表情変化は3〜5回までが目安です。")
        if dialogue_count and expression_count == dialogue_count:
            warnings.append("全セリフに表情指定があります。意味のある場面だけに絞ってください。")

        is_valid = len(errors) == 0
        return is_valid, errors + warnings
