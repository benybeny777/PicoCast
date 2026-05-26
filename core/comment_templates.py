"""
固定コメント自動生成テンプレート。
四国めたん調（お嬢様口調・軽い毒舌）でコメントを生成する。
"""
import random
import re

_NORMAL_TEMPLATES_WITH_TOPIC = [
    "{topic}のこと、知ってましたの？ 知ってた人は正直に白状なさいですわ。",
    "{topic}のイメージ、ちょっと変わりましたの？ コメントで教えなさいですわ。",
    "{topic}で他にも気になる謎があれば、コメントに置いていきなさいですわ。",
    "まさか{topic}のこと、常識だと思ってましたの？ コメントで教えなさい。",
    "{topic}、知ってたらなかなかの食べ物オタクですわ。あなたはどうでしたの？",
    "「{topic}の話、知らなかった」ですむと思ってますの？ 感想を書きなさいですわ。",
    "{topic}について一番意外だったこと、コメントで教えなさい。",
    "{topic}、ずんだもんより先に気づけた人はいますの？",
]

_NORMAL_TEMPLATES_GENERIC = [
    "これ知ってましたの？ 知ってた人は正直に白状なさいですわ。",
    "まさかこれ、常識だと思ってましたの？ コメントで教えなさい。",
    "知ってたらなかなかの食べ物オタクですわ。あなたはどうでしたの？",
    "ずんだもんより先に気づけた人、いますの？",
    "これを知ってた人、ちょっと尊敬してあげますわ。",
    "「知らなかった」ですむと思ってますの？ 感想を書きなさいですわ。",
    "あなたの中で一番意外だった食べ物雑学、コメントで教えなさい。",
    "これ、家族や友達に言いたくなりましたの？",
]

_TOPIC_REQUEST_TEMPLATES_WITH_TOPIC = [
    "{topic}みたいな食べ物の謎、他にも気になるものがあればコメントに置いていきなさいですわ。面白ければ採用して差し上げますわ。",
    "次に調べてほしい食べ物、コメントで投げなさい。{topic}くらい面白ければ採用しますわ。",
    "{topic}以外にも「なんで？」と思う食べ物があれば、コメントで教えなさい。めたんが査定してあげますわ。",
]

_TOPIC_REQUEST_TEMPLATES_GENERIC = [
    "次に調べてほしい食べ物、コメントで投げなさい。面白ければ採用して差し上げますわ。",
    "食べ物の「なんで？」をコメントで教えなさい。めたんが査定してあげますわ。",
    "あなたが気になってる食べ物の謎、コメントに置いていきなさいですわ。",
    "次のネタ候補、庶民の知恵を見せてごらんなさい。",
    "「これ調べてほしい」って食べ物、コメントで出しなさい。採用されるかはセンス次第ですわ。",
]


def _extract_topic(title: str) -> str | None:
    """タイトルから食べ物・話題名を簡易抽出する。取れない場合はNone。"""
    cleaned = re.sub(r"[\[【（(][^\]】）)]*[\]】）)]", "", title).strip()
    # 「の/は/が/で/と」より前の部分をトピックとして使う
    m = re.match(r"^(.+?)[のはがでとをに！？!?]", cleaned)
    if m:
        topic = m.group(1).strip()
        if 2 <= len(topic) <= 15:
            return topic
    return None


def build_fixed_comment(title: str, mode: str = "normal") -> str:
    """
    めたん調の固定コメントを生成する。

    Args:
        title: 動画タイトル
        mode: "normal" または "topic_request"
    """
    topic = _extract_topic(title)

    if mode == "topic_request":
        if topic:
            template = random.choice(_TOPIC_REQUEST_TEMPLATES_WITH_TOPIC)
            return template.format(topic=topic)
        return random.choice(_TOPIC_REQUEST_TEMPLATES_GENERIC)

    if topic:
        template = random.choice(_NORMAL_TEMPLATES_WITH_TOPIC)
        return template.format(topic=topic)
    return random.choice(_NORMAL_TEMPLATES_GENERIC)
