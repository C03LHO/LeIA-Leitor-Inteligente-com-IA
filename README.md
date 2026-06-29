# LeIA — Leitor Inteligente com IA

Aplicativo desktop para Windows que abre PDFs, extrai apenas o conteúdo relevante (descartando metadados, URLs, rodapés, números de página etc.), exibe o texto limpo e narra em **pt-BR** com voz natural usando **XTTS-v2** rodando localmente na GPU (com fallback para CPU).

100% local, gratuito, sem chaves de API, sem nuvem.

---

## Desenvolvimento

Requisitos: **Python 3.11** (64-bit) no Windows 10/11. GPU NVIDIA é recomendada mas não obrigatória durante o desenvolvimento da UI / extração.

```powershell
git clone https://github.com/<voce>/LeIA-Leitor-Inteligente-com-IA.git
cd LeIA-Leitor-Inteligente-com-IA

python -m venv venv
venv\Scripts\activate

pip install -r requirements-dev.txt

python -m backend.main
```

Abra `http://127.0.0.1:8765/` no navegador — a raiz serve a interface. O JSON de
status fica em `http://127.0.0.1:8765/api`:

```json
{"status": "ok", "name": "LeIA", "version": "0.1.0"}
```

## Testes

```powershell
pytest
```

## Estrutura

```
backend/        FastAPI, extração PDF, motor TTS
frontend/       HTML + Bootstrap + JS vanilla (sem build step)
installer/      Inno Setup, launcher, first_run
tests/          pytest + fixtures de PDF
docs/           arquitetura, QA, como testar
```

## Status

Em desenvolvimento — ver `docs/` e o plano de implementação por fases.
