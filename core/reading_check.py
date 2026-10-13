"""読みが分かれる語（読み違いの可能性）を、音声合成の前に見つける。

台本の元の文（漢字のまま）を VOICEVOX の audio_query に渡すと、VOICEVOX がどう読むかを
AquesTalk 風のカタカナ（`kana`。例: `カ'ライノダ`）で返す。これを形態素解析（Sudachi）の読みと比べ、
漢字を含む語で2つの解析の読みが分かれる箇所を「読み違いの可能性」として出す。
音声を聞き直す（Whisper など）必要がなく、合成前に一瞬で調べられる。

読み補正が full_hiragana（全部ひらがな）のとき、音声は Sudachi の読みで作られる。分かれた語は
Sudachi の読みが文脈に合っていない（例: 辛いカレー → つらい）おそれがあるため確認が要る。
どちらが正しいかは決めない。利用者が画面で確認し、正しい読みを基本辞書へ登録する
（core/reading_dictionary_store.py）。基本辞書に登録済みの語は出さない。

比較は発音に寄せて揃える。辞書の読みは表記どおり（トウキョウ・助詞のハ）で、VOICEVOX は
発音どおり（トーキョー・ワ）のため、長音・助詞・ヲ/ヅ/ヂを1文字ずつ置き換えて比べる
（置き換えは1対1なので、食い違った位置から元の読みをそのまま取り出せる）。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_KANJI = re.compile(r"[一-鿿々〆ヵヶ]")
# VOICEVOX の kana に入る記号（アクセント・句切り・読点・無声化・疑問）
_KANA_SYMBOLS = re.compile(r"['/、_？?]")
_PARTICLE_PRONUNCIATION = {"ハ": "ワ", "ヘ": "エ", "ヲ": "オ"}
_SAME_SOUND = str.maketrans({"ヲ": "オ", "ヅ": "ズ", "ヂ": "ジ"})

_VOWEL_ROWS = {
    "a": "アカガサザタダナハバパマヤラワァャヮ",
    "i": "イキギシジチヂニヒビピミリィ",
    "u": "ウクグスズツヅヌフブプムユルゥュヴ",
    "e": "エケゲセゼテデネヘベペメレェ",
    "o": "オコゴソゾトドノホボポモヨロヲォョ",
}
_VOWEL_OF = {kana: vowel for vowel, row in _VOWEL_ROWS.items() for kana in row}
_VOWEL_KANA = {"a": "ア", "i": "イ", "u": "ウ", "e": "エ", "o": "オ"}


@dataclass(frozen=True)
class Finding:
    """読み違いの可能性がある1語。"""
    word: str             # 台本上の表記（漢字を含む）
    expected_reading: str  # 辞書（Sudachi）の読み（ひらがな）
    voicevox_reading: str  # VOICEVOX が読もうとしている読み（ひらがな）
    text: str              # 見つかった台本の文


def _to_hiragana(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def clean_voicevox_kana(kana: str) -> str:
    """VOICEVOX の kana から記号を除いたカタカナ列。"""
    return _KANA_SYMBOLS.sub("", kana or "")


def pronunciation_key(katakana: str) -> str:
    """発音に寄せた比較用の文字列（入力と同じ長さ）。

    ー は直前の母音へ、オ段・ウ段の後のウはオ・ウへ、エ段の後のイはエへ（トウ→トオ、セイ→セエ）。
    """
    chars = list(katakana.translate(_SAME_SOUND))
    for i, c in enumerate(chars):
        prev_vowel = _VOWEL_OF.get(chars[i - 1]) if i else None
        if c == "ー" and prev_vowel:
            chars[i] = _VOWEL_KANA[prev_vowel]
        elif c == "ウ" and prev_vowel in ("o", "u"):
            chars[i] = _VOWEL_KANA[prev_vowel]
        elif c == "イ" and prev_vowel == "e":
            chars[i] = "エ"
    return "".join(chars)


class ReadingChecker:
    """台本の文と VOICEVOX の kana を比べる。Sudachi の辞書を1度だけ読み込んで使い回す。"""

    def __init__(self):
        from sudachipy import dictionary, tokenizer

        self._tokenizer = dictionary.Dictionary().create()
        self._mode = tokenizer.Tokenizer.SplitMode.C

    def _expected(self, text: str) -> tuple[str, list[tuple[int, int, str, str]]]:
        """辞書の読み（カタカナ）と、各語の (開始, 終了, 表記, 読み) の一覧。"""
        reading_parts = []
        spans = []
        pos = 0
        for token in self._tokenizer.tokenize(text, self._mode):
            surface = token.surface()
            reading = token.reading_form()
            if not reading or reading == "*" or not re.fullmatch(r"[ァ-ヶー]+", reading):
                # 記号・英数字など読みの比較に使えない語は、両側から外す必要があるため比較をあきらめる
                reading = ""
            if token.part_of_speech()[0] == "助詞" and reading in _PARTICLE_PRONUNCIATION:
                reading = _PARTICLE_PRONUNCIATION[reading]
            spans.append((pos, pos + len(reading), surface, reading))
            reading_parts.append(reading)
            pos += len(reading)
        return "".join(reading_parts), spans

    def compare(self, text: str, voicevox_kana: str) -> list[Finding]:
        """1つの文について、漢字を含む語で読みが食い違うものを返す。"""
        expected, spans = self._expected(text)
        actual = clean_voicevox_kana(voicevox_kana)
        if not expected or not actual:
            return []
        matcher = difflib.SequenceMatcher(None, pronunciation_key(expected), pronunciation_key(actual), autojunk=False)
        opcodes = matcher.get_opcodes()
        if all(tag == "equal" for tag, *_ in opcodes):
            return []

        def to_actual(position: int, *, end: bool) -> int:
            for tag, i1, i2, j1, j2 in opcodes:
                if i1 <= position < i2 or (end and position == i2):
                    return j1 + (position - i1) if tag == "equal" else (j2 if end else j1)
            return len(actual)

        findings = []
        for tag, i1, i2, _j1, _j2 in opcodes:
            if tag == "equal":
                continue
            for start, stop, surface, reading in spans:
                overlaps = start < max(i2, i1 + 1) and stop > i1
                if not overlaps or not reading or not _KANJI.search(surface):
                    continue
                voiced = actual[to_actual(start, end=False):to_actual(stop, end=True)]
                if pronunciation_key(voiced) == pronunciation_key(reading) or not voiced:
                    continue
                finding = Finding(surface, _to_hiragana(reading), _to_hiragana(voiced), text)
                if finding not in findings:
                    findings.append(finding)
        return findings


def covered_by_base_dict(word: str, base_dict: dict[str, str]) -> bool:
    """基本辞書（利用者が確認した読み）で読みが決まる語か。基本辞書は部分一致で置換される。"""
    return any(key and key in word for key in base_dict)


def check_and_record(pairs: list[tuple[str, str]], source: str) -> list[Finding]:
    """(台本の元の文, その文の VOICEVOX の kana) の組を比べ、見つかったものを記録して返す。"""
    from core import reading_dictionary_store

    checker = ReadingChecker()
    base_dict = reading_dictionary_store.load_dict("base")
    findings: list[Finding] = []
    for text, kana in pairs:
        for finding in checker.compare(text, kana):
            if finding not in findings and not covered_by_base_dict(finding.word, base_dict):
                findings.append(finding)
    reading_dictionary_store.record_findings(findings, source)
    return findings


def describe(finding: Finding) -> str:
    """ログ・画面向けの1行。"""
    return f"{finding.word}（VOICEVOX: {finding.voicevox_reading} / 形態素解析: {finding.expected_reading}）"
