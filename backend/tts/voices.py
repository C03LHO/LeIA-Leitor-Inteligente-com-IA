from __future__ import annotations

import json
from dataclasses import dataclass

from backend.config import USER_DATA_DIR
from backend.utils.logging import get_logger

logger = get_logger("tts.voices")

PREVIEW_SENTENCE = (
    "Olá! Esta é a minha voz. Vou narrar os seus livros com calma e clareza, "
    "no ritmo que você preferir."
)


@dataclass
class Voice:
    id: str          # nome do falante embutido do XTTS-v2
    name: str        # rótulo curto exibido
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


# Catálogo curado de vozes do XTTS-v2 (falantes embutidos) para narração em
# português. O `id` é o nome do falante que o XTTS usa internamente.
# O Damião é a voz PRINCIPAL (padrão); a Ana é a segunda recomendada. As demais
# são opções secundárias.
XTTS_VOICES: list[Voice] = [
    Voice("Damien Black", "Damião", "Masculina", "Envolvente", "Voz principal. Masculina marcante e limpa, ótima para qualquer livro."),
    Voice("Ana Florence", "Ana", "Feminina", "Clara e calma", "Recomendada. Feminina brasileira, ótima para leitura longa."),
    Voice("Sofia Hellen", "Sofia", "Feminina", "Suave", "Feminina suave, tom acolhedor."),
    Voice("Alma María", "Alma", "Feminina", "Expressiva", "Feminina expressiva, boa para ficção."),
    Voice("Daisy Studious", "Daisy", "Feminina", "Séria", "Feminina séria, boa para não-ficção."),
    Voice("Luis Moray", "Luís", "Masculina", "Firme", "Masculina firme e articulada."),
    Voice("Dionisio Schuyler", "Dionísio", "Masculina", "Grave", "Masculina grave, tom de contador de histórias."),
]

# Ids das vozes recomendadas (destacadas na interface) — Damião primeiro.
RECOMMENDED_VOICE_IDS = ["Damien Black", "Ana Florence"]

EMBEDDED_VOICES = XTTS_VOICES
_VOICE_BY_ID = {v.id: v for v in XTTS_VOICES}

DEFAULT_VOICE_ID = "Damien Black"

# Voz ativa persistida (sobrevive a reinício). Guardada em settings.json.
_SETTINGS_PATH = USER_DATA_DIR / "settings.json"


def all_voices() -> list[Voice]:
    return list(XTTS_VOICES)


def resolve_voice(voice_id: str) -> Voice:
    """Devolve a voz pelo id; ids desconhecidos (ex.: 'natural' antigo) caem na padrão."""
    return _VOICE_BY_ID.get(voice_id, _VOICE_BY_ID[DEFAULT_VOICE_ID])


def get_active_voice_id() -> str:
    try:
        data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        vid = data.get("voice")
        if vid in _VOICE_BY_ID:
            return vid
    except Exception:
        pass
    return DEFAULT_VOICE_ID


def set_active_voice_id(voice_id: str) -> str:
    vid = resolve_voice(voice_id).id
    try:
        data = {}
        if _SETTINGS_PATH.exists():
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        data["voice"] = vid
        _SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.exception("Falha ao salvar a voz ativa")
    return vid
