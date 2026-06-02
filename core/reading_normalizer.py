"""
VOICEVOXの読み間違い対策。
LLMによる全文変換を廃止し、形態素解析（SudachiPy）と自前辞書を組み合わせた
「安全な自動読み補正」と「辞書育成」を行います。
字幕には元テキストをそのまま使用し、音声合成用テキストのみを補正します。
"""
import re
from config import config as _cfg
from core import reading_dictionary_store

def _kata_to_hira(text: str) -> str:
    """カタカナをひらがなに変換する"""
    res = []
    for c in text:
        if '\u30a1' <= c <= '\u30f6':
            res.append(chr(ord(c) - 0x60))
        elif c == 'ー':
            res.append(c)
        else:
            res.append(c)
    return "".join(res)

class ReadingNormalizer:
    def __init__(self):
        self.mode = getattr(_cfg, "VOICE_READING_MODE", "safe_auto")
        self._available = self.mode in ("dictionary", "safe_auto")
        
        self.base_dict = {}
        self.user_dict = {}
        self.candidates = {}
        
        # 統計・ロギング用
        self.applied_base = set()
        self.applied_user = set()
        self.applied_auto = set()
        self.skipped_terms = set()
        
        if self._available:
            self._load_dicts()
            
            if self.mode == "safe_auto":
                try:
                    from sudachipy import dictionary, tokenizer
                    self.tokenizer_obj = dictionary.Dictionary().create()
                    self.split_mode = tokenizer.Tokenizer.SplitMode.C
                except ImportError as e:
                    raise RuntimeError(
                        f"よみがな補正({self.mode})に必要なライブラリがありません: {e}\n"
                        "pip install sudachipy sudachidict_core を実行してください。"
                    ) from e

    def _load_dicts(self):
        dictionaries = reading_dictionary_store.load_all()
        self.base_dict = dictionaries["base"]
        self.user_dict = dictionaries["user"]
        self.candidates = reading_dictionary_store.load_candidates()

    def _save_dicts(self):
        reading_dictionary_store.save_dict("user", self.user_dict)
        reading_dictionary_store.save_candidates(self.candidates)

    def normalize_batch(self, texts: list[str]) -> dict[str, str]:
        """複数テキストを一括でよみがな補正する。"""
        if not self._available:
            return {t: t for t in texts}

        result = {}
        for t in texts:
            result[t] = self._normalize_single(t)
            
        if self.mode == "safe_auto":
            self._save_dicts()
            
        return result

    def _normalize_single(self, text: str) -> str:
        if self.mode == "off":
            return text
            
        if self.mode == "dictionary":
            # Sudachi非依存の単純置換（ベース辞書優先、長い語から置換）
            res = text
            merged = {**self.user_dict, **self.base_dict}
            for k in sorted(merged.keys(), key=len, reverse=True):
                if k in res:
                    res = res.replace(k, merged[k])
                    if k in self.base_dict:
                        self.applied_base.add(k)
                    else:
                        self.applied_user.add(k)
            return res

        # safe_auto
        # base_dictをトークン化前に前処理置換（長い順に優先）。
        # 「黒い」のような活用形も「黒」→「くろ」に展開できる。
        pre_text = text
        for k in sorted(self.base_dict.keys(), key=len, reverse=True):
            if k in pre_text:
                pre_text = pre_text.replace(k, self.base_dict[k])
                self.applied_base.add(k)

        tokens = self.tokenizer_obj.tokenize(pre_text)
            
        res_text = []
        has_kanji = re.compile(r'[\u4E00-\u9FFF]')
        
        for t in tokens:
            surface = t.surface()
            
            # ユーザー辞書（base_dictは前処理済み）
            if surface in self.user_dict:
                res_text.append(self.user_dict[surface])
                self.applied_user.add(surface)
                continue
                
            pos = t.part_of_speech()
            pos1, pos2 = pos[0], pos[1]
            
            # 除外判定
            if len(surface) == 1 and has_kanji.search(surface):
                self.skipped_terms.add(surface)
                res_text.append(surface)
                continue
            if pos1 in ("動詞", "形容詞", "助詞", "助動詞", "補助記号", "記号"):
                res_text.append(surface)
                continue
            if not has_kanji.search(surface):
                res_text.append(surface)
                continue
                
            reading = t.reading_form()
            if not reading or reading == "*":
                self.skipped_terms.add(surface)
                res_text.append(surface)
                continue
                
            hiragana = _kata_to_hira(reading)
            
            # 自動置換条件 (安全な名詞類)
            is_safe_auto = False
            if pos1 == "名詞":
                if len(surface) >= 2 and pos2 != "数詞":
                    is_safe_auto = True
                elif pos2 == "固有名詞":
                    is_safe_auto = True
                    
            if is_safe_auto:
                self.user_dict[surface] = hiragana
                self.applied_auto.add(surface)
                res_text.append(hiragana)
                continue
            
            # 判断が怪しい語は候補へ
            if surface not in self.candidates:
                self.candidates[surface] = {
                    "surface": surface,
                    "reading": hiragana,
                    "reason": f"POS: {pos1},{pos2}",
                    "source": "safe_auto",
                    "auto_applied": False,
                    "review_required": True
                }
            self.skipped_terms.add(surface)
            res_text.append(surface)
            
        return "".join(res_text)

    def load_cache(self, saved: dict[str, str]) -> None:
        pass  # 互換性維持

    def get_meta_info(self):
        return {
            "mode": self.mode,
            "applied_base_terms": list(self.applied_base),
            "applied_user_terms": list(self.applied_user),
            "applied_auto_terms": list(self.applied_auto),
            "skipped_terms": list(self.skipped_terms)
        }
