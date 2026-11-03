import json
import sys
import wave

import pytest

from central.motion_episodes import EPISODE_DIALOGUE
from central.motion_speech import SpeechError, resolve_voices, synthesize_episode


@pytest.mark.skipif(sys.platform != "win32", reason="Windows SAPI is only available on Windows")
def test_local_pt_br_speech_creates_sixty_second_audio_and_timed_captions(tmp_path):
    pytest.importorskip("win32com.client")
    audio, captions = synthesize_episode(tmp_path, "speech-test", EPISODE_DIALOGUE, 42)

    with wave.open(str(audio), "rb") as stream:
        assert stream.getframerate() == 22050
        assert stream.getnchannels() == 1
        assert stream.getnframes() == 22050 * 60
    data = json.loads(captions.read_text(encoding="utf-8"))
    assert data["language"] == "pt-BR"
    assert len(data["segments"]) == len(EPISODE_DIALOGUE)
    assert data["segments"][-1]["text"] == "Lara... abre. Eu sou você."
    assert data["segments"][0]["voice_profile"] == data["segments"][2]["voice_profile"] == "lara"
    assert data["segments"][1]["voice_profile"] == data["segments"][3]["voice_profile"] == "telefone"
    assert data["segments"][-1]["voice_profile"] == "porta"


def test_voice_assignments_are_stable_and_reject_unknown_profiles():
    dialogue = [
        {"speaker": "Lara", "text": "Uma fala."},
        {"speaker": "Lara", "text": "Outra fala."},
        {"speaker": "Voz desconhecida", "text": "Resposta."},
    ]
    assert resolve_voices(dialogue) == {"Lara": "lara", "Voz desconhecida": "telefone"}
    assert resolve_voices(dialogue, {"Lara": "porta"})["Lara"] == "porta"
    with pytest.raises(SpeechError):
        resolve_voices(dialogue, {"Lara": "inexistente"})
