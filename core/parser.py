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
    _chapter_re = re.compile(r'^(?:チャプター|チャプター一覧|Chapter(?:s|List)?)[:：]', re.IGNORECASE)
    _bracket_meta_re = re.compile(
        r'^【\s*(動画形式|Format|動画タイトル|Title|サムネ文字|サムネテキスト|サムネイル|Thumbnail|説明文|Description|タグ|Tags?|固定コメント|PinnedComment|生成区分|GenerationKind|元動画|派生元|SourceVideo|目的|生成目的|GenerationPurpose|ネタ募集CTA|TopicRequestCTA|ネタ募集CTA理由|TopicRequestCTAReason)\s*】\s*(.*)$',
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

    # main.py / gui.py で共通利用するメタタイプセット
    META_TYPES = frozenset({
        "thumbnail", "video_title", "description", "tags",
        "video_format", "thumbnail_text", "fixed_comment",
        "generation_kind", "source_video_title", "generation_purpose",
        "character_pattern", "genre_group", "topic_request_cta", "topic_request_cta_reason",
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

                # メタ値の続き（description=複数行、それ以外=次の1行のみ）
                if last_meta:
                    is_keyword = any(r.match(line) for r in [bg_re, thumb_re, thumb_text_re, title_re, desc_re, tags_re, telop_re, format_re, fixed_comment_re, generation_kind_re, source_video_re, generation_purpose_re, character_pattern_re, genre_group_re, topic_request_cta_re, topic_request_cta_reason_re, bracket_meta_re])
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
                    last_meta = None  # キーワード処理へ

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
                    emotion = m.group(2) if m.group(2) else "ノーマル"
                    expression = m.group(3).strip() if m.group(3) else None
                    text = m.group(4).strip()

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
