# Build do instalador LeIA

## Pré-requisitos

1. **Inno Setup 6.x** instalado — https://jrsoftware.org/isdl.php
2. **PowerShell** (já vem no Windows 10/11).
3. **Conexão de internet** — o script baixa o Python embeddable e o `get-pip.py` em tempo de build.
4. **Ícone**: coloque um `icon.ico` (256×256 recomendado) em `installer\icon.ico`. Há um placeholder; substitua pelo seu.

## Como buildar

A partir da raiz do repositório:

```powershell
cd installer
.\build_installer.bat
```

Saída: `dist\LeIA_Setup_v1.0.0.exe` (~30 MB).

## O que o instalador faz

1. **Copia para `%LocalAppData%\Programs\LeIA\`:**
   - Python embeddable 3.11.9 (`python\`)
   - Código do backend e frontend
   - `launcher.bat`, `first_run.py`, `requirements.txt`, `EULA.txt`, `icon.ico`
2. **Cria atalhos** no Desktop (opcional) e Menu Iniciar.
3. **Na primeira execução do atalho**, o `launcher.bat` detecta que `%AppData%\LeIA\.setup_complete` não existe e roda `first_run.py`, que:
   - cria um venv em `%AppData%\LeIA\venv\`
   - instala PyTorch (CUDA 12.1 se houver GPU NVIDIA, CPU caso contrário) e demais dependências
   - pré-baixa o modelo XTTS-v2 (~1.8 GB) e o tokenizer NLTK punkt
   - escreve o flag `.setup_complete`
4. **Em execuções subsequentes**, o launcher só sobe o backend (`pythonw -m backend.main --open`) e abre `http://127.0.0.1:8765/` no browser padrão.

## Sobre Python embeddable + pip

O Python embeddable da python.org não vem com pip. O script automatiza:

1. Extrai `python-3.11.9-embed-amd64.zip` em `_build\python\`.
2. Edita `python311._pth` descomentando a linha `import site` (libera carregar `site-packages`).
3. Baixa `get-pip.py` e executa, instalando pip no embeddable.

O embeddable só serve para criar o venv real em `%AppData%\LeIA\venv\` no primeiro boot. O backend roda dentro desse venv.

## SmartScreen

O instalador não-assinado dispara o SmartScreen do Windows ("Aplicativo não reconhecido"). Clique em **Mais informações → Executar mesmo assim**. Assinatura digital fica fora do MVP.
