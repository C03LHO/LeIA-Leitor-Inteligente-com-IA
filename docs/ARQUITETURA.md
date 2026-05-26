# Arquitetura do LeIA

## Visão geral

LeIA é um app desktop **single-host**: backend Python (FastAPI) + frontend HTML/JS estático, ambos servidos pelo mesmo processo na porta `127.0.0.1:8765`. O browser padrão do usuário atua como UI. Tudo roda local, sem rede externa após o setup.

```
+---------+   HTTP/WS   +---------------+
| Browser | <---------> | FastAPI       |
| (UI)    |             |  /api/pdf/*   |
+---------+             |  /api/tts/*   |
                        |  /ws/tts      |
                        |  /static/*    |
                        +-------+-------+
                                |
              +-----------------+-------------------+
              |                 |                   |
          PyMuPDF           Coqui XTTS-v2       Cache em
          (extração)        (GPU/CPU)           %AppData%\LeIA\
```

## Decisões de stack

### Por que PyMuPDF (fitz)?
- Único extrator que retorna **blocos com posição, fonte, tamanho e flags**, essencial para detectar headers/footers, notas de rodapé, colunas e títulos.
- `pdfminer.six` é mais lento e perde muita estrutura; `pdfplumber` é bom para tabelas mas pesado para texto puro.

### Por que XTTS-v2?
- Melhor voz pt-BR em modelo open-source com licença que permite uso pessoal.
- Suporta clonagem de voz a partir de 6–10s de áudio (`speaker_wav`), o que permite vozes customizadas no futuro.
- Streaming nativo (sentença a sentença) com primeira sentença em < 3s em GPU média.
- Alternativas avaliadas e descartadas: Piper (qualidade pt-BR inferior), Tortoise (lento demais), ElevenLabs (paga + nuvem).

### Por que FastAPI + HTML estático?
- Sem build step no frontend → instalador menor, contribuições mais simples.
- FastAPI já tem WebSocket nativo, ideal pro streaming de TTS.
- Bootstrap dá UI razoável sem CSS custom extenso.

### Por que NÃO PyInstaller?
- Bundle com PyTorch + CUDA + XTTS passa de 4 GB → impossível distribuir como `.exe` único.
- Solução: instalador Inno Setup leve (~30 MB) que carrega Python embeddable, e baixa o que falta no primeiro boot. Modelo + venv ficam em `%AppData%\LeIA\` e sobrevivem a desinstalações se o usuário quiser.

## Pipeline de extração

1. **`pdf/extractor.py`** — `extract_blocks()` retorna `RawBlock`s com bbox/fonte/flags por bloco.
2. **`pdf/cleaner.py`**:
   - `body_font_size()` → moda dos tamanhos como referência.
   - `detect_recurring_headers_footers()` → texto que aparece no topo/rodapé em ≥30% das páginas.
   - `classify_block()` → decide `heading | paragraph | drop` aplicando regexes (URL, DOI, ISBN, copyright, editora, números de página, marcadores de footnote, refs `[12]`) e heurísticas de fonte/rotação (watermarks).
3. **`pdf/reflow.py`**:
   - `_sort_blocks_reading_order()` → detecta 2 colunas pela coordenada X (lê esquerda → direita).
   - `_join_block_lines()` + `_merge_hyphen_break()` → reconstrói parágrafos, trata hifenização com `pyphen` (mantém compostos reais como "guarda-chuva", junta artefatos como "palav- ra").
   - `build_sections()` → agrupa parágrafos em seções por heading, mescla parágrafos contínuos entre blocos.

A saída é o JSON descrito em `4.1.G` do plano (sections → paragraphs).

## Pipeline de TTS

1. **`tts/engine.py`** — `TTSEngine` (singleton) com carregamento *lazy* do XTTS-v2. Detecção de hardware (CUDA vs CPU) feita no construtor.
2. **`tts/streamer.py`** — `split_sentences()` (NLTK punkt em pt, fallback regex) + cache LRU de 500 MB indexado por `sha1(text|voice|speed)`.
3. **`/ws/tts`** — recebe `{text, voice, speed}`, manda `{type: "plan", sentences: [...]}`, depois um `{type: "chunk", index, sentence, audio_b64}` por sentença, finalizando com `{type: "done"}`. Frontend já vai tocando.

## Frontend

JS modular sem build:
- `api-client.js` — wrappers fetch/XHR/WS.
- `pdf-upload.js` — dropzone + polling do job.
- `reader.js` — render do documento, split client-side em spans `.sentence`.
- `player.js` — orquestra WS, fila de áudios, highlight da frase ativa.
- `app.js` — bootstrap, badge de hardware, toasts.

Tema escuro fixo (paleta `#1a1a1a` / `#4a9eff` / `#e8e8e8`). Tipografia serifada no corpo do leitor pra leitura longa.

## Persistência

Tudo em `%AppData%\LeIA\`:
- `venv\` — Python real do app.
- `models\` — pesos do XTTS (alguns modelos preferem `~/.local/share/tts`, ajustar via env var se necessário).
- `cache\pdf\` — PDFs enviados + JSONs de resultado, indexados por `job_id`.
- `cache\audio\` — WAVs sintetizados, hash-based.
- `logs\leia.log` — log com rotação (5×2MB).

## Pontos de extensão futura
- Resumo por IA local (Ollama) opcional, atrás de um flag em `CleaningConfig`.
- Múltiplas vozes (clonagem custom).
- Suporte a EPUB/MOBI (adicionar um `epub/extractor.py` simétrico).
- Tray icon Windows pra encerrar o backend sem matar pelo Task Manager.
