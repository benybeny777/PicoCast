import requests
import os
from config import (
    VOICEVOX_URL,
    VOICE_SPEED_SCALE,
    VOICE_POST_PHONEME_LENGTH,
    VOICEVOX_CONNECTION_TIMEOUT_SEC,
    VOICEVOX_QUERY_TIMEOUT_SEC,
    VOICEVOX_SYNTHESIS_TIMEOUT_SEC,
)

class VoicevoxAPI:
    def __init__(self, base_url=VOICEVOX_URL):
        self.base_url = base_url

    def check_connection(self):
        try:
            with requests.get(f"{self.base_url}/version", timeout=VOICEVOX_CONNECTION_TIMEOUT_SEC) as response:
                return response.status_code == 200
        except Exception:
            return False

    def _post(self, path, **kwargs):
        """VOICEVOX へ POST する。接続不可・タイムアウトは対処手順つきの AppError に包む。

        呼び出し側は `except Exception` で `str(e)` を表示するため、生の
        ConnectionError ではなく「VOICEVOX を起動してください」と分かる例外にする。
        """
        from core.error_codes import AppError
        try:
            return requests.post(f"{self.base_url}{path}", **kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            raise AppError("E-VOICEVOX-DOWN", detail=self.base_url, cause=e)

    def audio_query_only(self, text, speaker_id, volume_scale=2.0, speed_scale=VOICE_SPEED_SCALE,
                         post_phoneme_length=VOICE_POST_PHONEME_LENGTH):
        """audio_query のみ実行してクエリ辞書を返す（並列化用）。"""
        params = (('text', text), ('speaker', speaker_id))
        with self._post("/audio_query", params=params, timeout=VOICEVOX_QUERY_TIMEOUT_SEC) as response:
            if response.status_code != 200:
                raise Exception(f"Failed to generate audio query: {response.text}")
            query = response.json()
        kana = query.get("kana", "")
        query["volumeScale"] = volume_scale
        query["speedScale"] = speed_scale
        query["postPhonemeLength"] = post_phoneme_length
        return query, kana

    def synthesis_only(self, query, speaker_id, output_path):
        """synthesis のみ実行（audio_query_only の結果を使う）。"""
        params = (('speaker', speaker_id),)
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._post(
            "/synthesis",
            headers={'Content-Type': 'application/json'},
            params=params,
            json=query,
            timeout=VOICEVOX_SYNTHESIS_TIMEOUT_SEC,
            stream=True,
        ) as response:
            if response.status_code != 200:
                raise Exception(f"Failed to synthesize audio: {response.text}")
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

    def generate_audio(self, text, speaker_id, output_path, volume_scale=2.0, speed_scale=VOICE_SPEED_SCALE,
                       post_phoneme_length=VOICE_POST_PHONEME_LENGTH):
        query, kana = self.audio_query_only(text, speaker_id, volume_scale, speed_scale, post_phoneme_length)
        self.synthesis_only(query, speaker_id, output_path)
        return output_path, kana
