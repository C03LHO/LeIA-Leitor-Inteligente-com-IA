# Como testar o LeIA

## Dev local (sem instalador)

Pré-requisito: **Python 3.11 64-bit**. PyTorch 2.1.2 + CUDA 12.1 só tem wheel até 3.11; 3.12+ não funciona.

```powershell
git clone <repo>
cd LeIA-Leitor-Inteligente-com-IA

python -m venv venv
venv\Scripts\activate

# Em máquina COM GPU NVIDIA:
pip install -r requirements-dev.txt

# Em máquina SEM GPU NVIDIA (pula CUDA):
pip install fastapi==0.110.3 uvicorn[standard]==0.27.1 python-multipart==0.0.9 ^
    websockets==12.0 PyMuPDF==1.24.1 pyphen==0.15.0 nltk==3.8.1 ^
    pydub==0.25.1 numpy==1.26.4 ^
    pytest==8.1.1 httpx==0.27.0 reportlab==4.1.0
# (coqui-tts e torch são opcionais para testar a parte de PDF / UI)

python -m backend.main
```

Abrir http://127.0.0.1:8765/ no navegador.

## Rodar a suíte de testes

```powershell
pytest
```

O `conftest.py` gera automaticamente 4 PDFs sintéticos em `tests/fixtures/` se não existirem (precisa do `reportlab`).

## Smoke test manual

1. `GET /` → deve servir a UI (ou JSON se o frontend não estiver presente).
2. `GET /api/system/status` → JSON com `hardware.cuda_available`.
3. Subir UI → arrastar um PDF → ver texto limpo no painel direito + estatísticas no painel esquerdo.
4. Clicar **▶** → primeiro chunk de áudio toca em < 5s (GPU) ou < 30s (CPU).
5. Mudar velocidade → próxima frase sintetizada usa o novo `speed`.
6. Clicar **⏭** → pula pra próxima frase.

## Teste do instalador

Em máquina **limpa** (Windows 10/11 64-bit, sem Python instalado):

1. Copiar `dist\LeIA_Setup_v1.0.0.exe`.
2. Clicar 2× → SmartScreen pode bloquear → "Mais informações → Executar mesmo assim".
3. Wizard padrão Inno Setup → Próximo → Instalar.
4. Janela tkinter "Configurando o LeIA pela primeira vez" → aguardar 5–15 min.
5. Browser abre automático em http://127.0.0.1:8765/.
6. Usar normalmente.

## Logs

Tudo em `%AppData%\LeIA\logs\leia.log` (rotação 5×2MB).

```powershell
Get-Content "$env:APPDATA\LeIA\logs\leia.log" -Tail 50 -Wait
```

## PDFs problemáticos

- **PDF protegido por senha**: `extract_blocks` detecta `doc.needs_pass` e levanta `ValueError`; `extract-sync` devolve 400 amigável e o job assíncrono guarda a mensagem em `error`.
- **PDF escaneado (imagem)**: blocos vêm vazios; a UI mostra a mensagem "Nenhum texto extraído… pode estar protegido ou ser uma imagem escaneada".
- **PDF corrompido**: `fitz.open()` falha e é convertido em `ValueError` ("pode estar corrompido"); mesmo tratamento amigável do protegido.
