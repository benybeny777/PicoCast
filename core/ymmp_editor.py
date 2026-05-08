import json
import uuid
import os
import base64

class YmmpEditor:
    def __init__(self, width=1920, height=1080, fps=60, debug=False):
        self.debug = debug
        self.width = width
        self.height = height
        self.fps = fps
        self.project = {
            "Resolution": {"Width": width, "Height": height},
            "Fps": fps,
            "FilePath": "",
            "SelectedTimelineIndex": 0,
            "Timelines": [
                {
                    "ID": str(uuid.uuid4()),
                    "Name": "メイン",
                    "Items": [],
                    "VideoInfo": {
                        "Width": width,
                        "Height": height,
                        "FPS": fps
                    }
                }
            ],
            "Characters": [],
            "LayoutXml": ""
        }
        self.templates = {}
        template_path = os.path.join(os.path.dirname(__file__), "character_templates.json")
        if os.path.exists(template_path):
            with open(template_path, "r", encoding="utf-8") as f:
                self.templates = json.load(f)

    _NAME_MAP = {"めたん": "四国めたん", "ずんだ": "ずんだもん"}

    @classmethod
    def _resolve_name(cls, name):
        return cls._NAME_MAP.get(name, name)

    @staticmethod
    def _anim_value(value):
        """Wrap a scalar into a YMM4 animatable value object."""
        return {
            "Values": [{"Value": float(value)}],
            "Span": 0.0,
            "AnimationType": "なし",
            "Bezier": {
                "Points": [
                    {"Point": {"X": 0.0, "Y": 0.0}, "ControlPoint1": {"X": -0.3, "Y": -0.3}, "ControlPoint2": {"X": 0.3, "Y": 0.3}},
                    {"Point": {"X": 1.0, "Y": 1.0}, "ControlPoint1": {"X": -0.3, "Y": -0.3}, "ControlPoint2": {"X": 0.3, "Y": 0.3}}
                ],
                "IsQuadratic": False
            }
        }

    def add_character(self, name, char_id=None):
        # Check if exists
        for char in self.project["Characters"]:
            if char["Name"] == name:
                return

        if not char_id:
            char_id = str(uuid.uuid4())

        if name in self.templates:
            import copy
            char_data = dict(self.templates[name])  # shallow copy
            # deep-copy only the field we mutate below
            if "FontSize" in char_data:
                char_data["FontSize"] = copy.deepcopy(char_data["FontSize"])
            char_data["Id"] = char_id
            if "$type" not in char_data:
                char_data["$type"] = "YukkuriMovieMaker.Project.CharacterParameter, YukkuriMovieMaker"
            # Scale font size for portrait (Shorts) layout
            font_size = 65.0
            if "FontSize" in char_data and "Values" in char_data["FontSize"]:
                for v in char_data["FontSize"]["Values"]:
                    v["Value"] = font_size
            self.project["Characters"].append(char_data)
        else:
            # Fallback to minimal definition with simple numbers
            self.project["Characters"].append({
                "$type": "YukkuriMovieMaker.Project.CharacterParameter, YukkuriMovieMaker",
                "Id": char_id,
                "Name": name,
                "Voice": {
                    "SourceType": "VOICEVOX",
                    "VoiceId": "0",
                    "Volume": 100.0,
                    "Speed": 100.0,
                    "Pitch": 0.0,
                    "Intonation": 100.0,
                },
                "X": 0.0,
                "Y": 0.0,
                "Scale": 100.0,
                "Opacity": 100.0,
            })

    def _get_character_id(self, name):
        target_name = self._resolve_name(name)
        
        for char in self.project["Characters"]:
            if char["Name"] == target_name:
                return char["Id"]
        
        # 新規登録
        new_id = str(uuid.uuid4())
        self.add_character(target_name, new_id)
        return new_id

    def add_voice_item(self, character_name, text, hatsuon=None, file_path=None, start_frame=0, duration=100, layer=2, volume=200.0):
        resolved_name = self._resolve_name(character_name)
        self._get_character_id(resolved_name)  # ensure registered

        item = {
            "$type": "YukkuriMovieMaker.Project.Items.VoiceItem, YukkuriMovieMaker",
            "CharacterName": resolved_name,
            "FilePath": os.path.abspath(file_path) if file_path else "",
            "Serif": text,
            "Hatsuon": hatsuon if hatsuon else "",
            "Decorations": [],
            "IsWaveformEnabled": False,
            "Frame": start_frame,
            "Length": duration,
            "Layer": layer,
            "Volume": self._anim_value(volume),
            "PlaybackRate": 100.0
        }
        self.project["Timelines"][0]["Items"].append(item)

    def add_audio_item(self, file_path, start_frame, duration, layer=3, volume=100.0):
        item = {
            "$type": "YukkuriMovieMaker.Project.Items.AudioItem, YukkuriMovieMaker",
            "FilePath": os.path.abspath(file_path),
            "Frame": start_frame,
            "Length": duration,
            "Layer": layer,
            "Volume": self._anim_value(volume),
            "PlaybackRate": 100.0
        }
        self.project["Timelines"][0]["Items"].append(item)

    def add_image_item(self, file_path, start_frame, duration, layer=0):
        scale = 100.0
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                img_w, img_h = img.size
            if img_w != self.width or img_h != self.height:
                scale_w = self.width / img_w * 100.0
                scale_h = self.height / img_h * 100.0
                scale = max(scale_w, scale_h)
        except Exception:
            pass

        item = {
            "$type": "YukkuriMovieMaker.Project.Items.ImageItem, YukkuriMovieMaker",
            "FilePath": os.path.abspath(file_path),
            "Frame": start_frame,
            "Length": duration,
            "Layer": layer,
            "Opacity": 100.0,
            "Scale": float(scale),
            "X": 0.0,
            "Y": 0.0,
        }
        self.project["Timelines"][0]["Items"].append(item)

    def add_transition_item(self, cut_frame, duration, layer=1,
                            transition_type="DoubleOpenDoor", target="Before",
                            easing_type="Expo", easing_mode="InOut"):
        type_ns = "YukkuriMovieMaker.Transition"
        item_ns = "YukkuriMovieMaker.Project.Items"
        asm = "YukkuriMovieMaker"

        known = {
            "DoubleOpenDoor": "DoubleOpenDoorTransition",
            "CrossDissolve":  "CrossDissolveTransition",
            "Fade":           "FadeTransition",
            "Slide":          "SlideTransition",
            "Wipe":           "WipeTransition",
        }
        base = known.get(transition_type, f"{transition_type}Transition")

        item = {
            "$type": f"{item_ns}.TransitionItem, {asm}",
            "X": self._anim_value(0),
            "Y": self._anim_value(0),
            "Z": self._anim_value(0),
            "Opacity": self._anim_value(100),
            "Zoom": self._anim_value(100),
            "Rotation": self._anim_value(0),
            "FadeIn": 0.0,
            "FadeOut": 0.0,
            "IsInverted": False,
            "Blend": "Normal",
            "IsAlwaysOnTop": False,
            "IsZOrderEnabled": False,
            "IsClippingWithObjectAbove": False,
            "VideoEffects": [],
            "TransitionType": f"{type_ns}.{base}Plugin, {asm}",
            "TransitionParameter": {
                "$type": f"{type_ns}.{base}Parameter, {asm}",
                "Target": target,
                "Angle": self._anim_value(0),
                "EasingType": easing_type,
                "EasingMode": easing_mode,
            },
            "BeforeVideoEffects": [],
            "AfterVideoEffects": [],
            "Group": 0,
            "Frame": max(0, cut_frame - duration // 2),
            "Layer": layer,
            "KeyFrames": {"Frames": [], "Count": 0},
            "Length": duration,
            "PlaybackRate": 100.0,
            "ContentOffset": "00:00:00",
            "Remark": "",
            "IsLocked": False,
            "IsHidden": False,
        }
        self.project["Timelines"][0]["Items"].append(item)

    def add_tachie_item(self, character_name, start_frame, duration, layer=4, x=0, y=0):
        resolved_name = self._resolve_name(character_name)
        self._get_character_id(resolved_name)  # ensure registered

        # Look up plugin parameters from template
        tmpl = self.templates.get(resolved_name, {})
        tachie_item_param = tmpl.get("TachieDefaultItemParameter")
        face_param = tmpl.get("TachieDefaultFaceParameter")

        item = {
            "$type": "YukkuriMovieMaker.Project.Items.TachieItem, YukkuriMovieMaker",
            "CharacterName": resolved_name,
            "Frame": start_frame,
            "Length": duration,
            "Layer": layer,
            "X": self._anim_value(x),
            "Y": self._anim_value(y),
            "Z": self._anim_value(0),
            "Opacity": self._anim_value(100),
            "Zoom": self._anim_value(30),
            "Rotation": self._anim_value(0),
            "FadeIn": 0.0,
            "FadeOut": 0.0,
            "Blend": "Normal",
            "IsInverted": False,
            "IsClippingWithObjectAbove": False,
            "IsAlwaysOnTop": False,
            "IsZOrderEnabled": False,
            "VideoEffects": [],
            "Group": 0,
            "KeyFrames": {"Frames": [], "Count": 0},
            "PlaybackRate": 100.0,
            "ContentOffset": "00:00:00",
            "Remark": "",
            "IsLocked": False,
            "IsHidden": False
        }
        if tachie_item_param:
            item["TachieItemParameter"] = tachie_item_param
        item["FaceItemParameter"] = {}

        self.project["Timelines"][0]["Items"].append(item)

    def add_text_item(self, text, start_frame, duration, layer=2, font_size=60.0, y=350.0):
        item = {
            "$type": "YukkuriMovieMaker.Project.Items.TextItem, YukkuriMovieMaker",
            "Text": text,
            "Frame": start_frame,
            "Length": duration,
            "Layer": layer,
            "FontSize": float(font_size),
            "Font": "Meiryo",
            "FontColor": "#FFFFFFFF",
            "Style": 1, # Border
            "StyleColor": "#FF000000",
            "X": 0.0,
            "Y": float(y),
            "BasePoint": 4, # Center
            "Opacity": 100.0
        }
        self.project["Timelines"][0]["Items"].append(item)

    def merge_project(self, source_path, offset_frames=0):
        if not os.path.exists(source_path):
            return
        try:
            with open(source_path, "r", encoding="utf-8-sig") as f:
                src = json.load(f)
        except Exception as e:
            if self.debug:
                print(f"  [YMMP] merge_project failed to load {source_path}: {e}")
            return

        # Merge characters (skip duplicates by name)
        existing_names = {c["Name"] for c in self.project["Characters"]}
        for char in src.get("Characters", []):
            if char.get("Name") not in existing_names:
                self.project["Characters"].append(char)
                existing_names.add(char.get("Name"))

        # Merge items with frame offset
        for item in src.get("Timelines", [{}])[0].get("Items", []):
            if offset_frames and "Frame" in item:
                merged = dict(item)
                merged["Frame"] = item["Frame"] + offset_frames
                self.project["Timelines"][0]["Items"].append(merged)
            else:
                self.project["Timelines"][0]["Items"].append(item)

        if self.debug:
            print(f"  [YMMP] Merged {source_path} (offset={offset_frames})")

    def save(self, file_path):
        with open(file_path, "w", encoding="utf-8-sig") as f:
            json.dump(self.project, f, ensure_ascii=False, indent=2)
        if self.debug:
            print(f"  [YMMP] Saved project to {file_path}")
