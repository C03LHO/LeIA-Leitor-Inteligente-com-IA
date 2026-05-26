from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.config import ROOT_DIR

VOICES_DIR = ROOT_DIR / "voices"


@dataclass
class Voice:
    id: str
    label: str
    language: str
    sample_path: Path

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "language": self.language,
            "sample_exists": self.sample_path.exists(),
        }


def builtin_voices() -> list[Voice]:
    return [
        Voice(
            id="default",
            label="LeIA (pt-BR feminina)",
            language="pt",
            sample_path=VOICES_DIR / "speaker_default.wav",
        ),
    ]


def get_voice(voice_id: str) -> Voice:
    for v in builtin_voices():
        if v.id == voice_id:
            return v
    raise KeyError(f"Voz desconhecida: {voice_id}")
