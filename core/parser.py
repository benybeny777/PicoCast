import re
from config import CHARACTERS

class ScriptParser:
    _bg_re = re.compile(r'^(?:背景|Background|シーン|Scene)\d*[:：](.*)$', re.IGNORECASE)
    _dialogue_re = re.compile(r'^([^:：(（【]+)(?:\s*[（(]([^)）]+)[）)])?\s*[:：]\s*(.*)$')
    _telop_re = re.compile(r'^(?:テロップ|Telop)[:：](.*)$', re.IGNORECASE)
    _thumb_re = re.compile(r'^(?:サムネイル|Thumbnail)[:：](.*)$', re.IGNORECASE)
    _thumb_text_re = re.compile(r'^(?:サムネ文字|サムネテキスト)[:：](.*)$', re.IGNORECASE)
    _title_re = re.compile(r'^(?:動画タイトル|Title)[:：](.*)$', re.IGNORECASE)
    _desc_re = re.compile(r'^(?:説明文|Description)[:：](.*)$', re.IGNORECASE)
    _tags_re = re.compile(r'^(?:タグ|Tags?)[:：](.*)$', re.IGNORECASE)
    _format_re = re.compile(r'^(?:動画形式|Format)[:：](.*)$', re.IGNORECASE)
    _fixed_comment_re = re.compile(r'^(?:固定コメント|PinnedComment)[:：](.*)$', re.IGNORECASE)
    _bracket_meta_re = re.compile(
        r'^【\s*(動画形式|Format|動画タイトル|Title|サムネ文字|サムネテキスト|サムネイル|Thumbnail|説明文|Description|タグ|Tags?)\s*】\s*(.*)$',
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

    @staticmethod
    def parse(file_path):
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
        bracket_meta_re = ScriptParser._bracket_meta_re
        ignore_patterns = ScriptParser._ignore_patterns

        lines = []
        last_dialogue = None

        last_meta = None

        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # Clean up common AI decorations
                line = line.replace("**", "").replace("__", "")

                # Metadata header style:
                # 【動画タイトル】
                # タイトル
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

                # Continuation of metadata (description=multi-line, others=next-line-only)
                if last_meta:
                    is_keyword = any(r.match(line) for r in [bg_re, thumb_re, thumb_text_re, title_re, desc_re, tags_re, telop_re, format_re, fixed_comment_re, bracket_meta_re])
                    is_dialogue = bool(dialogue_re.match(line))
                    is_ignore = any(p.match(line) for p in ignore_patterns)
                    if not is_keyword and not is_dialogue and (not is_ignore or last_meta["type"] == "description"):
                        if last_meta["type"] == "description":
                            last_meta["text"] = (last_meta["text"] + "\n" + line).strip()
                            continue
                        elif not last_meta["text"]:
                            # 値が空の単一行フィールド：次の行を値として取り込む
                            val = line.strip()
                            last_meta["text"] = val.strip("()（）") if last_meta["type"] == "background" else val
                            last_meta = None
                            continue
                    last_meta = None  # fall through to keyword processing

                # Check ignore patterns
                if any(p.match(line) for p in ignore_patterns):
                    last_dialogue = None
                    last_meta = None
                    continue

                # Background
                m = bg_re.match(line)
                if m:
                    bg_text = m.group(1).strip().strip("()（）")
                    item = {"type": "background", "text": bg_text}
                    lines.append(item)
                    last_dialogue = None
                    last_meta = item if not bg_text else None
                    continue

                # Metadata: thumbnail / video_title / description / tags
                matched_meta = False
                for meta_re, meta_type in [
                    (format_re, "video_format"),
                    (thumb_re, "thumbnail"),
                    (thumb_text_re, "thumbnail_text"),
                    (title_re, "video_title"),
                    (desc_re, "description"),
                    (tags_re, "tags"),
                    (fixed_comment_re, "fixed_comment"),
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

                # Telop
                m = telop_re.match(line)
                if m:
                    lines.append({"type": "telop", "text": m.group(1).strip()})
                    last_dialogue = None
                    last_meta = None
                    continue

                # Dialogue
                m = dialogue_re.match(line)
                if m:
                    char_name = m.group(1).strip()
                    emotion = m.group(2) if m.group(2) else "ノーマル"
                    text = m.group(3).strip()

                    # Normalize character name
                    found_char_name = "ずんだもん" # default
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
                        "text": text,
                    }
                    lines.append(new_item)
                    last_dialogue = new_item
                    last_meta = None
                    continue

                # Continuation of previous dialogue
                if last_dialogue and not any(p.match(line) for p in ignore_patterns):
                    if line.startswith(('*', '-', '・')):
                        last_dialogue = None
                        continue
                    if line:
                        separator = "" if last_dialogue["text"].endswith(('。', '！', '？', '.', '!', '?')) else " "
                        last_dialogue["text"] += separator + line
        
        return lines

    @staticmethod
    def parse_string(text: str):
        """文字列から直接パースする。"""
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', encoding='utf-8', delete=False) as f:
            f.write(text)
            tmp = f.name
        try:
            return ScriptParser.parse(tmp)
        finally:
            os.unlink(tmp)

    @staticmethod
    def validate(items):
        """Validates the parsed items and returns (is_valid, messages)."""
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
            elif "[Shorts]" in title_text or "動画形式" in title_text or "サムネ文字" in title_text or "【" in title_text:
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

        is_valid = len(errors) == 0
        return is_valid, errors + warnings
