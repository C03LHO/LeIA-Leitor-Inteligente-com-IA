from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from backend.config import USER_DATA_DIR
from backend.utils.logging import get_logger

logger = get_logger("tts.voices")

CUSTOM_VOICES_DIR = USER_DATA_DIR / "custom_voices"
CUSTOM_VOICES_DIR.mkdir(parents=True, exist_ok=True)
CUSTOM_VOICES_INDEX = CUSTOM_VOICES_DIR / "_index.json"

PREVIEW_SENTENCE = (
    "Olá, eu sou o LeIA. Vou ler seus PDFs com naturalidade, "
    "no ritmo que você preferir."
)

DEFAULT_VOICE_ID = "ana_florence"

VoiceKind = Literal["embedded", "custom"]


@dataclass
class Voice:
    id: str
    name: str
    speaker: str | None
    gender: str
    style: str
    description: str
    language: str = "pt"
    kind: VoiceKind = "embedded"
    wav_path: str | None = None
    created_at: float | None = None
    duration_s: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender,
            "style": self.style,
            "description": self.description,
            "language": self.language,
            "kind": self.kind,
            "custom": self.kind == "custom",
            "created_at": self.created_at,
            "duration_s": self.duration_s,
        }


EMBEDDED_VOICES: list[Voice] = [
    Voice(
        id="ana_florence",
        name="Ana",
        speaker="Ana Florence",
        gender="feminina",
        style="Calorosa, melódica",
        description="Boa para literatura e ficção",
    ),
    Voice(
        id="sofia_hellen",
        name="Sofia",
        speaker="Sofia Hellen",
        gender="feminina",
        style="Clara, didática",
        description="Ideal para textos acadêmicos",
    ),
    Voice(
        id="daisy_studious",
        name="Daisy",
        speaker="Daisy Studious",
        gender="feminina",
        style="Suave, contemplativa",
        description="Ótima para ensaios e poesia",
    ),
    Voice(
        id="camilla_holmstrom",
        name="Camila",
        speaker="Camilla Holmström",
        gender="feminina",
        style="Neutra, profissional",
        description="Tom de locutora de rádio",
    ),
    Voice(
        id="tammie_ema",
        name="Tâmara",
        speaker="Tammie Ema",
        gender="feminina",
        style="Jovem, dinâmica",
        description="Boa para conteúdo leve",
    ),
    Voice(
        id="andrew_chipper",
        name="André",
        speaker="Andrew Chipper",
        gender="masculina",
        style="Amigável, próxima",
        description="Tom de conversa informal",
    ),
    Voice(
        id="damien_black",
        name="Damião",
        speaker="Damien Black",
        gender="masculina",
        style="Grave, dramática",
        description="Ideal para ficção e suspense",
    ),
    Voice(
        id="royston_min",
        name="Rogério",
        speaker="Royston Min",
        gender="masculina",
        style="Madura, professoral",
        description="Ótima para não-ficção densa",
    ),
    Voice(
        id="eugenio_mataraci",
        name="Eugênio",
        speaker="Eugenio Mataracı",
        gender="masculina",
        style="Calorosa, narrativa",
        description="Estilo audiobook clássico",
    ),
    Voice(
        id="abrahan_mack",
        name="Abrão",
        speaker="Abrahan Mack",
        gender="masculina",
        style="Profunda, ritmada",
        description="Voz de podcast premium",
    ),
]


def _load_custom_index() -> dict:
    if not CUSTOM_VOICES_INDEX.exists():
        return {}
    try:
        return json.loads(CUSTOM_VOICES_INDEX.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Falha ao ler índice de vozes customizadas")
        return {}


def _save_custom_index(data: dict) -> None:
    CUSTOM_VOICES_INDEX.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def custom_voices() -> list[Voice]:
    out: list[Voice] = []
    for vid, meta in _load_custom_index().items():
        wav = Path(meta.get("wav_path", ""))
        if not wav.exists():
            continue
        out.append(
            Voice(
                id=vid,
                name=meta.get("name", "Personalizada"),
                speaker=None,
                gender=meta.get("gender", "—"),
                style=meta.get("style", "Personalizada"),
                description=meta.get("description", "Voz enviada pelo usuário"),
                kind="custom",
                wav_path=str(wav),
                created_at=meta.get("created_at"),
                duration_s=meta.get("duration_s"),
            )
        )
    return out


def all_voices() -> list[Voice]:
    return EMBEDDED_VOICES + custom_voices()


def resolve_voice(voice_id: str) -> Voice:
    for v in all_voices():
        if v.id == voice_id:
            return v
    raise KeyError(f"Voz desconhecida: {voice_id}")


def add_custom_voice(
    wav_bytes: bytes,
    name: str,
    duration_s: float,
    gender: str = "—",
) -> Voice:
    voice_id = "custom_" + uuid.uuid4().hex[:10]
    target = CUSTOM_VOICES_DIR / f"{voice_id}.wav"
    target.write_bytes(wav_bytes)
    index = _load_custom_index()
    index[voice_id] = {
        "name": name,
        "gender": gender,
        "style": "Personalizada",
        "description": "Voz enviada pelo usuário",
        "wav_path": str(target),
        "created_at": time.time(),
        "duration_s": duration_s,
    }
    _save_custom_index(index)
    logger.info("Voz custom adicionada: %s (%s)", voice_id, name)
    return resolve_voice(voice_id)


def remove_custom_voice(voice_id: str) -> bool:
    index = _load_custom_index()
    meta = index.pop(voice_id, None)
    if not meta:
        return False
    try:
        Path(meta["wav_path"]).unlink(missing_ok=True)
    except Exception:
        pass
    _save_custom_index(index)
    return True
