# LeIA — Leitor Inteligente com IA

Aplicativo desktop para Windows que abre **PDFs e EPUBs**, extrai apenas o conteúdo relevante (descartando metadados, URLs, rodapés, números de página, cabeçalhos recorrentes etc.), exibe o texto limpo num leitor confortável e **narra em pt-BR com voz natural** usando o motor **Chatterbox (Resemble AI)** rodando localmente na GPU NVIDIA (com fallback para CPU).

100% local, gratuito, sem chaves de API, sem nuvem para ler seus arquivos.
*(A busca de livros grátis é o único recurso que usa a internet — e é opcional.)*

---

## Recursos

- **Leitor + narração sincronizada** — a frase sendo lida fica destacada; controles de play/pause, frase/seção, velocidade e volume.
- **Estante estilo Kindle** — arraste um livro → ele vai para a estante com capa, autor e progresso. Clique na capa para abrir e **retoma de onde você parou**.
- **PDF e EPUB** — qualquer arquivo de livro. Extração limpa e reconstrução de parágrafos.
- **Preparo de áudio sob demanda + fila na GPU** — escolha se quer já preparar a narração ao adicionar. A geração roda numa **fila serial** (um livro por vez na GPU, estilo Steam), com badge de progresso na barra superior.
- **Buscar livros grátis online** — Project Gutenberg, Wikisource (pt) e Internet Archive, só em português. Quando a obra existe em mais de uma fonte, você escolhe de onde baixar. Resultados do Internet Archive vêm com aviso de domínio público.
- **Personalização de leitura** — fonte (serifada / sem serifa / **OpenDyslexic**), espessura, espaçamento, margens, tema claro/escuro, luz quente e brilho.
- **Estatísticas** — tempo de leitura, sequência (streak), meta diária e gráfico dos últimos 7 dias.
- **Coleções, busca (título/autor/trecho) e marcadores.**

---

## Requisitos

- **Windows 10/11** (64-bit)
- **Python 3.11** (64-bit)
- **GPU NVIDIA com CUDA** recomendada para narração fluida (ex.: RTX 4060 Ti). Sem GPU, a narração roda em CPU, porém bem mais lenta.

## Desenvolvimento

```powershell
git clone https://github.com/<voce>/LeIA-Leitor-Inteligente-com-IA.git
cd LeIA-Leitor-Inteligente-com-IA

py -3.11 -m venv venv
venv\Scripts\activate

# Stack completa (torch CUDA + Chatterbox). Use requirements-dev.txt para
# desenvolvimento só de UI/extração (sem baixar a stack de TTS).
pip install -r requirements.txt

python -m backend.main
```

O app escolhe automaticamente a primeira porta livre em `8765–8775` e serve a
interface na raiz. Abra `http://127.0.0.1:8765/` (ou a porta indicada no log).
Status em `/api`:

Para abrir como **aplicativo de desktop** (janela nativa via WebView2, sem
navegador) — é assim que o instalador inicia o LeIA:

```powershell
python -m backend.main --window
```

```json
{"status": "ok", "name": "LeIA", "version": "0.1.0"}
```

## Testes

```powershell
pytest
```

## Estrutura

```
backend/
  api/        rotas FastAPI (pdf, books, tts, voices, system)
  pdf/        extração + limpeza + reflow de PDF
  epub/       extração de EPUB
  sources/    fontes de livros grátis (Gutenberg, Wikisource, Internet Archive)
  tts/        motor Chatterbox, cache e streaming de áudio
frontend/     HTML + CSS + JS vanilla (sem build step)
installer/    Inno Setup, launcher, first_run
tests/        pytest + fixtures de PDF
docs/         arquitetura, QA, como testar
```

## Fontes de livros e uso legal

A busca online retorna apenas obras de **domínio público / livres**. O **Internet
Archive** pode conter obras cujo status de domínio público varia por país — por
isso todo resultado dessa fonte carrega um aviso. Confirme se você pode baixar/ouvir
a obra na sua região.

## Status

Em uso pessoal e evolução contínua — ver `docs/` para arquitetura e QA.
