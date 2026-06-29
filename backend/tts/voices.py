from __future__ import annotations

from dataclasses import dataclass

from backend.utils.logging import get_logger

logger = get_logger("tts.voices")

PREVIEW_SENTENCE = (
    "Olá, eu sou o LeIA. Vou ler seus PDFs com naturalidade, "
    "no ritmo que você preferir."
)

DEFAULT_VOICE_ID = "natural"


@dataclass
class Voice:
    id: str
    name: str
    gender: str
    style: str
    description: str
    language: str = "pt"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender,
            "style": self.style,
            "description": self.description,
            "language": self.language,
            "custom": False,
        }


# O Chatterbox tem uma única voz nativa (sem catálogo). É a que o LeIA usa.
_NATURAL = Voice(
    id=DEFAULT_VOICE_ID,
    name="Padrão",
    gender="—",
    style="Natural",
    description="Voz natural do LeIA",
)

EMBEDDED_VOICES: list[Voice] = [_NATURAL]


def all_voices() -> list[Voice]:
    return list(EMBEDDED_VOICES)


def resolve_voice(voice_id: str) -> Voice:
    """Voz única: qualquer id (inclusive prefs antigas do XTTS) resolve para a padrão."""
    return _NATURAL
