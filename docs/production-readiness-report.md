# Revisão de prontidão para produção — Orbitz Sticky Notes

**Alvo:** árvore de trabalho baseada em `d6dee36` (`Improve sticky note workflows and dock actions`), incluindo as alterações locais de Sticky Code, redimensionamento, privacidade, anexos e empacotamento observadas em 30/10/2026. A árvore já continha alterações não commitadas antes desta revisão; elas foram preservadas.

**Objetivo:** consolidar achados por área, evidências, limites e melhorias prioritárias. Testes automatizados não substituem validação visual em desktops reais.

## Estado executivo

O produto tem cobertura funcional ampla para notas, persistência, PIN visual, anexos e Sticky Code, além de pipeline Flatpak/CI. A rodada mais recente confirmou 146 testes aprovados; dois smokes que dependem de display GTK foram pulados. Validadores de arquivos desktop e AppStream, sintaxe Python, catálogos de tradução e `git diff --check` também passaram.

**O produto continua em prévia, sem certificação de produção.** A distribuição atual é x86_64, runtime GNOME 49, GTK 3 sobre X11/XWayland. A matriz documenta CI e um smoke básico de janelas em GNOME XWayland; KDE/Xfce, ARM, Wayland nativo, fluxos de portal e escala multimonitor seguem sem homologação. O PIN oculta dados na interface, mas não criptografa SQLite, backups, títulos, texto ou metadados de anexos.

## Principais pontos a melhorar

| Prioridade | Área | Evidência / preocupação | Próxima ação recomendada |
| --- | --- | --- | --- |
| P1 | Fluidez ao redimensionar | O usuário confirmou que validou visualmente o item 1. Nesta rodada, o smoke GTK do viewport com texto longo também passou; ele não simula arraste pelo compositor. | Considerar validado no ambiente do usuário; repetir em outros compositores/escalas somente se a matriz for ampliada. |
| P1 | Privacidade | PIN é barreira visual. SQLite e backups permanecem em texto claro; o aviso já aparece na interface/README. | Manter a limitação destacada. Criptografia seria um projeto separado, com migração, recuperação e política de backup definidas. |
| P1 | Compatibilidade Linux | Bundle atual é x86_64 com runtime GNOME 49 e socket X11. Smokes GTK e a suíte foram executados em XWayland; a árvore construída mapeou uma nota usando GTK do host, mas o SDK GNOME 49 necessário para executar o app no sandbox não está instalado. | Manter a matriz conservadora e homologar KDE/XWayland, Xfce, Wayland nativo e ARM separadamente antes de ampliar a divulgação. |
| P1 | Integridade dos dados | A auditoria independente reproduziu falha de purga de rascunho e hardlinks nos três locks; ambos foram corrigidos e cobertos por regressões focadas. O backend também revisou CAS, migração, PIN e transições do Sticky Code. | Manter exclusão bloqueada se o cache não puder ser limpo; continuar validando os três locks e purga de backups em alterações futuras. |
| P2 | Custo de edição | `document_changed()` serializa o texto rico e grava uma transação SQLite síncrona por alteração no thread GTK. O auditor mediu 300 updates curtos em banco temporário: mediana 4,193 ms, p95 5,405 ms, máximo 12,870 ms; isso não representa o disco do usuário nem mede resize. | Medir em armazenamento lento e snippets longos. Debounce/coalescência pode reduzir commits, mas introduz uma janela de perda em encerramento abrupto; qualquer mudança deve explicitar esse trade-off e manter flush nos limites normais. |
| P2 | Primeira prévia de anexo | A primeira miniatura é decodificada sincronicamente no caminho do tooltip; o cache evita trabalho repetido e limites de tamanho já existem. | Medir latência com imagens/PDF grandes e, se perceptível, mover a decodificação para tarefa assíncrona cancelável sem bloquear GTK. |
| P2 | Anexos e cliente de e-mail | Acesso/abertura dependem de portais e provedores externos; os arquivos originais ficam na pasta de origem. | Validar seletor, drag/drop, prévia e rascunho com anexos em desktops/clientes suportados; explicar limites sem prometer compatibilidade universal. |
| P2 | Acessibilidade e estados | Operação de PIN/mover/redimensionar por teclado tem regressões automatizadas e smoke de criação de janela XWayland; Orca/AT-SPI real não foi exercitado porque a acessibilidade está desativada na sessão. | Homologar fala/ordem de foco com Orca em sessão isolada antes de declarar suporte a leitor de tela. |
| P2 | Release e cadeia de suprimentos | Build/smoke do Flatpak foram repetidos após a correção do botão GTK; artefato temporário/hash atual constam abaixo. O builder 1.2.2 avisa que não reconhece `license-files`. | Manter sources/checksums/licenças fixos, validar o mesmo build no CI e publicar checksum/notas somente ao preparar release. |

## Relatórios por papel

- **Backend:** corrigiu a validação de propriedade/link nos locks de app, startup e backup; hardlinks são recusados antes de mudar permissões. Acrescentou testes de transição atômica do Sticky Code, CAS, linguagem/opacidade, migração e links adversariais. 26 testes de startup/exclusão passaram no fechamento focado. Identificou custo potencial de SQLite por edição; preservou commits síncronos por integridade.
- **Frontend:** atualizou fixtures obsoletos, corrigiu a exclusão para limpar drafts antes de apagar a nota e revisou a mensagem nos catálogos. Falha na limpeza agora cancela exclusão; testes confirmam que a nota/janela permanecem. Revisão visual de resize segue sem sessão gráfica.
- **Auditor independente:** encontrou dois defeitos reproduzíveis P1/P2 no alvo inicial, verificou as correções e não encontrou outro bloqueador no escopo. O parecer está em [docs/audits/2026-10-30-sticky-notes-production-audit.md](audits/2026-10-30-sticky-notes-production-audit.md).

## Verificações consolidadas

| Verificação | Resultado | Limite |
| --- | --- | --- |
| Testes sem display (`make test`) | 146 testes aprovados; 2 pulados | Os dois smokes GTK exigem um display acessível. |
| Suíte completa em XWayland | 146 testes aprovados; nenhum skip | Executada com `GDK_BACKEND=x11`, display e XAUTHORITY da sessão de teste. O teste de reflow usa `Gtk.OffscreenWindow`; o teste de emoji abre apenas uma janela temporária. |
| Smokes GTK em XWayland | Reflow/rolagem de texto e seletor nativo de emoji passaram | Exercita widgets da fonte com conteúdo sintético, não o app instalado nem a GUI do bundle. |
| Janela real da árvore Flatpak construída | Uma nota temporária mapeou e fechou normalmente com GTK 3.24 do host, bus privado e diretórios XDG de teste; nomes ATK de título, conteúdo e mover estavam preenchidos | Os arquivos Python vieram de `build/files`; o app não foi executado no runtime Flatpak GNOME 49, cujo SDK não está instalado. O banco sintético ficou em `/tmp`. Nomes ATK não validam fala/ordem via Orca. |
| `desktop-file-validate` nos dois lançadores | Passou | Valida sintaxe, não testa integração do menu no GNOME. |
| `appstreamcli validate --no-net` | Passou | Não comprova publicação em loja. |
| `compileall` em `sticky-notes/`, `i18n/`, `tests/` | Passou | Verificação sintática, não funcional. |
| Catálogos JSON e paridade `en-US`/`pt-BR` | Passou; 142 chaves em cada idioma | Não substitui leitura humana de todas as traduções. |
| `git diff --check` | Passou | A árvore permanece com alterações locais não commitadas. |
| Build local Flatpak | Passou em `/tmp/orbitz-sticky-production` | Rebuild/smoke de importação passaram; sem instalação nem teste visual. Hash registrado no seguimento abaixo. |
| Instalação e teste visual real | Não executados nesta tarefa | Não recarreguei nem alterei a instalação ativa. |

Na primeira tentativa, o sandbox do runner não podia acessar o display. Com acesso controlado à sessão XWayland, os dois smokes passaram. O teste nativo do emoji havia revelado que a última coluna de botões ultrapassava o grid em 7 px, e a fixture de layout não tinha o estado `set_opacity`/`code_mode` requerido pela implementação atual. Corrigi o tamanho do popup com margem de 8 px em cada dimensão e atualizei a fixture. O teste agora confere que os 48 botões cabem no grid, que o grid inteiro cabe no popup, e que selecionar um emoji o insere no cursor salvo. A antiga expectativa de 480 px e o teste baseado em um `Gtk.Dialog` com campo de busca não correspondiam à implementação atual. A tupla de `translate_coordinates()` é aceita tanto com dois valores quanto com sucesso + coordenadas, cobrindo diferenças entre versões de PyGObject.

## Decisão de release

**Não declarar produção estável ainda.** A auditoria independente, suíte integrada, rebuild local e smoke de importação foram concluídos; o usuário confirmou a validação visual do redimensionamento no seu ambiente. Os próximos gates são smoke de interação do bundle em ambiente gráfico, validação visual de emoji/menus/anexos, smoke real com AT-SPI/Orca, integração com portais e medição ponta a ponta de edição/primeira prévia em máquina representativa. Os limites de PIN e suporte continuam visíveis no README em inglês. Não houve commit, push, publicação nem instalação local nesta revisão.

## Seguimento das pendências 2–5 — 30/10/2026

O usuário confirmou que já validou o item 1 (fluidez visual do resize). Esta rodada definiu a matriz a partir do manifest/CI e do host disponível, reconstruiu o app em caminhos temporários, mediu persistência e revisou acessibilidade. Nenhuma instalação ativa foi modificada.

### Matriz de suporte baseada em evidência

| Ambiente | Evidência nesta rodada | Classificação |
| --- | --- | --- |
| CI Ubuntu 24.04 x86_64, Python 3.12, Xvfb, runtime/SDK GNOME 49 | Workflow executa a suíte e o build do Flatpak. Xvfb não exercita comportamento visual do compositor. | Cobertura automatizada de teste/build; sem homologação desktop visual. |
| Host Ubuntu 22.04.5 x86_64, kernel 6.8.0-138, GNOME Shell 42.9 em Wayland com XWayland, Flatpak 1.12.7 | Suite e dois smokes GTK executados explicitamente com `GDK_BACKEND=x11` na sessão XWayland. A árvore do build mapeou uma nota temporária com GTK host e XDG/D-Bus isolados. Nenhuma instalação ou instância ativa foi tocada. | Smokes de componente e do código empacotado sob GTK host passaram; o app não rodou dentro do Flatpak GNOME 49 porque o SDK exigido não está instalado. |
| X11 / XWayland | O manifest concede `--socket=x11`. Suite completa (146 testes) e smokes do reflow/grade de emoji passaram com `GDK_BACKEND=x11`. | Smoke cobre reflow no `OffscreenWindow` e o popup/seleção nativos, não arraste/resize real pelo compositor, menus, anexos, portal ou janela completa do app. |
| Wayland nativo sem XWayland, KDE, Xfce, outros WM, ARM64/aarch64 | Sem socket Wayland, execução visual, build ou suíte específicos. | Não homologados; não anunciar suporte. |

Esta matriz não define versões mínimas de Flatpak nem certifica a combinação Ubuntu/GNOME. Posição, foco, always-on-top, ações do lançador, portais e múltiplos monitores dependem do compositor e precisam de smoke visual separado. O README limita a prévia a x86_64 com runtime GNOME 49 sobre X11/XWayland.

### Desempenho medido

O backend mediu serialização e commits de texto simples em SQLite WAL com `synchronous=FULL`, diretório temporário ext4, Python 3.10.12, 40 amostras por tamanho e três aquecimentos. As medianas de `Store.text` foram 4,413 ms para 1 KiB, 4,307 ms para 10 KiB e 4,094 ms para 100.000 caracteres; p95 de 6,572 ms, 6,760 ms e 5,590 ms, respectivamente. A serialização simples ficou abaixo de 0,004 ms p95. `Card.document_value()` para buffer GTK em negrito teve medianas de 0,036 ms, 0,075 ms e 0,510 ms nesses tamanhos.

Limites: o disco estava 98% ocupado; a medição não inclui latência de digitação, renderização, resize, sincronização do compositor nem armazenamento lento. Texto formatado de 100.000 caracteres serializou em 100.081 caracteres e ultrapassa o limite atual; portanto, o commit de 100 KB foi medido com texto simples. Esses resultados não demonstram a causa do resize percebido nem justificam trocar o commit síncrono, que evita janela de perda após encerramento abrupto. Falta medir interação ponta a ponta em armazenamento representativo e avaliar a primeira prévia de anexo sob carga.

### Acessibilidade

O conteúdo da nota e o editor Sticky Code agora têm nomes acessíveis localizados; o seletor de linguagem também tem nome e relação explícita com o rótulo. O controle PIN, mover e redimensionar ganharam roles/names/descriptions e operação por teclado: Enter/Espaço ativa; setas movem/ajustam; Shift aumenta o passo; Enter/Esc conclui. Notas secretas ainda passam por autenticação. No smoke da árvore construída, os nomes ATK de título, conteúdo e mover estavam preenchidos e a janela mapeou com dados temporários. Não foi feito smoke manual com Orca/AT-SPI: Orca e PyAT-SPI estão instalados e o socket AT-SPI existe, mas `org.a11y.Status.IsEnabled`, `ScreenReaderEnabled` e `toolkit-accessibility` estavam `false`; não alterei essa preferência. Nomes ATK não garantem fala nem ordem de foco por leitor de tela.

Lacunas: leitores de tela não foram usados para confirmar fala, ordem de foco ou descrição completa. O foco de teclado agora recebe contorno slate discreto; mouse hover/active segue sem fundo e sem aro laranja. Os testes automatizados cobrem ativação e modos por teclado, mas não o comportamento real com Orca/AT-SPI. A interface ainda não está certificada para leitor de tela.

### Build local em diretório temporário

`flatpak-builder` 1.2.2 não estava instalado no sistema; foi extraído em `/tmp`, e a compilação foi feita em `/tmp/orbitz-sticky-production`, sem instalação de sistema ou mudança do Flatpak ativo. O builder 1.2.2 emite aviso de propriedade `license-files` desconhecida, mas concluiu a compilação. A exportação inicial parou porque o repositório OSTree temporário exigia 3% de espaço livre e o disco tinha 2,1%; a configuração `min-free-space-percent=0` foi aplicada somente ao repositório descartável em `/tmp`, e a exportação foi repetida com sucesso. Nenhuma configuração global foi alterada. O smoke dentro do sandbox importou `storage`, `card` e `ui_language` e validou uma tradução. O pacote foi reconstruído depois da correção GTK/acessibilidade; hash e tamanho atualizados estão no fechamento desta seção. Metadata do build confirma app ID `io.orbitz.Postits`, runtime/SDK GNOME 49, x86_64 e socket X11. Isso valida build/importação, não interação completa ou execução gráfica dentro do runtime.

### Segunda rodada — fluxo GTK e disponibilidade dos serviços

O script reproduzível [`tools/benchmark_sticky_interactions.py`](../tools/benchmark_sticky_interactions.py) emite `Gtk.TextBuffer::changed` e mede `Card.changed → document_changed → flush → Store.text`, com 40 amostras e quatro aquecimentos, banco e anexos temporários. Em ext4 com SQLite WAL/`synchronous=FULL`, os resultados p50/p95/máximo foram:

| Conteúdo | Callback completo | Serialização | Commit SQLite | Histórico de undo |
| --- | --- | --- | --- | --- |
| 1 KiB | 4,641 / 8,695 / 11,938 ms | 0,040 / 0,142 / 0,148 ms | 4,495 / 8,522 / 11,034 ms | 0,082 / 0,236 / 0,270 ms |
| 10 KiB | 4,477 / 5,489 / 12,706 ms | 0,039 / 0,095 / 0,115 ms | 4,181 / 5,556 / 9,944 ms | 0,092 / 0,164 / 0,222 ms |
| 100.000 caracteres | 4,768 / 6,723 / 9,041 ms | 0,046 / 0,084 / 0,115 ms | 3,992 / 8,358 / 8,979 ms | 0,079 / 0,120 / 0,160 ms |

Uma miniatura sintética JPEG 1024×768, com decodificação limitada a 280×180 e cache de arquivo aquecido, teve cache-miss de 8,873 / 10,645 / 13,530 ms. O host não tem binding Poppler GI, então não foi medido preview PDF. O script testa o buffer e callback sem janela mapeada: não inclui desenho de frame, input físico, compositor, resize nem mídia em armazenamento lento. O disco estava 98% ocupado. Não há evidência para mudar a gravação síncrona; isso exigiria teste em hardware representativo e uma decisão explícita sobre durabilidade.

Os serviços XDG Portal estavam ativos; Email, OpenURI e FileChooser responderam na versão 3. `toolkit-accessibility` e `org.a11y.Status.IsEnabled/ScreenReaderEnabled` estavam desativados. Um processo Thunderbird já estava aberto com um rascunho; não acionei o handler padrão. Em vez disso, gerei um MIME X-Unsent com anexo sintético pelo helper do app e abri por 12 segundos no Thunderbird headless com perfil novo e `--new-instance`; não houve envio nem acesso ao perfil existente. Isso valida que Thunderbird aceita abrir o formato do arquivo, mas não verifica visualmente os anexos nem o fluxo real via portal, que ainda precisa de VM/perfil gráfico descartável.

### Estado após esta rodada

As pendências 2–5 foram trabalhadas, com os limites acima. O usuário confirmou que o item 1 já foi validado. Testes de teclado continuam majoritariamente com mocks; smoke de leitor de tela, portal/email e interação dentro do sandbox Flatpak ainda faltam. O Flatpak foi reconstruído após o ajuste do popup; o smoke de importação no sandbox passou. O teste `flatpak-builder --run` da aplicação não pôde prosseguir porque o SDK GNOME 49 não está instalado. A árvore construída mapeou uma nota temporária com GTK do host, bus privado e dados em `/tmp`. Bundle atual: `/tmp/orbitz-sticky-production/dist/orbitz-sticky-notes-x86_64.flatpak`, 19.624.256 bytes, SHA-256 `8528a315cb5c352eaaf78e840db7a8241b2bab464247eec90c029aa37215f4c8`. A suíte completa executada em XWayland passou com **146 testes, sem skips**. O auditor independente conferiu o tamanho, hash e metadata do bundle, e revisou o ajuste do popup; não executou a interface completa no sandbox.

### VM de compatibilidade Ubuntu 24.04.4 — 30/10/2026

Foi preparada uma VM Ubuntu 24.04.4 LTS x86_64 em QEMU/KVM. A instalação do bundle `io.orbitz.Postits` e do runtime GNOME 49 foi confirmada com `flatpak info/list`. Em Xvfb/D-Bus, `flatpak run --user io.orbitz.Postits` permaneceu vivo até um timeout controlado de 15 s, sem crash. O portal de documentos reportou que não consegue montar `/run/user/1000/doc` no ambiente Xvfb. Portanto, há evidência de instalação e inicialização do processo, mas não de janela visível ou interação gráfica, compositor, integração real com portais ou fluxo de e-mail. O gate de homologação visual/portal continua aberto. OpenSSH foi habilitado temporariamente com autorização do usuário, encaminhado só em `127.0.0.1`; `ssh.socket`/`ssh.service` foram desativados e a VM desligada após a validação. A suíte local repetida nesta sessão passou com 146 testes e dois skips de GTK por ausência de display.


## Atualização de validação em VM — 30/10/2026

O gate antes aberto de instalação/abertura gráfica básica foi verificado na VM Ubuntu 24.04.4 LTS x86_64 com GNOME Shell 46.0: o bundle Flatpak de hash `8528a315cb5c352eaaf78e840db7a8241b2bab464247eec90c029aa37215f4c8` instalou e abriu uma nota visível na sessão GNOME; `postits.py` permaneceu ativo e o app exibiu a notificação de inicialização. A instalação usa runtime GNOME 49. Houve apenas aviso não fatal pela ausência do módulo opcional `canberra-gtk-module`.

**Efeito na decisão:** a inicialização visual básica está verificada para Ubuntu 24.04/GNOME 46. A recomendação permanece **não declarar produção estável**: ainda faltam interação funcional completa nessa VM (menus, resize/drag, PIN, Sticky Code), portais de arquivos/e-mail, leitor de tela manual, outros ambientes gráficos e medição ponta a ponta representativa. A sessão QA foi encerrada, o SSH temporário foi desativado, socket e serviço ficaram inativos/desabilitados, compartilhamento desmontado e portas locais de encaminhamento fechadas. Nenhuma instalação do host foi alterada.


## Fechamento da rodada funcional em VM — 30/10/2026

Foi continuada a validação do bundle `io.orbitz.Postits` em Ubuntu 24.04.4 LTS / GNOME Shell 46.0 (runtime GNOME 49). O menu abriu; Configurações e Atalhos abriram; foi possível escolher cor, marcar Always above e observar a redução visual da opacidade. O seletor adicionou PDF e PNG sintéticos, e ambos os previews abriram. Uma nota aumentou/diminuiu; a troca para Sticky Code removeu a nota do fundo, manteve título/conteúdo/anexos e a troca de volta preservou os dados. PIN incorreto foi recusado, PIN correto desbloqueou, Esc bloqueou e Ctrl+H ocultou uma nota bloqueada; reabrir via `--open-hidden-notes` a mostrou ainda bloqueada. Arquivar/restaurar funcionou para uma nota sem título identificada no submenu como `undefined-3`; Excluir nota removeu uma nota artificial.

O resize por alça própria do Sticky Code não foi confirmado por automação gráfica; o tamanho mudou via atalho de redimensionamento do GNOME/WM, que não prova o funcionamento do handle personalizado. A composição de e-mail chegou ao handler de `mailto:`; a VM não tinha provedor associado e Firefox interceptou o protocolo. Thunderbird foi instalado só na VM e aberto como handler de sistema, mas sua configuração inicial parou antes do editor de mensagem. Nenhum e-mail foi enviado e os anexos não foram verificados dentro do compositor. As capturas funcionais e seu índice estão em [`tests/evidence/ubuntu-24.04-gnome-46-2026-10-30/`](../tests/evidence/ubuntu-24.04-gnome-46-2026-10-30/).

**Decisão permanece: não recomendar produção estável.** A execução fornece evidência funcional parcial na combinação Ubuntu 24.04/GNOME 46, não certificação de outros ambientes. Restam resize pelo handle do Sticky Code, abertura visual real de rascunho com anexos pelo portal após perfil Thunderbird configurado, validação manual de leitores de tela, outros compositores/distribuições, testes de todos os comandos de menu e benchmark ponta a ponta com input físico/compositor. A instalação Flatpak deste processo de QA e os anexos/note fixtures eram exclusivos da VM; não se alterou a instalação do host.

## Beta 0.2.0 — validação do artefato final — 30/10/2026

**Commit validado:** `19a7e338108e907e61fb8a694d2497d8830b3f95` (`19a7e33`). **CI:** workflow `41110902730` verde para esse commit. **Bundle:** arquivo Flatpak de 19.626.056 bytes, SHA-256 `5f6c7160e02578e5a01e6c520ad409ca10633c48dcfb5a19727b958fa3bb3416`; o mesmo arquivo foi usado nas VMs. A suíte repetida localmente passou com 146 testes; dois testes de geometria/foco GTK foram pulados porque esta execução não tinha display. A CI do commit passou separadamente.

### Evidência por plataforma

| Ambiente | Validado no bundle da CI | Limites |
| --- | --- | --- |
| Ubuntu 22.04.5 LTS, VM limpa, Flatpak 1.12.7 | Atualização de 0.1.0; conteúdo, título, cor, posição, tamanho e referência do anexo sintético permaneceram no SQLite após migração; arquivo anexado continuou presente. O processo abriu e permaneceu ativo sob Xvfb. | VM sem GNOME/display interativo; fluxos visuais não foram homologados aqui. |
| Ubuntu 24.04.4 LTS, GNOME Shell 46, Flatpak 1.14.6 | Atualização do bundle anterior; persistência do fixture; abertura do Sticky Code; resize pelo handle próprio para menor e maior com 200 linhas; Settings, Shortcuts, seletor nativo de arquivos; seleção de anexo; invocação do handler Thunderbird. Opacidade foi conferida nas vistas de nota e code. | Um conjunto de comandos do menu ainda não foi acionado individualmente; demais compositores e sessões não foram testados. |

As capturas do resize feitas com o bundle exato estão em [`tests/evidence/ubuntu-24.04-gnome-46-beta.1-2026-10-30/`](../tests/evidence/ubuntu-24.04-gnome-46-beta.1-2026-10-30/). A rodada anterior de evidência visual continua separada e mantém seu próprio checksum/limitações.

### Email, conclusão beta e pendências

O formulário de email aceitou o endereço de teste e Enter acionou o cliente Thunderbird instalado na VM. O Thunderbird abriu o assistente de primeira execução, e não o editor de mensagem; assim, o conteúdo e o anexo do compositor não foram verificados visualmente. Os testes automatizados confirmam a criação do MIME X-Unsent com corpo e anexo sintético, mas não substituem a validação ponta a ponta no cliente configurado. Nenhuma mensagem foi enviada.

O bundle pode ser publicado como **beta para Ubuntu 22.04 e 24.04 x86_64**, com esses limites explícitos nas notas. Isso não equivale a recomendação de produção estável: fluxo visual Thunderbird com anexo, todos os comandos do menu, Orca/AT-SPI, Wayland nativo, outros ambientes gráficos e arquiteturas permanecem fora da cobertura demonstrada. As VMs de QA foram desligadas e os encaminhamentos SSH temporários estavam fechados ao final desta rodada; instalações e dados pessoais do host não foram alterados.

## Atualização da validação do candidato beta.1 exato — 30/10/2026

**Esta atualização substitui a afirmação acima de que o candidato exato estaria validado para publicação em Ubuntu 22.04 e 24.04.** O bundle `9e98800a…4ea24` do commit `b02144d` foi instalado como atualização na VM Ubuntu 24.04.4/GNOME 46 e passou pelas verificações visuais anotadas em [`docs/validation.md`](validation.md) e evidenciadas em [`tests/evidence/ubuntu-24.04.4-exact-beta.1-2026-10-30/`](../tests/evidence/ubuntu-24.04.4-exact-beta.1-2026-10-30/README.md). A comparação pré/pós preservou os registros de quatro notas sintéticas e suas posições/dimensões/textos.

O reteste também identificou dois limites que precisam ficar visíveis antes de declarar cobertura completa: a referência de anexo armazenada no banco aponta para `/run/flatpak/doc/...` e não resolve após reiniciar a sessão; e o comando `Open hidden notes` no menu do ícone não foi confirmado como restaurando uma nota. O menu da própria nota restaurou a nota oculta. O rascunho gerado continha corpo e anexo MIME e abriu o Thunderbird, mas a tela de primeira execução impediu verificar o compositor; nenhuma mensagem foi enviada.

**Estado corrigido da recomendação:** a versão exata `b02144d` tem evidência de atualização e interação em Ubuntu 24.04.4. Não há evidência do bundle exato em Ubuntu 22.04; essa versão não deve ser incluída como compatibilidade validada com base apenas nos candidatos anteriores. A release beta ainda não foi publicada nesta rodada. Persistência de conteúdo de anexos, rota do launcher para notas ocultas, configuração visual do cliente de e-mail e validação em Ubuntu 22.04 continuam pendentes.

## Final beta.1 package — 2026-10-30

Supersedes the prior exact-candidate gap for Ubuntu 22.04 and durable attachment storage. Source `ba29f50`, CI run 41153532222 passed. The official artifact SHA-256 is `11b1d7bcaa27911cde14d3947128e3d64256f5896167bb2014ef7a9cfe58a9ac`; targeted installed-runtime checks passed on Ubuntu 22.04.5/Xvfb and Ubuntu 24.04.4/GNOME 46/XWayland. Local suite: 154 tests passed, no skips. See [final package evidence](../tests/evidence/beta.1-final-2026-10-30/README.md) for transcripts, screenshot, commands and limits. This supports a public prerelease with the documented limits, not stable-production certification. Thunderbird composition and direct GNOME icon-menu interaction remain unverified in the final build.
