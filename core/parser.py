import re
from config import CHARACTERS

class ScriptParser:
    _bg_re = re.compile(r'^(?:背景|Background|シーン|Scene)\d*[:：](.*)$', re.IGNORECASE)
    _dialogue_re = re.compile(r'^([^:：(（【]+)(?:\s*[（(]([^)）]+)[）)])?\s*[:：]\s*(.*)$')
    _telop_re = re.compile(r'^(?:テロップ|Telop)[:：](.*)$', re.IGNORECASE)
    _thumb_re = re.compile(r'^(?:サムネイル|Thumbnail)[:：](.*)$', re.IGNORECASE)
    _title_re = re.compile(r'^(?:動画タイトル|Title)[:：](.*)$', re.IGNORECASE)
    _desc_re = re.compile(r'^(?:説明文|Description)[:：](.*)$', re.IGNORECASE)
    _tags_re = re.compile(r'^(?:タグ|Tags?)[:：](.*)$', re.IGNORECASE)
    _format_re = re.compile(r'^(?:動画形式|Format)[:：](.*)$', re.IGNORECASE)
    _ignore_patterns = [
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
        title_re = ScriptParser._title_re
        desc_re = ScriptParser._desc_re
        tags_re = ScriptParser._tags_re
        format_re = ScriptParser._format_re
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

                # Continuation of description (before ignore patterns to preserve #hashtag lines)
                if last_meta and last_meta["type"] == "description":
                    is_keyword = any(r.match(line) for r in [bg_re, thumb_re, title_re, desc_re, tags_re, telop_re])
                    if not is_keyword:
                        last_meta["text"] = (last_meta["text"] + "\n" + line).strip()
                        continue
                    else:
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
                    lines.append({"type": "background", "text": bg_text})
                    last_dialogue = None
                    last_meta = None
                    continue

                # Metadata: thumbnail / video_title / description / tags
                matched_meta = False
                for meta_re, meta_type in [
                    (format_re, "video_format"),
                    (thumb_re, "thumbnail"),
                    (title_re, "video_title"),
                    (desc_re, "description"),
                    (tags_re, "tags"),
                ]:
                    m = meta_re.match(line)
                    if m:
                        item = {"type": meta_type, "text": m.group(1).strip()}
                        lines.append(item)
                        last_dialogue = None
                        last_meta = item if meta_type == "description" else None
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
    def validate(items):
        """Validates the parsed items and returns (is_valid, messages)."""
        errors = []
        warnings = []
        
        if not items:
            errors.append("台本が空、または正しく読み取れませんでした。フォーマットを確認してください。")
            return False, errors
            
        dialogue_count = sum(1 for item in items if item["type"] == "dialogue")
        bg_count = sum(1 for item in items if item["type"] == "background")
        
        if dialogue_count == 0:
            errors.append("セリフが一つも見つかりませんでした。「名前: セリフ」の形式になっているか確認してください。")
        
        if bg_count == 0:
            warnings.append("背景(背景: ...)が設定されていません。")
            
        # Check for unknown characters (best effort)
        known_names = [info["name"] for info in CHARACTERS.values()]
        for item in items:
            if item["type"] == "dialogue":
                if item["character"] not in known_names:
                    warnings.append(f"不明なキャラクター名が見つかりました: {item['character']}")
        
        is_valid = len(errors) == 0
        return is_valid, errors + warnings
