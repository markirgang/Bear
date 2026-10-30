"""Gemini multimodal bridge for the Gemmy AI Dancing Bear.

Exposes text and voice conversation plus function calling so the model can
drive the bear's stage, body shimmy, tushie, mouth and spotlight.
"""

from google import genai
from google.genai import types


MODEL_NAME = "gemini-3.8-flash"


class GeminiBearBridge:
    def __init__(self):
        self.system_instruction = (
            "You are Bruno, the charismatic AI brain of a large Gemmy animatronic dancing bear "
            "performing on a rotating stage. You can open your mouth, shimmy your body left or "
            "right, pop your spring-loaded tushie, move a two-axis spotlight and rotate your stage.\n"
            "Your job is to:\n"
            "1. Hold warm, witty, concise conversations with the people in the room.\n"
            "2. Describe what you see when the user shares a camera frame.\n"
            "3. Use the provided functions when asked to sing, dance, shimmy, pop your tushie, "
            "move the spotlight or turn the stage.\n"
            "Keep spoken replies to one or two sentences so the performance stays lively."
        )

    def _system_instruction(self, profile=None):
        profile = profile or {}
        name = str(profile.get("name") or "Bruno").strip() or "Bruno"
        personality = str(profile.get("personality_prompt") or "").strip()
        mimic = bool(profile.get("mimic_mode"))

        instruction = (
            "You are %s, the charismatic AI brain of a large Gemmy animatronic dancing bear "
            "performing on a rotating stage. You can open your mouth, shimmy your body left or "
            "right, pop your spring-loaded tushie, move a two-axis spotlight and rotate your stage.\n"
            "Your job is to:\n"
            "1. Hold warm, witty, concise conversations with the people in the room.\n"
            "2. Describe what you see when the user shares a camera frame.\n"
            "3. Use the provided functions when asked to sing, dance, shimmy, pop your tushie, "
            "move the spotlight or turn the stage.\n"
            "Keep spoken replies to one or two sentences so the performance stays lively."
        ) % name

        if personality:
            instruction += "\n\nYour personality: " + personality
        if mimic:
            instruction += (
                "\nYou love mimicking sounds and short phrases. When it fits naturally, repeat a "
                "short phrase or sound the user makes in a funny bear voice, then respond."
            )
        return instruction

    def _tools(self):
        number = types.Schema(type=types.Type.NUMBER)
        string = types.Schema(type=types.Type.STRING)

        return [
            types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name="bear_sing",
                    description="Start a singing performance with the named song when available.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"song_name": string},
                    ),
                ),
                types.FunctionDeclaration(
                    name="bear_dance",
                    description="Start or stop dancing to music, shimmying the body and flashing the spotlight.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"enabled": types.Schema(type=types.Type.BOOLEAN)},
                        required=["enabled"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="bear_shimmy",
                    description="Shimmy the bear body left, right or stop. Use this for a quick dance move.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"direction": string},
                        required=["direction"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="bear_tushie",
                    description="Pop the spring-loaded tushie out for a short pulse, or release it.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "pop": types.Schema(type=types.Type.BOOLEAN),
                            "duration": number,
                        },
                    ),
                ),
                types.FunctionDeclaration(
                    name="bear_talk",
                    description="Mark the bear as talking so the spotlight breathes and the stage sweeps slowly.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"enabled": types.Schema(type=types.Type.BOOLEAN)},
                        required=["enabled"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="bear_spotlight",
                    description="Aim the two-axis spotlight and set its brightness (manual mode).",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "pan": number,
                            "tilt": number,
                            "intensity": number,
                        },
                    ),
                ),
                types.FunctionDeclaration(
                    name="bear_stage",
                    description="Rotate the stage turntable to an angle between 30 and 150 degrees.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"angle": number},
                        required=["angle"],
                    ),
                ),
            ])
        ]

    def _run(self, api_key, contents, config):
        if not api_key:
            return {
                "text": "Add a Google Gemini API key in Settings to enable AI conversation.",
                "action": None,
            }
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config,
            )

            action = None
            text_response = response.text or ""
            if response.function_calls:
                call = response.function_calls[0]
                try:
                    args = dict(call.args)
                except Exception:
                    args = call.args
                action = {"name": call.name, "args": args}
                if not text_response:
                    text_response = "Right away!"
            return {"text": text_response, "action": action}
        except Exception as exc:
            return {"text": "Gemini API error: %s" % exc, "action": None}

    def generate_chat_response(self, api_key, user_text="", image_bytes=None, profile=None):
        contents = []
        if image_bytes:
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
        contents.append(user_text or "Describe what you see in front of you!")

        config = types.GenerateContentConfig(
            system_instruction=self._system_instruction(profile),
            tools=self._tools(),
            temperature=0.7,
        )
        return self._run(api_key, contents, config)

    def generate_voice_chat_response(
        self, api_key, audio_bytes=None, mime_type="audio/webm", image_bytes=None, profile=None
    ):
        contents = []
        if image_bytes:
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
        if audio_bytes:
            contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=mime_type))
            contents.append(
                "Listen to the voice recording, answer the request concisely and run any "
                "requested performance functions."
            )
        else:
            contents.append("What do you see?")

        config = types.GenerateContentConfig(
            system_instruction=self._system_instruction(profile),
            tools=self._tools(),
            temperature=0.7,
        )
        return self._run(api_key, contents, config)
