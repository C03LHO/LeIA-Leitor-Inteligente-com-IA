# Checklist QA pré-release

## Instalação

- [ ] `LeIA_Setup_v1.0.0.exe` < 50 MB.
- [ ] Wizard Inno Setup abre em pt-BR.
- [ ] EULA exibida e aceitável.
- [ ] Instalação roda sem privilégio de admin (PrivilegesRequired=lowest).
- [ ] Atalho no Desktop criado (opcional).
- [ ] Atalho no Menu Iniciar criado.
- [ ] Entrada em "Adicionar/Remover Programas" presente com ícone correto.
- [ ] Tamanho instalado em `%LocalAppData%\Programs\LeIA\` ≈ 30 MB (antes do first run).

## First run

- [ ] Janela tkinter abre com tema escuro.
- [ ] Barra de progresso e log em tempo real visíveis.
- [ ] Detecta GPU NVIDIA corretamente (nvidia-smi).
- [ ] Em máquina sem GPU, cai pra PyTorch CPU sem erro.
- [ ] Download do XTTS-v2 mostra progresso.
- [ ] `.setup_complete` é escrito ao fim.
- [ ] Se interrompido no meio, reabrir o launcher reinicia o setup do ponto que faltava.

## Boot subsequente

- [ ] Launcher abre o backend em < 5s.
- [ ] Backend escuta em 127.0.0.1:8765 (ou próxima porta livre se ocupada).
- [ ] Browser padrão abre automaticamente na URL.

## UI / fluxo principal

- [ ] Drag-and-drop de PDF funciona.
- [ ] Botão "Selecionar arquivo" abre file picker.
- [ ] Barra de progresso evolui durante upload + extração.
- [ ] Toast "✓ Texto extraído e limpo" aparece ao fim.
- [ ] Sumário (TOC) clicável rola até a seção.
- [ ] Estatísticas de limpeza mostram páginas, chars mantidos, chars removidos com % e breakdown.
- [ ] Badge no canto superior direito mostra GPU verde ou CPU amarelo.

## Player

- [ ] Botão ▶ inicia narração.
- [ ] Primeiro áudio toca em < 5s (GPU) / < 30s (CPU).
- [ ] Frase atual fica destacada em amarelo.
- [ ] Scroll automático centraliza a frase ativa.
- [ ] ⏸ pausa; ▶ retoma.
- [ ] ⏭ pula pra próxima frase.
- [ ] ⏮ volta uma frase.
- [ ] Mudar velocidade (0.75x → 2.0x) afeta a próxima síntese.
- [ ] Fechar o documento (✕) volta pra tela de upload.

## Limpeza de PDF

- [ ] URLs (http/https/www) não aparecem no texto.
- [ ] DOI removido.
- [ ] ISBN removido.
- [ ] "© ... Todos os direitos reservados" removido.
- [ ] Linhas isoladas de editora removidas.
- [ ] Números de página removidos.
- [ ] Headers e footers recorrentes removidos.
- [ ] Notas de rodapé com fonte menor removidas.
- [ ] Marcadores `[12]`, `[7]` isolados removidos.
- [ ] Watermarks (texto rotacionado) removidos.

## Robustez

- [ ] PDF de 200+ páginas processa sem OOM.
- [ ] PDF protegido por senha exibe erro amigável (não trava).
- [ ] PDF de imagem escaneada (sem texto) exibe aviso claro.
- [ ] Porta 8765 ocupada → tenta próxima até 8775.
- [ ] WS interrompido pelo cliente não trava o backend.
- [ ] Cache de áudio reduzido para 500 MB quando ultrapassa.
- [ ] Logs rotacionam a cada 2 MB.

## Desinstalação

- [ ] Inno Setup remove `Program Files\LeIA` (ou `LocalAppData\Programs\LeIA`).
- [ ] Pergunta sobre remoção de `%AppData%\LeIA` (modelos+cache).
- [ ] Se "Sim", pasta é removida; se "Não", preservada.
- [ ] Atalhos removidos do Desktop e Menu Iniciar.

## Acessibilidade básica

- [ ] Contraste de texto ≥ 4.5:1 (tema escuro).
- [ ] Foco visível em controles do player.
- [ ] Atalhos de teclado: espaço para play/pause (TODO v1.1).

## Versão e versão de modelos

- [ ] `GET /api/system/status` retorna versão do app.
- [ ] Modelo XTTS-v2 identificável pela presença em `%AppData%\LeIA\models\` ou `~/.local/share/tts/`.
