#!/usr/bin/env python3
"""Gemmy AI Dancing Bear stage controller.

Serves the control UI, camera stream, MP3 library, TTS and Gemini endpoints,
and drives the Raspberry Pi 5 hardware through hardware.py.
"""

import base64
import http.server
import json
import math
import os
import random
import re
import socket
import socketserver
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request

import cv2
import numpy as np

import local_audio
from gemini_bridge import GeminiBearBridge
from hardware import hardware, PINS

PORT = int(os.environ.get("PORT", 1890))
HOST = os.environ.get("HOST", os.environ.get("IP", "127.0.0.1"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORY = os.environ.get("DIRECTORY", os.path.join(BASE_DIR, "static"))
AUDIO_DIR = os.path.join(BASE_DIR, "music")
HARDWARE_CONFIG_FILE = os.path.join(BASE_DIR, "hardware_config.json")
PROFILE_FILE = os.path.join(BASE_DIR, "profile.json")
os.makedirs(AUDIO_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Camera stream
# ---------------------------------------------------------------------------

def generate_synthetic_camera_frame():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :] = (12, 24, 18)
    cv2.putText(frame, "GEMMY AI BEAR STAGE CAMERA", (90, 200),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 240, 255), 2)
    cv2.putText(frame, "STATUS: Virtual Stage Feed Active", (140, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (160, 255, 160), 1)
    cv2.putText(frame, "LIVE TIME: " + time.strftime("%H:%M:%S"), (220, 280),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return frame


class CameraStream:
    def __init__(self, source="usb"):
        self.source = str(source).lower()
        self.cap = None
        self.picam2 = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        threading.Thread(target=self._update, daemon=True).start()

    def set_source(self, source):
        with self.lock:
            self.source = str(source).lower()
            self._close_cameras()
            self.frame = None

    def _close_cameras(self):
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        if self.picam2:
            try:
                self.picam2.stop()
                self.picam2.close()
            except Exception:
                pass
            self.picam2 = None

    def _update(self):
        while self.running:
            with self.lock:
                cur_source = self.source

            if cur_source in ("csi", "picamera", "raspberry_pi", "ov5647"):
                if self.picam2 is None:
                    self._close_cameras()
                    try:
                        from picamera2 import Picamera2
                        p = Picamera2()
                        p.configure(p.create_preview_configuration(main={"size": (640, 480)}))
                        p.start()
                        time.sleep(0.3)
                        self.picam2 = p
                    except Exception:
                        self.picam2 = None
                        time.sleep(1.0)
                        continue
                try:
                    array = self.picam2.capture_array("main")
                    if array is not None and array.size > 0:
                        frame = cv2.cvtColor(array, cv2.COLOR_RGBA2BGR) if array.shape[2] == 4 else array
                        with self.lock:
                            self.frame = frame
                    time.sleep(0.04)
                except Exception:
                    self._close_cameras()
                    time.sleep(0.5)
                continue

            if self.cap is None or not self.cap.isOpened():
                self._close_cameras()
                candidates = [0, 1, 6, 2, 8, 23]
                if cur_source.isdigit():
                    candidates.insert(0, int(cur_source))
                candidates = [idx for idx in dict.fromkeys(candidates)
                              if os.path.exists("/dev/video%d" % idx)]
                opened = False
                for idx in candidates:
                    try:
                        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        if cap.isOpened():
                            ok, frame = cap.read()
                            if ok and frame is not None and frame.size > 0:
                                self.cap = cap
                                with self.lock:
                                    self.frame = frame
                                opened = True
                                break
                        cap.release()
                    except Exception:
                        pass
                if not opened:
                    with self.lock:
                        self.frame = generate_synthetic_camera_frame()
                    time.sleep(2.0)

            if self.cap and self.cap.isOpened():
                try:
                    ok, frame = self.cap.read()
                    if ok and frame is not None and frame.size > 0:
                        with self.lock:
                            self.frame = frame
                        time.sleep(0.04)
                    else:
                        self._close_cameras()
                        time.sleep(1.0)
                except Exception:
                    self._close_cameras()
                    time.sleep(1.0)
            else:
                time.sleep(0.5)

    def get_frame(self):
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()
        return generate_synthetic_camera_frame()


camera_stream = CameraStream("usb")
gemini_bridge = GeminiBearBridge()


# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

hardware_config = {
    "camera_source": "usb",
    "mic_source": "browser",
    "mic_device": "",
    "mic_gain": 100,
    "mic_sensitivity": 100,
    "speaker_source": "browser",
    "speaker_volume": 100,
    "automation": True,
}


PERSONALITIES = {
    "playful": {
        "label": "Playful Showman",
        "prompt": "Playful, quick-witted showbiz bear. Loves puns, playful teasing and getting the audience to laugh.",
    },
    "pirate": {
        "label": "Pirate Bear",
        "prompt": "Swashbuckling pirate bear. Uses nautical jokes, a bold mischievous streak and the occasional 'arrr'.",
    },
    "wise": {
        "label": "Wise Old Bear",
        "prompt": "Calm, wise old bear. Thoughtful and warm, with gentle humour and short pieces of practical wisdom.",
    },
    "diva": {
        "label": "Showbiz Diva",
        "prompt": "Glamorous showbiz diva. Theatrical, dramatic, generous with compliments and always ready for the spotlight.",
    },
    "cyber": {
        "label": "Cyberpunk AI",
        "prompt": "Futuristic cyberpunk bear. Clever, fast-talking, neon-nightclub energy and playful tech references.",
    },
    "sweet": {
        "label": "Sweet Companion",
        "prompt": "Affectionate companion bear. Gentle, encouraging, comforting and always happy to see the people nearby.",
    },
    "custom": {
        "label": "Custom Personality",
        "prompt": "",
    },
}


profile_lock = threading.Lock()

bear_profile = {
    "name": "Bruno",
    "personality": "playful",
    "personality_custom": "",
    "mimic_mode": False,
    "voice": "ai_female_us",
    "camera_source": "usb",
    "mic_source": "browser",
    "mic_device": "",
    "mic_sensitivity": 100,
    "speaker_source": "browser",
    "speaker_volume": 100,
}


def load_profile():
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, "r") as handle:
                saved = json.load(handle)
            if isinstance(saved, dict):
                for key in bear_profile:
                    if key in saved:
                        bear_profile[key] = saved[key]
        except Exception:
            pass


def save_profile():
    try:
        with open(PROFILE_FILE, "w") as handle:
            json.dump(bear_profile, handle, indent=2)
    except Exception:
        pass


def current_profile():
    with profile_lock:
        data = dict(bear_profile)
    data["camera_source"] = hardware_config.get("camera_source", data.get("camera_source", "usb"))
    data["mic_source"] = hardware_config.get("mic_source", data.get("mic_source", "browser"))
    data["mic_device"] = hardware_config.get("mic_device", data.get("mic_device", ""))
    data["mic_sensitivity"] = hardware_config.get("mic_sensitivity", data.get("mic_sensitivity", 100))
    data["speaker_source"] = hardware_config.get("speaker_source", data.get("speaker_source", "browser"))
    data["speaker_volume"] = hardware_config.get("speaker_volume", data.get("speaker_volume", 100))
    with state_lock:
        data["voice"] = bear_state.get("voice", data.get("voice", "ai_female_us"))
    return data


def profile_for_gemini():
    data = current_profile()
    key = str(data.get("personality", "playful"))
    if key == "custom":
        prompt = str(data.get("personality_custom") or "").strip()
        if not prompt:
            prompt = PERSONALITIES["playful"]["prompt"]
    else:
        prompt = PERSONALITIES.get(key, PERSONALITIES["playful"])["prompt"]
    data["personality_prompt"] = prompt
    return data


def load_hardware_config():
    if os.path.exists(HARDWARE_CONFIG_FILE):
        try:
            with open(HARDWARE_CONFIG_FILE, "r") as handle:
                hardware_config.update(json.load(handle))
        except Exception:
            pass


def save_hardware_config():
    try:
        with open(HARDWARE_CONFIG_FILE, "w") as handle:
            json.dump(hardware_config, handle, indent=2)
    except Exception:
        pass


load_hardware_config()
load_profile()
camera_stream.set_source(hardware_config.get("camera_source", "usb"))


# ---------------------------------------------------------------------------
# Bear performance state
# ---------------------------------------------------------------------------

state_lock = threading.Lock()

bear_state = {
    "mode": "idle",                 # idle | talking | dancing
    "talking": False,
    "dancing": False,
    "automation": bool(hardware_config.get("automation", True)),
    "mouth_channel1": "off",        # off | open
    "body_channel2": "off",         # off | left | right
    "tushie": False,
    "spotlight": {
        "pan": 90,
        "tilt": 90,
        "intensity": 0,
        "mode": "idle",             # idle | breathe | flash | solid | manual
    },
    "stage": {
        "angle": 90,
        "mode": "idle",             # idle | talk | dance | manual
    },
    "beat_energy": 0,
    "last_beat": 0.0,
    "voice": bear_profile.get("voice", "ai_female_us"),
}

_next_idle_sweep = time.time() + random.uniform(10.0, 20.0)
_idle_target_angle = 90.0
_last_stage_angle = 90.0
_tushie_pulse_token = 0


def snapshot():
    with state_lock:
        data = json.loads(json.dumps(bear_state))
    data["hardware_available"] = hardware.available
    data["hardware_error"] = hardware.error
    data["pins"] = PINS
    return data


def set_mode(mode):
    mode = str(mode or "idle").lower()
    if mode not in ("idle", "talking", "dancing"):
        mode = "idle"
    if mode == "dancing":
        with state_lock:
            bear_state["automation"] = True
        hardware_config["automation"] = True
        save_hardware_config()
    with state_lock:
        bear_state["mode"] = mode
        bear_state["talking"] = mode == "talking"
        bear_state["dancing"] = mode == "dancing"
        if mode == "dancing":
            bear_state["body_channel2"] = "left"
        elif bear_state["automation"]:
            bear_state["body_channel2"] = "off"
            bear_state["tushie"] = False
            bear_state["mouth_channel1"] = "off"
    if mode == "dancing":
        hardware.set_body("left")
    elif bear_state.get("automation", True):
        hardware.set_body("off")
        hardware.set_tushie(False)
        hardware.set_mouth("off")
        with state_lock:
            bear_state["mouth_channel1"] = "off"


def set_mouth(mode):
    mode = str(mode or "off").lower()
    if mode not in ("off", "open"):
        mode = "off"
    with state_lock:
        bear_state["mouth_channel1"] = mode
    hardware.set_mouth(mode)


def set_body(direction):
    direction = str(direction or "off").lower()
    if direction not in ("off", "left", "right"):
        direction = "off"
    with state_lock:
        bear_state["body_channel2"] = direction
    hardware.set_body(direction)


def set_tushie(active):
    active = bool(active)
    with state_lock:
        bear_state["tushie"] = active
    hardware.set_tushie(active)


def pulse_tushie(duration=0.9):
    """Power the tushie motor briefly, then release it for the return spring."""
    global _tushie_pulse_token
    try:
        duration = max(0.05, min(5.0, float(duration)))
    except Exception:
        duration = 0.9
    with state_lock:
        _tushie_pulse_token += 1
        token = _tushie_pulse_token
        bear_state["tushie"] = True
    hardware.set_tushie(True)

    def worker():
        time.sleep(duration)
        with state_lock:
            if token != _tushie_pulse_token:
                return
            if bear_state["automation"] and bear_state["mode"] == "dancing":
                return
            bear_state["tushie"] = False
        hardware.set_tushie(False)

    threading.Thread(target=worker, daemon=True).start()


def animation_loop():
    """Drive body shimmy, tushie, spotlight and stage from the performance mode."""
    global _next_idle_sweep, _idle_target_angle, _last_stage_angle

    while True:
        now = time.time()
        with state_lock:
            mode = bear_state["mode"]
            automation = bear_state["automation"]
            beat = float(bear_state.get("beat_energy", 0))
            manual_spot = dict(bear_state["spotlight"])
            manual_stage = dict(bear_state["stage"])
            manual_body = str(bear_state.get("body_channel2", "off"))
            manual_tushie = bool(bear_state.get("tushie", False))
            mouth_open = bear_state["mouth_channel1"] == "open"

        if not automation:
            # Manual mode still animates the chosen LED effect (breathe/flash)
            # while body, tushie, pan, tilt and stage stay where the user left them.
            spot_mode = manual_spot.get("mode", "manual")
            if spot_mode == "breathe":
                intensity = 42.0 + 32.0 * math.sin(now * 1.3)
            elif spot_mode == "flash":
                intensity = 100.0 if math.sin(now * 4.0) > 0 else 0.0
            elif spot_mode == "solid":
                intensity = manual_spot.get("intensity", 100)
            elif spot_mode == "idle":
                intensity = 0.0
            else:
                intensity = manual_spot.get("intensity", 0)
            hardware.set_body(manual_body)
            hardware.set_tushie(manual_tushie)
            hardware.set_spotlight(intensity)
            with state_lock:
                bear_state["spotlight"]["intensity"] = round(intensity, 1)
            time.sleep(0.05)
            continue

        if mode == "dancing":
            energy = max(0.0, min(100.0, beat))
            speed = 1.6 + (energy / 100.0) * 6.0
            stage_angle = 90.0 + 42.0 * math.sin(now * (0.55 + energy / 130.0))
            pan = 90.0 + 28.0 * math.sin(now * (1.5 + energy / 45.0))
            tilt = 90.0 + 18.0 * math.cos(now * (1.2 + energy / 70.0))
            intensity = 100.0 if math.sin(now * (4.0 + energy / 22.0)) > 0 else 0.0
            spotlight_mode = "flash"
            stage_mode = "dance"
            body = "left" if math.sin(now * speed) >= 0 else "right"
            tushie = math.sin(now * (3.0 + energy / 24.0)) > 0.15
        elif mode == "talking":
            stage_angle = 90.0 + 18.0 * math.sin(now * 0.55)
            pan, tilt = 90.0, 90.0
            intensity = 42.0 + 32.0 * math.sin(now * 1.3)
            spotlight_mode = "breathe"
            stage_mode = "talk"
            body = manual_body
            tushie = manual_tushie
        else:
            if now >= _next_idle_sweep:
                _idle_target_angle = random.choice([55, 65, 80, 100, 115, 125])
                _next_idle_sweep = now + random.uniform(14.0, 28.0)
            stage_angle = _last_stage_angle + (_idle_target_angle - _last_stage_angle) * 0.012
            pan, tilt = 90.0, 90.0
            intensity = 4.0
            spotlight_mode = "idle"
            stage_mode = "idle"
            body = manual_body
            tushie = manual_tushie

        _last_stage_angle = stage_angle

        hardware.set_body(body)
        hardware.set_tushie(tushie)
        hardware.set_spotlight_angles(pan, tilt)
        hardware.set_spotlight(intensity)
        hardware.set_stage(stage_angle)

        with state_lock:
            bear_state["spotlight"] = {
                "pan": round(pan, 1),
                "tilt": round(tilt, 1),
                "intensity": round(intensity, 1),
                "mode": spotlight_mode,
            }
            bear_state["stage"] = {
                "angle": round(stage_angle, 1),
                "mode": stage_mode,
            }
            bear_state["body_channel2"] = body
            bear_state["tushie"] = bool(tushie)

        time.sleep(0.05)


threading.Thread(target=animation_loop, daemon=True).start()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class BearRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_HEAD(self):
        route = urllib.parse.urlparse(self.path).path
        if route.startswith("/api/"):
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
        elif route.startswith("/music/") or route.startswith("/audio/"):
            self.send_response(200)
            self.send_header("Content-type", "audio/mpeg")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
        else:
            super().do_HEAD()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path

        if route.startswith("/api/export-pdf"):
            self.send_bytes(self.generate_schematic_pdf(), "application/pdf",
                            "Animatronic_Bear_Wiring_Schematic.pdf")
        elif route.startswith("/api/status"):
            self.send_json({
                "status": "online",
                "device": "Raspberry Pi 5 Gemmy AI Dancing Bear Stage",
                "python_version": sys.version,
                "hardware_available": hardware.available,
                "hardware_error": hardware.error,
            })
        elif route in ("/api/bear/state", "/api/motor/state", "/api/state"):
            self.send_json(snapshot())
        elif route in ("/api/bear/presets", "/api/presets"):
            self.send_json(PERFORMANCE_PRESETS)
        elif route.startswith("/api/camera/frame"):
            self.serve_camera_frame()
        elif route in ("/api/hardware/config", "/api/hardware/select"):
            self.send_json(hardware_config)
        elif route == "/api/profile":
            self.send_json({
                "profile": current_profile(),
                "personalities": PERSONALITIES,
            })
        elif route in ("/api/audio/list", "/api/music/list"):
            self.send_json({"files": self.list_audio_files()})
        elif route in ("/api/audio/outputs", "/api/audio/sinks"):
            self.send_json({"outputs": local_audio.list_local_audio_outputs()})
        elif route.startswith("/api/tts/speak"):
            self.handle_tts(parsed)
        elif route.startswith("/music/") or route.startswith("/audio/"):
            self.serve_audio(route)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {}

        if route in ("/api/audio/play", "/api/audio/play_local"):
            audio_bytes, content_type = local_audio.load_audio_bytes_from_url(data.get("url", ""))
            if not audio_bytes:
                self.send_json({"error": "Unable to load audio for local playback"}, status=500)
            else:
                volume = data.get("volume", hardware_config.get("speaker_volume", 100))
                local_audio.play_audio_on_local_output(
                    audio_bytes, content_type, data.get("speaker", "default"), volume
                )
                self.send_json({"success": True, "speaker": data.get("speaker", "default")})

        elif route in ("/api/bear/mode", "/api/bear/talk", "/api/bear/dance"):
            if route == "/api/bear/talk":
                mode = "talking" if data.get("enabled", data.get("active", True)) else "idle"
            elif route == "/api/bear/dance":
                mode = "dancing" if data.get("enabled", data.get("active", True)) else "idle"
            else:
                mode = data.get("mode", "idle")
            set_mode(mode)
            self.send_json({"success": True, "state": snapshot()})

        elif route in ("/api/bear/control", "/api/motor/control"):
            if "automation" in data:
                with state_lock:
                    bear_state["automation"] = bool(data["automation"])
                hardware_config["automation"] = bool(data["automation"])
                save_hardware_config()
            if "mouth" in data or "mouth_channel1" in data:
                value = data.get("mouth", data.get("mouth_channel1"))
                if isinstance(value, bool):
                    value = "open" if value else "off"
                set_mouth(value)
            if "body" in data or "body_channel2" in data:
                set_body(data.get("body", data.get("body_channel2")))
            if "tushie_pulse" in data:
                pulse_tushie(data.get("tushie_pulse", 0.9))
            elif "tushie" in data:
                set_tushie(data.get("tushie"))
            if "voice" in data:
                with state_lock:
                    bear_state["voice"] = str(data["voice"])
            self.send_json({"success": True, "state": snapshot()})

        elif route == "/api/bear/spotlight":
            with state_lock:
                spot = bear_state["spotlight"]
                if "pan" in data:
                    spot["pan"] = max(45, min(135, float(data["pan"])))
                if "tilt" in data:
                    spot["tilt"] = max(45, min(135, float(data["tilt"])))
                if "intensity" in data:
                    spot["intensity"] = max(0, min(100, float(data["intensity"])))
                if "mode" in data:
                    spot["mode"] = str(data["mode"])
                if data.get("manual"):
                    bear_state["automation"] = False
                pan, tilt = spot["pan"], spot["tilt"]
                intensity = spot["intensity"]
            hardware.set_spotlight_angles(pan, tilt)
            hardware.set_spotlight(intensity)
            self.send_json({"success": True, "state": snapshot()})

        elif route == "/api/bear/stage":
            with state_lock:
                stage = bear_state["stage"]
                if "angle" in data:
                    stage["angle"] = max(30, min(150, float(data["angle"])))
                if "mode" in data:
                    stage["mode"] = str(data["mode"])
                if data.get("manual"):
                    bear_state["automation"] = False
                angle = stage["angle"]
            hardware.set_stage(angle)
            self.send_json({"success": True, "state": snapshot()})

        elif route == "/api/bear/beat":
            try:
                energy = max(0.0, min(100.0, float(data.get("energy", 0))))
            except Exception:
                energy = 0.0
            with state_lock:
                bear_state["beat_energy"] = energy
                bear_state["last_beat"] = time.time()
            self.send_json({"success": True, "energy": energy})

        elif route == "/api/profile":
            profile = data.get("profile", data)
            with profile_lock:
                if "name" in profile:
                    name = str(profile["name"]).strip()[:60]
                    bear_profile["name"] = name or "Bruno"
                if "personality" in profile:
                    key = str(profile["personality"])
                    bear_profile["personality"] = key if key in PERSONALITIES else "playful"
                if "personality_custom" in profile:
                    bear_profile["personality_custom"] = str(profile["personality_custom"])[:1200]
                if "mimic_mode" in profile:
                    bear_profile["mimic_mode"] = bool(profile["mimic_mode"])
                if "voice" in profile:
                    voice = str(profile["voice"])
                    bear_profile["voice"] = voice if voice in (
                        "ai_female_us", "ai_male_us", "ai_male_uk", "ai_female_uk"
                    ) else "ai_female_us"
                    with state_lock:
                        bear_state["voice"] = bear_profile["voice"]

                for key in ("camera_source", "mic_source", "mic_device", "speaker_source"):
                    if key in profile:
                        value = str(profile[key])
                        bear_profile[key] = value
                        hardware_config[key] = value
                for key in ("mic_sensitivity", "speaker_volume"):
                    if key in profile:
                        try:
                            value = max(0, min(200, int(profile[key])))
                        except Exception:
                            continue
                        bear_profile[key] = value
                        hardware_config[key] = value

            if "camera_source" in profile:
                camera_stream.set_source(hardware_config["camera_source"])
            save_profile()
            save_hardware_config()
            self.send_json({"success": True, "profile": current_profile()})

        elif route in ("/api/hardware/config", "/api/hardware/select"):
            for key in ("camera_source", "mic_source", "mic_device", "speaker_source"):
                if key in data:
                    hardware_config[key] = str(data[key])
            for key in ("mic_gain", "mic_sensitivity", "speaker_volume"):
                if key in data:
                    try:
                        hardware_config[key] = int(data[key])
                    except Exception:
                        pass
            if "automation" in data:
                hardware_config["automation"] = bool(data["automation"])
                with state_lock:
                    bear_state["automation"] = bool(data["automation"])
            if "camera_source" in data:
                camera_stream.set_source(hardware_config["camera_source"])
            save_hardware_config()
            self.send_json({"success": True, "config": hardware_config})

        elif route == "/api/camera/select":
            source = str(data.get("source", "usb"))
            hardware_config["camera_source"] = source
            camera_stream.set_source(source)
            save_hardware_config()
            self.send_json({"success": True, "active_source": source})

        elif route == "/api/gemini/chat":
            api_key = data.get("api_key") or os.environ.get("GEMINI_API_KEY", "")
            image_bytes = self.capture_camera_bytes() if data.get("include_vision", True) else None
            result = gemini_bridge.generate_chat_response(
                api_key, data.get("prompt", ""), image_bytes, profile_for_gemini()
            )
            self.apply_ai_action(result.get("action"))
            self.send_json(result)

        elif route == "/api/gemini/voice":
            api_key = data.get("api_key") or os.environ.get("GEMINI_API_KEY", "")
            audio_b64 = data.get("audio_b64", "")
            audio_bytes = base64.b64decode(audio_b64) if audio_b64 else None
            image_bytes = self.capture_camera_bytes() if data.get("include_vision", True) else None
            result = gemini_bridge.generate_voice_chat_response(
                api_key, audio_bytes, data.get("mime_type", "audio/webm"), image_bytes,
                profile_for_gemini(),
            )
            self.apply_ai_action(result.get("action"))
            self.send_json(result)

        elif route in ("/api/audio/stop", "/api/music/stop"):
            local_audio.stop_local_audio()
            self.send_json({"success": True})

        elif route in ("/api/audio/upload", "/api/music/upload"):
            self.handle_upload(data)

        elif route in ("/api/audio/download_url", "/api/music/download_url"):
            self.handle_url_download(data)

        elif route in ("/api/audio/delete", "/api/music/delete"):
            filename = os.path.basename(data.get("filename", ""))
            path = os.path.join(AUDIO_DIR, filename)
            if filename and os.path.isfile(path):
                try:
                    os.remove(path)
                    self.send_json({"success": True})
                except Exception as exc:
                    self.send_json({"error": str(exc)}, status=500)
            else:
                self.send_json({"error": "File not found"}, status=404)

        elif route == "/api/export-python":
            script = self.generate_hardware_script()
            self.send_bytes(script.encode("utf-8"), "application/x-python",
                            "bear_stage_control.py")

        else:
            self.send_json({"error": "Endpoint not found"}, status=404)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def list_audio_files(self):
        files = []
        for name in sorted(os.listdir(AUDIO_DIR)):
            if name.lower().endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac")):
                path = os.path.join(AUDIO_DIR, name)
                files.append({
                    "name": name,
                    "size": os.path.getsize(path),
                    "mtime": os.path.getmtime(path),
                })
        return files

    def serve_audio(self, route):
        prefix = "/music/" if route.startswith("/music/") else "/audio/"
        filename = os.path.basename(urllib.parse.unquote(route[len(prefix):]))
        path = os.path.join(AUDIO_DIR, filename)
        if not os.path.isfile(path):
            self.send_json({"error": "File not found"}, status=404)
            return
        try:
            with open(path, "rb") as handle:
                content = handle.read()
            content_type = {
                ".mp3": "audio/mpeg",
                ".wav": "audio/wav",
                ".ogg": "audio/ogg",
                ".m4a": "audio/mp4",
                ".flac": "audio/flac",
            }.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(content)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_tts(self, parsed):
        try:
            from gtts import gTTS
            import io

            query = urllib.parse.parse_qs(parsed.query)
            text = re.sub(r"\*[^*]*\*", "", query.get("text", ["Hello!"])[0]).strip() or "Hello!"
            with state_lock:
                default_voice = bear_state.get("voice", "ai_female_us")
            voice = query.get("voice", [default_voice])[0]
            tld_map = {
                "ai_female_us": ("en", "com"),
                "ai_male_us": ("en", "us"),
                "ai_male_uk": ("en", "co.uk"),
                "ai_female_uk": ("en", "co.uk"),
            }
            lang, tld = tld_map.get(voice, ("en", "com"))
            tts = gTTS(text=text, lang=lang, tld=tld)
            buffer = io.BytesIO()
            tts.write_to_fp(buffer)
            self.send_bytes(buffer.getvalue(), "audio/mpeg")
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_upload(self, data):
        filename = data.get("filename", "")
        file_b64 = data.get("data", "") or data.get("file_b64", "")
        if not filename or not file_b64:
            self.send_json({"error": "Missing filename or data"}, status=400)
            return
        safe_name = os.path.basename(filename)
        if not safe_name.lower().endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac")):
            safe_name += ".mp3"
        try:
            if "," in file_b64:
                file_b64 = file_b64.split(",", 1)[1]
            raw = base64.b64decode(file_b64)
            with open(os.path.join(AUDIO_DIR, safe_name), "wb") as handle:
                handle.write(raw)
            self.send_json({"success": True, "filename": safe_name, "size": len(raw)})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_url_download(self, data):
        url = (data.get("url") or "").strip()
        filename = (data.get("filename") or "").strip()
        if not url:
            self.send_json({"error": "Missing MP3 URL"}, status=400)
            return
        try:
            if not filename:
                filename = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path))
            if not filename or not filename.lower().endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac")):
                filename = (filename or "downloaded_track") + ".mp3"
            safe_name = os.path.basename(filename)
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            with open(os.path.join(AUDIO_DIR, safe_name), "wb") as handle:
                handle.write(raw)
            self.send_json({"success": True, "filename": safe_name, "size": len(raw)})
        except Exception as exc:
            self.send_json({"error": "Download failed: %s" % exc}, status=500)

    def apply_ai_action(self, action):
        if not action or not action.get("name"):
            return
        name = action["name"]
        args = action.get("args") or {}
        if name == "bear_dance":
            enabled = args.get("enabled", True)
            if enabled:
                with state_lock:
                    bear_state["automation"] = True
                hardware_config["automation"] = True
                save_hardware_config()
            set_mode("dancing" if enabled else "idle")
        elif name == "bear_shimmy":
            direction = str(args.get("direction", "off")).lower()
            if direction not in ("left", "right"):
                direction = "off"
            with state_lock:
                bear_state["automation"] = False
            hardware_config["automation"] = False
            save_hardware_config()
            set_body(direction)
        elif name == "bear_tushie":
            with state_lock:
                bear_state["automation"] = False
            hardware_config["automation"] = False
            save_hardware_config()
            if args.get("pop", True):
                pulse_tushie(args.get("duration", 0.9))
            else:
                set_tushie(False)
        elif name == "bear_talk":
            set_mode("talking" if args.get("enabled", True) else "idle")
        elif name == "bear_sing":
            set_mode("talking")
        elif name == "bear_spotlight":
            with state_lock:
                spot = bear_state["spotlight"]
                if "pan" in args:
                    spot["pan"] = max(45, min(135, float(args["pan"])))
                if "tilt" in args:
                    spot["tilt"] = max(45, min(135, float(args["tilt"])))
                if "intensity" in args:
                    spot["intensity"] = max(0, min(100, float(args["intensity"])))
                bear_state["automation"] = False
                pan, tilt, intensity = spot["pan"], spot["tilt"], spot["intensity"]
            hardware.set_spotlight_angles(pan, tilt)
            hardware.set_spotlight(intensity)
        elif name == "bear_stage":
            angle = max(30, min(150, float(args.get("angle", 90))))
            with state_lock:
                bear_state["stage"]["angle"] = angle
                bear_state["automation"] = False
            hardware.set_stage(angle)

    def capture_camera_frame(self):
        return camera_stream.get_frame()

    def capture_camera_bytes(self):
        frame = self.capture_camera_frame()
        ok, jpeg = cv2.imencode(".jpg", frame)
        return jpeg.tobytes() if ok else None

    def serve_camera_frame(self):
        jpeg = self.capture_camera_bytes()
        if jpeg is None:
            self.send_response(503)
            self.end_headers()
            return
        try:
            self.send_response(200)
            self.send_header("Content-type", "image/jpeg")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(jpeg)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def send_json(self, data, status=200):
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def send_bytes(self, payload, content_type, filename=None):
        try:
            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if filename:
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % filename)
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------

    def generate_hardware_script(self):
        return '''#!/usr/bin/env python3
"""Standalone Gemmy AI Dancing Bear stage controller.

L298N #1 channel 1 : mouth (forward)
L298N #1 channel 2 : body shimmy (forward = left, reverse = right)
L298N #2 channel 1 : tushie motor (forward = push out, off = spring return)
IRLZ44N MOSFET     : spotlight LED PWM
Servos             : spotlight pan/tilt + stage turntable
"""

import time
from gpiozero import AngularServo, DigitalOutputDevice, PWMOutputDevice

L298_ENA, L298_IN1, L298_IN2 = 18, 23, 24
L298_ENB, L298_IN3, L298_IN4 = 19, 25, 8
TUSHIE_ENA, TUSHIE_IN1, TUSHIE_IN2 = 17, 27, 22
SPOTLIGHT_LED, SPOTLIGHT_PAN, SPOTLIGHT_TILT = 12, 13, 16
STAGE_SERVO = 9

in1 = DigitalOutputDevice(L298_IN1, initial_value=False)
in2 = DigitalOutputDevice(L298_IN2, initial_value=False)
in3 = DigitalOutputDevice(L298_IN3, initial_value=False)
in4 = DigitalOutputDevice(L298_IN4, initial_value=False)
tushie_in1 = DigitalOutputDevice(TUSHIE_IN1, initial_value=False)
tushie_in2 = DigitalOutputDevice(TUSHIE_IN2, initial_value=False)
ena = PWMOutputDevice(L298_ENA, frequency=1000, initial_value=0)
enb = PWMOutputDevice(L298_ENB, frequency=1000, initial_value=0)
tushie_ena = PWMOutputDevice(TUSHIE_ENA, frequency=1000, initial_value=0)
led = PWMOutputDevice(SPOTLIGHT_LED, frequency=1000, initial_value=0)

servo_kwargs = dict(min_angle=0, max_angle=180,
                    min_pulse_width=0.0005, max_pulse_width=0.0025)
pan = AngularServo(SPOTLIGHT_PAN, initial_angle=90, **servo_kwargs)
tilt = AngularServo(SPOTLIGHT_TILT, initial_angle=90, **servo_kwargs)
stage = AngularServo(STAGE_SERVO, initial_angle=90, **servo_kwargs)


def set_mouth(mode):
    if mode == "open":
        in1.on(); in2.off(); ena.value = 1.0
    else:
        in1.off(); in2.off(); ena.value = 0


def set_body(direction):
    if direction == "left":
        in3.on(); in4.off(); enb.value = 0.9
    elif direction == "right":
        in3.off(); in4.on(); enb.value = 0.9
    else:
        in3.off(); in4.off(); enb.value = 0


def set_tushie(active):
    if active:
        tushie_in1.on(); tushie_in2.off(); tushie_ena.value = 0.9
    else:
        tushie_in1.off(); tushie_in2.off(); tushie_ena.value = 0


def set_spotlight(percent):
    led.value = max(0.0, min(100.0, percent)) / 100.0


def set_spotlight_angles(pan_deg, tilt_deg):
    pan.angle = max(45, min(135, pan_deg))
    tilt.angle = max(45, min(135, tilt_deg))


def set_stage(angle):
    stage.angle = max(30, min(150, angle))


def demo():
    set_spotlight_angles(90, 90)
    set_spotlight(60)
    for _ in range(3):
        set_mouth("open"); time.sleep(0.25); set_mouth("off"); time.sleep(0.2)
    set_body("left"); time.sleep(0.7)
    set_body("right"); time.sleep(0.7)
    set_body("off")
    set_tushie(True); time.sleep(0.9); set_tushie(False)
    set_stage(60); time.sleep(0.8); set_stage(120); time.sleep(0.8); set_stage(90)


if __name__ == "__main__":
    try:
        demo()
    finally:
        set_mouth("off")
        set_body("off")
        set_tushie(False)
        set_spotlight(0)
'''

    def generate_schematic_pdf(self):
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                                leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        title = ParagraphStyle("TitleX", parent=styles["Heading1"], fontName="Helvetica-Bold",
                               fontSize=18, textColor=colors.HexColor("#065f46"), spaceAfter=4)
        sub = ParagraphStyle("SubX", parent=styles["Normal"], fontName="Helvetica-Oblique",
                             fontSize=9, textColor=colors.HexColor("#444444"), spaceAfter=10)
        head = ParagraphStyle("HeadX", parent=styles["Heading2"], fontName="Helvetica-Bold",
                              fontSize=11, textColor=colors.HexColor("#0f766e"), spaceBefore=8, spaceAfter=4)
        cell = ParagraphStyle("CellX", parent=styles["Normal"], fontName="Helvetica",
                              fontSize=8, leading=10)
        hcell = ParagraphStyle("HCellX", parent=styles["Normal"], fontName="Helvetica-Bold",
                               fontSize=8, leading=10, textColor=colors.white)

        story = [
            Paragraph("GEMMY AI BEAR STAGE - WIRING SCHEMATIC", title),
            Paragraph("Raspberry Pi 5, L298N dual H-bridge, IRLZ44N spotlight MOSFET and stage servos", sub),
            HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0f766e"),
                       spaceBefore=2, spaceAfter=8),
            Paragraph("Component overview", head),
        ]

        overview = [
            [Paragraph("Component", hcell), Paragraph("Role", hcell), Paragraph("Power", hcell)],
            [Paragraph("Raspberry Pi 5", cell), Paragraph("Web server, camera, AI and stage controller", cell), Paragraph("5V 5A USB-C", cell)],
            [Paragraph("L298N #1 channel 1", cell), Paragraph("Mouth motor forward pulse (ENA 18, IN1 23, IN2 24)", cell), Paragraph("12V motor rail", cell)],
            [Paragraph("L298N #1 channel 2", cell), Paragraph("Body shimmy motor, forward = left, reverse = right (ENB 19, IN3 25, IN4 8)", cell), Paragraph("12V motor rail", cell)],
            [Paragraph("L298N #2 channel 1", cell), Paragraph("Tushie motor, forward = push out, off = spring return (ENA 17, IN1 27, IN2 22)", cell), Paragraph("12V motor rail", cell)],
            [Paragraph("IRLZ44N MOSFET", cell), Paragraph("Spotlight LED PWM brightness on GPIO 12", cell), Paragraph("12V LED rail", cell)],
            [Paragraph("Spotlight servos", cell), Paragraph("2-DOF pan/tilt on GPIO 13 and GPIO 16", cell), Paragraph("5-6V servo rail", cell)],
            [Paragraph("Stage servo", cell), Paragraph("Turntable rotation on GPIO 9", cell), Paragraph("5-6V servo rail", cell)],
            [Paragraph("USB / CSI camera", cell), Paragraph("Vision and webcam microphone input", cell), Paragraph("5V USB", cell)],
        ]
        t = Table(overview, colWidths=[150, 400, 150])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#065f46")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecfdf5")]),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

        story.append(Paragraph("L298N truth table", head))
        logic = [
            [Paragraph("Action", hcell), Paragraph("ENA / ENB", hcell), Paragraph("IN1 / IN3", hcell), Paragraph("IN2 / IN4", hcell)],
            [Paragraph("Mouth open (forward pulse)", cell), Paragraph("PWM 0-100%", cell), Paragraph("HIGH", cell), Paragraph("LOW", cell)],
            [Paragraph("Mouth stop", cell), Paragraph("0", cell), Paragraph("LOW", cell), Paragraph("LOW", cell)],
            [Paragraph("Body shimmy left (forward)", cell), Paragraph("PWM 90%", cell), Paragraph("HIGH", cell), Paragraph("LOW", cell)],
            [Paragraph("Body shimmy right (reverse)", cell), Paragraph("PWM 90%", cell), Paragraph("LOW", cell), Paragraph("HIGH", cell)],
            [Paragraph("Tushie push out (L298 #2 forward)", cell), Paragraph("PWM 90%", cell), Paragraph("HIGH", cell), Paragraph("LOW", cell)],
            [Paragraph("Tushie release / spring return", cell), Paragraph("0", cell), Paragraph("LOW", cell), Paragraph("LOW", cell)],
        ]
        t2 = Table(logic, colWidths=[220, 140, 170, 170])
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecfdf5")]),
        ]))
        story.append(t2)

        doc.build(story)
        return buffer.getvalue()


PERFORMANCE_PRESETS = {
    "Talk to the Room": {"description": "Mouth pulses with speech, spotlight breathes and stage sweeps slowly.", "mode": "talking"},
    "Dance Party": {"description": "Body shimmies left and right while the tushie pops to the beat.", "mode": "dancing"},
    "Idle Show": {"description": "Calm idle show with occasional slow stage sweeps.", "mode": "idle"},
    "Mouth Test": {"description": "Pulses mouth channel 1 forward for a quick mechanism check.", "mode": "idle"},
}


class ThreadingReusableTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    ssl_context = None

    def get_request(self):
        newsocket, fromaddr = self.socket.accept()
        if self.ssl_context:
            try:
                first_byte = newsocket.recv(1, socket.MSG_PEEK)
                if first_byte and first_byte[0] == 0x16:
                    newsocket = self.ssl_context.wrap_socket(newsocket, server_side=True)
            except Exception:
                pass
        return newsocket, fromaddr


if __name__ == "__main__":
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            PORT = int(args[i + 1])
        elif arg == "--host" and i + 1 < len(args):
            HOST = args[i + 1]

    cert_path = os.path.join(BASE_DIR, "cert.pem")
    key_path = os.path.join(BASE_DIR, "key.pem")
    ssl_ctx = None
    if os.path.exists(cert_path) and os.path.exists(key_path):
        try:
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        except Exception as exc:
            print("SSL certificate warning:", exc)

    display_host = "localhost" if HOST in ("", "0.0.0.0", "127.0.0.1") else HOST
    bind_host = "" if HOST == "0.0.0.0" else HOST
    print("Gemmy AI Dancing Bear stage starting on http://%s:%s" % (display_host, PORT))
    print("Hardware:", "online" if hardware.available else "simulation (%s)" % hardware.error)
    with ThreadingReusableTCPServer((bind_host, PORT), BearRequestHandler) as httpd:
        httpd.ssl_context = ssl_ctx
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
