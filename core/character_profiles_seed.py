"""キャラクター設定の初期データと、台本プロンプトへの合成。

台本テンプレートからキャラ設定（役割・口調・禁止台詞・掛け合い）を分離し、
生成時に有効なキャラクター設定を合成する。

- `CHARACTER_FOOD_TOXIC_GENRE_PROFILES`: 四国めたんを「辛口相方ツッコミ（ずんだハウス風）」にする。
- 都市伝説など他ジャンル: 従来の「お嬢様毒舌めたん」を使う。
- 自動フォールバック禁止: 有効なキャラ設定が無いチャンネルは compose 側でエラーにする。
"""
from __future__ import annotations

from core.character_profile_store import (
    CharacterProfile,
    create_character,
    list_characters,
    update_character,
)
from config import (
    AQUESTALK_DEFAULT_PITCH,
    AQUESTALK_DEFAULT_SPEED,
    AQUESTALK_DEFAULT_VOLUME,
    AQUESTALK_MARISA_SPEAKER_KEY,
    AQUESTALK_MARISA_VOICE_TYPE,
    AQUESTALK_REIMU_SPEAKER_KEY,
    AQUESTALK_REIMU_VOICE_TYPE,
    CHARACTERS,
    CHARACTER_FOOD_TOXIC_GENRE_PROFILES,
)
from core.path_refs import asset_ref
from core.script_prompts import METAN_TSUNDERE_RULES


# ─────────────────────────────────────────────────────────────────────────────
# キャラクター設定の本文（seed 用）
# ─────────────────────────────────────────────────────────────────────────────

_ZUNDAMON = {
    "character_key": "zundamon",
    "display_name": "ずんだもん（ナビ役）",
    "character_name": "ずんだもん",
    "role": "情報を出すナビ役。事実・理由・答え・背景・結論を出すのはずんだもん。新情報を出す / 理由を説明する / 誤解を訂正する / 今との違いを説明する / 具体例を出す / 結論を出す。",
    "tone_style": "ボクっ娘。語尾は「〜なのだ」。明るく高テンポ。ときどきお茶目に失敗・大げさに驚く。",
    "speaking_rules": "1セリフは原則11〜15文字。説明口調・ナレーション調にしない。掛け合いで情報を届ける。",
    "forbidden_phrases": "",
    "dialogue_rules": "めたんの辛口ツッコミに落ち込みすぎず、強い事実で返す（例:「ここからが本題なのだ」「でも理由を聞くと変わるのだ」）。情報の主導権はずんだもんが持つ。",
    "voice_backend": "voicevox",
    "voice_speaker": str(CHARACTERS["ずんだもん"]["speaker_id"]),
    "voice_speaker_id": CHARACTERS["ずんだもん"]["speaker_id"],
    "voice_styles": CHARACTERS["ずんだもん"]["styles"],
    "portrait_png_path": asset_ref("assets/characters/zundamon.png"),
    "credit_required": True,
    "credit_text": "VOICEVOX:ずんだもん",
}

# 四国めたん（辛口相方ツッコミ・ずんだハウス風）= 食べ物雑学堂用
_METAN_FOOD_TOXIC = {
    "character_key": "metan_food_toxic",
    "display_name": "辛口相方めたん（ずんだハウス風）",
    "character_name": "四国めたん",
    "role": (
        "四国めたんは情報を持っている説明役ではない。食べ物雑学の事実・理由・答え・背景・結論を説明しない。"
        "ずんだもんの発言を復唱しない。ただ同意しない。ただ驚く相槌を言わない。補足説明もしない。"
        "役割は、ずんだもんの説明に対して、視聴者目線の疑問・違和感・浅さ・既知ネタ臭・構成の弱さを短く突っ込み、"
        "ずんだもんから次の情報を引き出すこと。情報・理由・答え・背景・結論は基本ずんだもんが出す。"
    ),
    "tone_style": (
        "口の悪い辛口相方・辛口編集者・雑なツッコミ役。"
        "「ですわ」連発は禁止。丁寧なお嬢様口調に寄せすぎない。"
        "「あんた」を使ってよい。「〜じゃん」「〜だろ」「〜でしょ」「〜なのよ」「〜わね」「〜しなさい」を使ってよい。"
        "ツッコミは長く説教せず1文か短い2文で切る。毎回キレず、呆れ・雑な流し・冷たい一言も混ぜる。"
        "視聴者を馬鹿にしない。実在企業・商品を過度に攻撃しない。食べ物そのものを汚く罵らない。"
    ),
    "speaking_rules": (
        "推奨ツッコミ型（語尾・距離感・速度・雑さの参考。丸暗記でなく雰囲気を再現する）:\n"
        "- あんた、それで引けると思ってるの？ / で、何が意外なのよ。 / そこが薄いのよ。 / 理由を先に言いなさいよ。\n"
        "- それ、有名すぎるだろ。 / また説明書みたいになってるじゃん。 / 普通に言うな、刺して言いなさい。\n"
        "- はい浅い、もう一段。 / そこを最初に言えよ。 / だから3秒で消えるのよ。 / 逃げんな。 / 適当すぎるだろ。\n"
        "- と、言えよ。 / 興味だけで進めるな。 / 知らん。 / マジかよ。 / 良かったですね。 / 無の極みですね。"
    ),
    "forbidden_phrases": (
        "そうですわね / なるほどですわ / その通りですわ / つまり〇〇ですわね / 〇〇ということですの？ / "
        "補足すると〇〇ですわ / 理由は〇〇ですわ / 実は〇〇なのよ / すごいですわね / 知らなかったですわ / "
        "えっ、そうなの？ / 本当ですの？ / 驚きですわね（これらおよび同義の復唱・同意・説明・驚きだけの単独使用を禁止）"
    ),
    "dialogue_rules": (
        "基本構造（情報を前に進めるループ）: 1.ずんだもんが意外な事実 2.めたんが「それだけだと弱い/で理由は？/有名すぎる」と突っ込む "
        "3.ずんだもんが理由 4.めたんが「まだ浅い/今と何が違うの？」とさらに突っ込む 5.ずんだもんがもう一段深い情報 "
        "6.めたんが短く雑に刺す 7.ずんだもんがループに戻す。\n"
        "情報密度: 掛け合いは必ず情報を前に進める。ただの驚き・相槌・罵倒・尺稼ぎは禁止。\n"
        "Shorts1本に最低でも「何が意外か」「なぜそうなったか」「今の食べ物・見た目・名前・食べ方とのつながり」の3点を入れる。\n"
        "悪い例: ずんだもん「ちくわの穴には理由があるのだ」→めたん「そうなのですわね」（禁止）。\n"
        "良い例: ずんだもん「ちくわの穴、飾りじゃないのだ」→めたん「それで引けると思ってるの」→ずんだもん「火を均一に通すためなのだ」→めたん「そこが薄い、なんで穴なのよ」→ずんだもん「棒に巻いて焼くからなのだ」→めたん「そこを最初に言えよ」。\n"
        "自己チェック（1つでも該当したら作り直す）: めたんが情報・理由・答えを説明していないか / 復唱・同意・相槌だけになっていないか / "
        "「ですわ」連発・お嬢様口調になっていないか / ツッコミが長すぎないか / ずんだもんが情報・理由・答えを出しているか / "
        "掛け合いが情報を前に進めているか / ただの毒舌で尺を使っていないか。"
    ),
    "voice_backend": "voicevox",
    "voice_speaker": str(CHARACTERS["めたん"]["speaker_id"]),
    "voice_speaker_id": CHARACTERS["めたん"]["speaker_id"],
    "voice_styles": CHARACTERS["めたん"]["styles"],
    "portrait_png_path": asset_ref("assets/characters/metan.png"),
    "credit_required": True,
    "credit_text": "VOICEVOX:四国めたん",
}

# 四国めたん（お嬢様毒舌）= 都市伝説など従来チャンネル用。既存の共通ルールを温存する。
_METAN_STANDARD_TOXIC = {
    "character_key": "metan_standard_toxic",
    "display_name": "毒舌めたん（お嬢様・標準）",
    "character_name": "四国めたん",
    "role": "視聴者代表の強毒舌ツッコミ役・辛口編集者・毒舌プロデューサー。情報の説明はしない（主導権はずんだもん）。",
    "tone_style": "プライド高めのお嬢様口調。「〜ですわ」「〜よ」を使う強めの毒舌ツッコミ。",
    "speaking_rules": "毒舌・疑問・反論・皮肉・違和感のいずれかを各セリフに必ず含める。原則11〜15文字。",
    "forbidden_phrases": (
        "なるほどですわ / そうなのですわね / すごいですわ / 知らなかったですわ / 便利ですわね / "
        "つまり〇〇ですわね（相槌・共感だけの単独使用を禁止）"
    ),
    # 既存の毒舌ルール本文をそのまま温存（都市伝説チャンネルの挙動を変えない）
    "dialogue_rules": METAN_TSUNDERE_RULES.strip(),
    "voice_backend": "voicevox",
    "voice_speaker": str(CHARACTERS["めたん"]["speaker_id"]),
    "voice_speaker_id": CHARACTERS["めたん"]["speaker_id"],
    "voice_styles": CHARACTERS["めたん"]["styles"],
    "portrait_png_path": asset_ref("assets/characters/metan.png"),
    "credit_required": True,
    "credit_text": "VOICEVOX:四国めたん",
}

_REIMU = {
    "character_key": "reimu",
    "display_name": "ゆっくり霊夢風（司会）",
    "character_name": "霊夢",
    "role": "落ち着いた司会・進行役。視聴者目線で話題を整理し、必要な疑問を短く挟む。情報を出しすぎず、会話の入口と締めを担当する。",
    "tone_style": "冷静で少しドライ。語尾は自然な口語。「〜ね」「〜よ」「どういうこと？」を使う。過剰に可愛くしない。",
    "speaking_rules": "1セリフは短く、進行・疑問・要約を中心にする。説明が長くなったら他キャラへ渡す。",
    "forbidden_phrases": "なのだ / ですわ / だぜ / 長い解説の独占",
    "dialogue_rules": "霊夢は会話の交通整理役。導入でテーマを提示し、途中で視聴者の疑問を代弁し、最後に短くまとめる。",
    "voice_backend": "aquestalk",
    "voice_speaker": AQUESTALK_REIMU_SPEAKER_KEY,
    "voice_type": AQUESTALK_REIMU_VOICE_TYPE,
    "voice_speed": AQUESTALK_DEFAULT_SPEED,
    "voice_pitch": AQUESTALK_DEFAULT_PITCH,
    "voice_volume": AQUESTALK_DEFAULT_VOLUME,
    "portrait_png_path": asset_ref("assets/characters/reimu.png"),
    "credit_required": True,
    "credit_text": "AquesTalk:ゆっくり霊夢風",
}

_MARISA = {
    "character_key": "marisa",
    "display_name": "ゆっくり魔理沙風（相方）",
    "character_name": "魔理沙",
    "role": "勢いのある相方・ツッコミ役。疑問、驚き、軽い茶化しでテンポを作り、話を前に進める。",
    "tone_style": "明るく少し雑。語尾は「〜だぜ」「〜じゃないか」「マジか」を使う。強すぎる罵倒は避ける。",
    "speaking_rules": "1セリフは短くテンポ重視。驚きだけで終わらず、次の情報を引き出す問いにする。",
    "forbidden_phrases": "なのだ / ですわ / ただの相槌 / 視聴者を馬鹿にする表現",
    "dialogue_rules": "魔理沙は霊夢や他キャラの説明に対し、驚きと疑問で次の説明を引き出す。情報そのものを長く説明しない。",
    "voice_backend": "aquestalk",
    "voice_speaker": AQUESTALK_MARISA_SPEAKER_KEY,
    "voice_type": AQUESTALK_MARISA_VOICE_TYPE,
    "voice_speed": AQUESTALK_DEFAULT_SPEED,
    "voice_pitch": AQUESTALK_DEFAULT_PITCH,
    "voice_volume": AQUESTALK_DEFAULT_VOLUME,
    "portrait_png_path": asset_ref("assets/characters/marisa.png"),
    "credit_required": True,
    "credit_text": "AquesTalk:ゆっくり魔理沙風",
}


def _seed_set_for_genre(genre_profile: str) -> list[dict]:
    """ジャンルに応じた seed セット（ずんだもん＋めたん両バリアント）を返す。

    めたんは「辛口相方」「お嬢様毒舌」の両方を投入し、UIでトグル切替できるようにする。
    ジャンル既定のめたんだけ enabled=True、もう一方は enabled=False。
    （compose は enabled のみ合成するため、同名キャラは原則1つだけ有効にする）
    """
    is_food = (genre_profile or "") in CHARACTER_FOOD_TOXIC_GENRE_PROFILES
    return [
        {**_ZUNDAMON, "sort_order": 10, "enabled": True},
        {**_METAN_FOOD_TOXIC, "sort_order": 20, "enabled": is_food},
        {**_METAN_STANDARD_TOXIC, "sort_order": 21, "enabled": not is_food},
        {**_REIMU, "sort_order": 30, "enabled": False},
        {**_MARISA, "sort_order": 31, "enabled": False},
    ]


def seed_character_profiles_for_profile(profile_id: str, genre_profile: str) -> int:
    """指定チャンネルにキャラクター設定を投入する。

    冪等・追補式: 既存の character_key はそのまま、未投入の key だけ追加する。
    （新規チャンネルのseed と、既存チャンネルへのバリアント追補の両方に使える）
    戻り値: 新規作成した件数。
    """
    existing_keys = {c.character_key for c in list_characters(profile_id)}
    created = 0
    for item in _seed_set_for_genre(genre_profile):
        if item["character_key"] in existing_keys:
            continue
        create_character(
            profile_id=profile_id,
            character_key=item["character_key"],
            display_name=item["display_name"],
            character_name=item["character_name"],
            role=item.get("role", ""),
            tone_style=item.get("tone_style", ""),
            speaking_rules=item.get("speaking_rules", ""),
            forbidden_phrases=item.get("forbidden_phrases", ""),
            dialogue_rules=item.get("dialogue_rules", ""),
            voice_backend=item.get("voice_backend", "voicevox"),
            voice_speaker=item.get("voice_speaker", ""),
            voice_speaker_id=item.get("voice_speaker_id"),
            voice_styles=item.get("voice_styles"),
            voice_type=item.get("voice_type", ""),
            voice_speed=item.get("voice_speed"),
            voice_pitch=item.get("voice_pitch"),
            voice_volume=item.get("voice_volume"),
            portrait_png_path=item.get("portrait_png_path", ""),
            credit_required=item.get("credit_required", True),
            credit_text=item.get("credit_text", ""),
            enabled=item.get("enabled", True),
            sort_order=item.get("sort_order", 0),
        )
        created += 1
    return created


# 空欄補完の対象（旧seedで作成され音声・立ち絵・クレジットが空のままのキャラを補う）
_BACKFILL_FIELDS = (
    "voice_backend", "voice_speaker", "voice_speaker_id", "voice_styles",
    "voice_type", "voice_speed", "voice_pitch", "voice_volume",
    "portrait_png_path", "credit_text",
)


def _is_empty(value) -> bool:
    return value is None or value == "" or value == {} or value == []


def _has_voice_identity(character: CharacterProfile) -> bool:
    """話者が一つでも設定済みか（=ユーザーが触った形跡があるか）。"""
    return (
        bool((character.voice_speaker or "").strip())
        or character.voice_speaker_id is not None
        or bool(character.voice_styles)
    )


def backfill_character_profiles_from_seed(profile_id: str, genre_profile: str) -> int:
    """既存キャラの空フィールドを seed 既定値で補完する（非破壊・冪等）。

    旧 seed で作成され音声/立ち絵/クレジットが空のままのチャンネル向けの移行処理。
    話者がまだ一つも設定されていないキャラ（=未移行とみなせる行）だけを対象にし、
    既に値が入っているフィールドは上書きしない。戻り値: 補完したキャラ件数。
    """
    seed_by_key = {item["character_key"]: item for item in _seed_set_for_genre(genre_profile)}
    updated = 0
    for character in list_characters(profile_id):
        seed_item = seed_by_key.get(character.character_key)
        # seed に無いキャラ・既に話者設定済みのキャラはユーザー資産として尊重し触らない
        if not seed_item or _has_voice_identity(character):
            continue
        patch: dict = {}
        for field in _BACKFILL_FIELDS:
            if not _is_empty(getattr(character, field, None)) or _is_empty(seed_item.get(field)):
                continue
            patch[field] = seed_item.get(field)
        if patch:
            update_character(character.character_id, **patch)
            updated += 1
    return updated


# 既存テンプレートに直書きされていた「めたん毒舌ルール」の検出マーカー。
# これを含む script テンプレートは、キャラ設定分離後に該当ブロックを除去する対象。
_LEGACY_CHARACTER_MARKER = "四国めたん 役割固定ルール"


def ensure_character_profiles_all() -> dict[str, int]:
    """全 channel profile にキャラクター設定が無ければ投入する（既存テンプレ済みチャンネルの移行用）。"""
    from core.channel_profile import list_profiles
    results: dict[str, int] = {}
    for profile in list_profiles():
        try:
            results[profile.profile_id] = seed_character_profiles_for_profile(
                profile.profile_id, profile.genre_profile
            )
            # 旧seedで作成され音声/立ち絵/クレジットが空のままの既存キャラを既定値で補完する
            backfill_character_profiles_from_seed(profile.profile_id, profile.genre_profile)
        except Exception:
            raise
    return results


def migrate_strip_character_rules_from_templates() -> int:
    """既存の script テンプレートからキャラ設定の長文（旧めたん毒舌ルール）を除去する。

    キャラ設定は character_profiles で管理し、生成時に合成するため、テンプレート側に
    直書きされた旧ブロックを取り除く。マーカーを含むテンプレートだけを対象にする（冪等）。
    戻り値: 更新したテンプレート数。
    """
    from core.channel_profile import list_profiles
    from core.prompt_template_store import get_default_template, update_template
    from core.prompt_template_seeder import _load_common_script_rules

    updated = 0
    for profile in list_profiles():
        tmpl = get_default_template(profile.profile_id, "script")
        if tmpl is None or not tmpl.script_rules:
            continue
        if _LEGACY_CHARACTER_MARKER not in tmpl.script_rules:
            continue
        # キャラ設定を含まない新しい共通ルールへ置き換える
        update_template(
            tmpl.template_id,
            profile_id=profile.profile_id,
            script_rules=_load_common_script_rules(profile.genre_profile),
        )
        updated += 1
    return updated


def compose_character_section(profile_id: str) -> str:
    """有効なキャラクター設定を合成して台本プロンプト用セクションを返す。

    自動フォールバック禁止: 有効なキャラ設定が1つも無ければ RuntimeError。
    """
    chars = list_characters(profile_id, enabled_only=True)
    if not chars:
        raise RuntimeError(
            f"profile '{profile_id}' に有効なキャラクター設定がありません。"
            "設定画面またはシードでキャラクター設定を作成してください（標準めたんへの自動フォールバックはしません）。"
        )
    blocks = [
        "━━━━━━━━━━━━━━━━━━",
        "キャラクター設定（最優先・厳守）",
        "━━━━━━━━━━━━━━━━━━",
        "本チャンネルの登場キャラクターは以下に固定する。役割・口調・禁止表現・掛け合いを厳守する。",
        "上の共通ルールや分量ルールにキャラ口調の指定があっても、本セクションを最優先する。",
    ]
    for c in chars:
        blocks.append(_format_character(c))
    return "\n\n".join(blocks)


def _format_character(c: CharacterProfile) -> str:
    lines = [f"### {c.character_name}（{c.display_name}）"]
    if c.role:
        lines.append(f"- 役割: {c.role}")
    if c.tone_style:
        lines.append(f"- 口調: {c.tone_style}")
    if c.speaking_rules:
        lines.append(f"- 話し方:\n{c.speaking_rules}")
    if c.forbidden_phrases:
        lines.append(f"- 禁止表現: {c.forbidden_phrases}")
    if c.dialogue_rules:
        lines.append(f"- 掛け合いルール:\n{c.dialogue_rules}")
    return "\n".join(lines)
