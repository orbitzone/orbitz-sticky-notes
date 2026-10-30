# Auditoria de fechamento — Orbitz Sticky Notes

**Alvo inicial:** working tree baseado em `d6dee36`, com alterações locais de Sticky Code, layout, segurança e empacotamento. A auditoria não corresponde a uma release/tag. **Rechecagem:** deltas de purga de e-mail e locks compartilhados, 30/10/2026.

## Achados da auditoria e rechecagem

### P1 — Nota excluída mesmo se a purga do rascunho falhar — corrigido

**Reproduzido no alvo inicial.** `Card.delete_note()` confirmava `Store.delete()` antes de purgar o `.eml`; uma falha injetada na purga ainda levava ao fechamento da nota, deixando o rascunho com texto/anexos no cache.

**Rechecagem:** a ordem agora é purgar rascunhos → excluir registro. Se a purga falhar, o método retorna sem excluir nem fechar a nota; se o banco rejeitar a exclusão, a nota continua visível. O teste `test_email_draft_purge_failure_cancels_note_deletion` cobre o caso. `test_sticky_interactions.py` passou nos testes direcionados.

### P2 — Hard link em arquivo de lock alterava permissões de outro caminho — corrigido

**Reproduzido no alvo inicial.** Os arquivos `.app-instance.lock`, `.startup.lock` e `backups/.lock` recebiam `fchmod(0600)` sem validar se o inode era compartilhado. Fixtures temporárias demonstraram alteração do modo do outro caminho.

**Rechecagem:** os três caminhos usam `_open_private_lock()`, que exige arquivo regular, proprietário igual ao usuário atual e `st_nlink == 1` antes de alterar permissões. Os testes agora verificam hard links para os três locks e recusam proprietário divergente. Reexecução direta: suíte de startup, exclusão/backup e interação — **42 aprovados, 1 pulado** (smoke emoji depende de display GTK). O teste específico do lock de backup confirmou que o arquivo externo preserva conteúdo e modo `0640`.

## Risco de desempenho e fluidez ainda sem validação gráfica

`Card.document_changed()` serializa o documento e chama `flush()` dentro do sinal GTK `changed`; cada edição pode executar transação SQLite síncrona com `synchronous=FULL` no thread da interface (`sticky-notes/card.py:707-717, 785-807`). Em banco temporário local, 300 atualizações de texto curto tiveram mediana de 4,193 ms, p95 de 5,405 ms e máximo de 12,870 ms. Essa medição sintética não representa o disco do usuário nem prova que seja a causa da sensação de resize. Debounce reduziria gravações, porém abriria uma janela de perda após encerramento abrupto; não recomendo mudar a política sem teste representativo e decisão explícita sobre essa durabilidade.

A suíte GTK pula smokes de geometria e emoji sem display real. Permanecem sem validação visual a fluidez de resize com texto longo, comportamento em múltiplos monitores/escalas, menu em outros desktops e integração real com portais/clientes de e-mail.

## Revisão sem achado adicional

- Sticky Code persiste na mesma nota/ID, usa CAS na troca de modo e valida linguagem por allowlist. As migrações preservam conteúdo antigo.
- Anexos têm limites de quantidade/tamanho/extensão; composição de e-mail valida descritores por dispositivo/inode, não usa shell e cria rascunhos na cache privada. Arquivos originais permanecem na pasta de origem, como documentado.
- O PIN bloqueia a interface, mas não criptografa SQLite nem backups; esse limite está explícito.
- Exclusão/purga de snapshots usa operações atômicas e falha fechada quando a preparação de backup não pode ser validada.

## Evidência integrada

- Antes dos dois deltas corretivos: `make test` — **136 aprovados, 2 pulados**; desktop-file validation, AppStream, compileall, JSON/paridade de catálogos e `git diff --check` aprovados.
- Após os deltas: testes focados — **42 aprovados, 1 pulado**, incluindo casos de hard link dos três locks e falha de purga de rascunho. `git diff --check` aprovado.
- Suíte global final após as correções, executada pelo supervisor: `make test` — **142 aprovados, 2 pulados**.
- Não foi feito um build Flatpak final nem validação visual real após os deltas; permanecem as limitações gráficas descritas acima.

## Parecer

Os dois bloqueios reproduzidos foram corrigidos e os testes focados confirmam os critérios. **A prontidão para uma release estável ainda não está certificada**: a suíte integrada final passou; falta validar visualmente fluidez/redimensionamento e combinações reais de desktop/portal, além do build Flatpak final. Não afirmar compatibilidade universal com Linux.

## Rechecagem das pendências 2–5 — 30/10/2026

**Esta seção registra uma rodada intermediária e foi supersedida pela atualização de fechamento abaixo.**

O supervisor completou build e exportação local do bundle atual. Conferi independentemente tamanho (19.950.248 bytes), SHA-256 (`ae8add7881e13744727e793950f3a7b01b62866c82124108e98192e534b9fc38`) e metadata do build (app ID/comando esperados, GNOME 49 x86_64, socket X11). O smoke informado importou `storage`, `card` e `ui_language` no sandbox e confirmou uma tradução. Isso cobre build/importação, não interface visual.

A matriz permanece conservadora: CI Ubuntu 24.04/Xvfb valida testes/build; não há homologação visual. Host Ubuntu 22.04.5/GNOME 42.9/Wayland+XWayland não teve integração exercitada. O socket X11 torna XWayland uma expectativa de execução, mas nenhum smoke real a certifica. Wayland nativo, desktops e gerenciadores adicionais, ARM64 e comportamentos de janela continuam sem validação.

Os benchmarks são isolados e não medem latência de input/frame nem resize em storage real. As adições de nomes acessíveis foram cobertas por teste; não houve leitor de tela/AT-SPI ativo. Permanecem lacunas de teclado no controle de PIN e mover/redimensionar. O bloqueador de resize visual continua deliberadamente pendente para a próxima fase. **Não certificar release estável ainda.**

## Revisão intermediária do pacote — supersedida em 30/10/2026

O registro abaixo documenta a revisão anterior ao ajuste final do popup e da acessibilidade por teclado. Para o estado de fechamento, prevalece o adendo subsequente.

O usuário confirmou que validou o redimensionamento (ponto 1); a rodada final não repetiu essa avaliação. O pacote atual em `/tmp/orbitz-sticky-production/dist/orbitz-sticky-notes-x86_64.flatpak` confere com 19.624.032 bytes e SHA-256 `c605f55c920bbf9b14986dd8d2bf68de1f4d39065f876782e15cf3bead5fb396`. A metadata confere com app ID esperado, runtime GNOME 49, arquitetura x86_64 e socket X11. Esta conferência não instalou nem abriu o pacote.

O smoke GTK disponível cria e fecha janelas usando o código-fonte local. Não fixa/registra `GDK_BACKEND`, não envia entrada de teclado/mouse e não exercita a interface do bundle; portanto, não prova execução em XWayland nem interação do pacote. A implementação de PIN/mover/redimensionar usa controles focáveis e valida autorização PIN; os testes dessas operações usam mocks. Não foi identificado bloqueio lógico óbvio, mas o teclado físico não foi homologado.

O artefato MIME temporário contém `X-Unsent` e um anexo sintético. A abertura headless no Thunderbird com perfil temporário foi reportada, mas não há transcript independente preservado. O teste não demonstra anexos visíveis nem o fluxo GUI portal→Thunderbird. Orca/AT-SPI permanece sem smoke, pois a acessibilidade estava desativada; KDE/Xfce/Wayland-only/ARM e X11 puro também não foram testados. **Manter a classificação de prévia; não declarar produção estável ou compatibilidade universal.**

## Adendo final — correção de recorte do popup de emoji — 30/10/2026

A janela do seletor agora reserva 8 px adicionais em largura e altura após medir o tamanho preferido pelo GTK. O smoke GTK nativo atualizado confirma que a janela está mapeada, que os 48 botões cabem no grid, que o grid completo cabe dentro dos limites do popup e que selecionar um emoji o insere no cursor salvo. A conversão de coordenadas trata os dois formatos do binding GTK (`x,y` e `success,x,y`). O smoke passou em XWayland. O smoke de layout/reflow/rolagem também passou; a suíte completa executada nesse backend passou com **146 testes, sem skips**.

O bundle reconstruído em `/tmp/orbitz-sticky-production/dist/orbitz-sticky-notes-x86_64.flatpak` tem **19.624.256 bytes**, SHA-256 `8528a315cb5c352eaaf78e840db7a8241b2bab464247eec90c029aa37215f4c8`. A verificação de importação no sandbox passou. Separadamente, uma árvore da aplicação mapeou uma nota temporária usando GTK do host. Não houve execução da interface gráfica do bundle dentro do sandbox, pois o SDK GNOME 49 não estava disponível para esse smoke.

Em smoke complementar posterior, a árvore Python extraída em `build/files` iniciou com GTK 3.24 do host, D-Bus privado e caminhos XDG temporários; uma nota foi mapeada e fechada, e os nomes ATK de título, conteúdo e controle de mover estavam presentes. Isso confirma criação/mapeamento básico e exposição desses nomes acessíveis no toolkit do host. Não executou dentro do runtime Flatpak GNOME 49, não usou Orca e não verificou fala nem ordem de foco.

Esse fechamento valida o recorte e a seleção do popup, além do reflow no `Gtk.OffscreenWindow`; não valida resize interativo via compositor, mouse/teclado na janela completa do pacote nem comportamento visual em outros ambientes. Permanecem gates para uma release estável: executar o bundle em ambiente gráfico isolado com runtime GNOME 49 e exercitar sua interface; validar Orca/AT-SPI; validar visualmente portal e anexos no cliente de e-mail; e homologar os desktops/arquiteturas que forem anunciados como suportados. Não há evidência para declarar compatibilidade universal.
