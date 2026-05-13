import requests
import os
from config import VOICEVOX_URL, VOICE_SPEED_SCALE

class VoicevoxAPI:
    def __init__(self, base_url=VOICEVOX_URL):
        self.base_url = base_url

    def check_connection(self):
        try:
            response = requests.get(f"{self.base_url}/version", timeout=5)
            return response.status_code == 200
        except:
            return False

    def generate_audio(self, text, speaker_id, output_path, volume_scale=2.0, speed_scale=VOICE_SPEED_SCALE):
        # 1. Audio Query
        params = (
            ('text', text),
            ('speaker', speaker_id),
        )
        response = requests.post(f"{self.base_url}/audio_query", params=params, timeout=10)
        if response.status_code != 200:
            raise Exception(f"Failed to generate audio query: {response.text}")

        query = response.json()
        kana = query.get("kana", "")
        query["volumeScale"] = volume_scale
        query["speedScale"] = speed_scale

        # 2. Synthesis
        params = (
            ('speaker', speaker_id),
        )
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with requests.post(
            f"{self.base_url}/synthesis",
            headers={'Content-Type': 'application/json'},
            params=params,
            json=query,
            timeout=30,
            stream=True,
        ) as response:
            if response.status_code != 200:
                raise Exception(f"Failed to synthesize audio: {response.text}")
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        
        return output_path, kana
