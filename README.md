# Sticky Notes - By Orbitz

Notas coloridas e independentes para sua área de trabalho Linux. Escreva, organize por cores, personalize títulos, abra links com Ctrl+clique e mantenha as notas à mão sem instalar uma extensão do GNOME Shell.

Desenvolvido por **Felipe Santiago / orbitzone**. Extraído do [Orbitz Widgets for GNOME](https://github.com/orbitzone/orbitz-widgets-for-gnome), sob GPL-3.0. A versão independente conserva o armazenamento SQLite, conflitos de revisão, backups diários e o bloqueio visual por PIN. **O PIN não criptografa o texto nem os backups.**

## Instalação Linux com Flatpak

O pacote atende distribuições com Flatpak e sessão X11 ou Wayland com XWayland. Não depende da versão do GNOME Shell. Não há garantia para qualquer versão de Linux: kernel, Flatpak, arquitetura e ambiente gráfico precisam ser compatíveis com o runtime. O primeiro pacote é x86_64; ARM64 ainda não é validado.

1. [Instale o Flatpak para sua distribuição](https://flatpak.org/setup/).
2. Baixe `orbitz-sticky-notes-x86_64.flatpak` na [prévia v0.1.0](https://github.com/orbitzone/orbitz-sticky-notes/releases/tag/v0.1.0). É uma versão para testes; ainda não há publicação no Flathub nem canal de atualização automática.
3. No diretório do pacote, execute:

```sh
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user ./orbitz-sticky-notes-x86_64.flatpak
flatpak run io.orbitz.Postits
```

O aplicativo também aparece no menu. Para atualizar, instale um novo pacote pelo mesmo comando. Não é necessário reiniciar o GNOME; encerre o aplicativo pelo menu da nota e reabra após atualizar. Não habilitamos início automático no login.

O pacote x86_64 passou por build e smoke de importação no sandbox; os 90 testes passaram no CI Ubuntu 24.04 com display virtual, incluindo os dois smokes GTK antes indisponíveis localmente. Isso ainda não equivale a homologação visual em GNOME/KDE/Xfce reais. O arquivo `SHA256SUMS` da release permite conferir o download com `sha256sum -c SHA256SUMS`.

## Uso e dados

- Clique e escreva; título editável e seis cores.
- Ctrl+B aplica negrito, Ctrl+I itálico, Ctrl+U sublinhado e Ctrl+E abre o seletor de emoji. Com texto selecionado, o atalho alterna a formatação; sem seleção, ativa o estilo para o próximo texto digitado.
- Dicas de texto foram removidas. Ao passar sobre imagens e PDFs anexados, ainda aparece a miniatura visual personalizada.
- Ctrl+N cria nota; Ctrl+Z / Ctrl+Shift+Z desfaz/refaz; Ctrl+H oculta. Fechar a nota também a oculta, sem excluir seu conteúdo.
- Arraste a faixa compacta acima do título para mover a nota. Arraste o canto inferior para redimensionar. O menu fecha ao clicar fora.
- O menu permite reexibir notas ocultas e arquivar a nota atual. Notas ocultas e arquivadas aparecem como títulos em listas suspensas; selecionar uma nota oculta a reabre, e selecionar uma arquivada a restaura. Títulos de notas secretas ficam ocultos nessas listas.
- A exclusão permanente só está disponível no menu da nota e remove a nota imediatamente. Fechar ou ocultar nunca exclui uma nota.
- O menu permite anexar arquivos; também é possível arrastá-los sobre o texto da nota sem inserir o caminho no conteúdo. Os ícones ficam no rodapé: clique para abrir; clique com o botão direito para mostrar a pasta de origem ou remover o vínculo da nota. São aceitos formatos comuns de imagem, texto, PDF, Microsoft Office, OpenDocument/OpenOffice e arquivos ZIP, RAR, 7z, TAR e compactados. Cada nota aceita até 10 arquivos, 50 MiB por arquivo e 100 MiB no total.
- “Enviar nota por e-mail” abre um rascunho no cliente padrão, com o texto no corpo e os anexos selecionados. O app não envia a mensagem; revise e envie no cliente de e-mail. Em sistemas com portal de e-mail antigo, o app usa o portal de abertura de links para entregar os anexos ao cliente padrão.
- Notas secretas se bloqueiam ao reabrir, ao ocultar/fechar a nota e após 15 segundos com o ponteiro fora. Enquanto bloqueadas, o conteúdo e os anexos ficam ocultos e alterações no texto, título, cor, tamanho, anexos ou ordem das janelas exigem o PIN; o cadeado central abre o diálogo de desbloqueio. Movimentos feitos pelo gerenciador de janelas não são salvos enquanto a nota está bloqueada. O PIN é uma barreira da interface, não criptografa os dados. Em Configurações, “Esqueci meu PIN” solicita confirmação e então apaga todas as notas secretas e seus registros nos backups para permitir definir outro PIN; as notas comuns são preservadas.
- No Flatpak, banco e backups ficam em `~/.var/app/io.orbitz.Postits/data/orbitz-postits/`. Não apagamos os dados ao atualizar. A instalação antiga do Orbitz permanece intacta; não há importação automática. Evite executar as duas versões ao mesmo tempo, pois compartilham o ID de aplicação.
- Anexos permanecem nas pastas escolhidas; o app grava caminhos e nomes no banco e nos backups, sem apagar os arquivos originais. No Flatpak, a seleção usa o portal de arquivos e concede acesso aos arquivos escolhidos. Se um arquivo for movido ou apagado, remova e adicione o anexo novamente. Excluir a nota remove os vínculos, os metadados dos backups e os rascunhos temporários do Orbitz associados a ela; cópias já abertas em outros aplicativos ficam fora do controle do app.
- PT-BR é o idioma padrão. Para inglês: `flatpak run --env=ORBITZ_LOCALE=en-US io.orbitz.Postits`. Configurações de idioma do Orbitz Widgets não são usadas.

## Compatibilidade e privacidade

O pacote usa GTK 3 via X11, inclusive em sessões Wayland com XWayland. Sessões sem XWayland não são suportadas nesta versão. Posição, manter acima e presença em todos os espaços dependem do gerenciador de janelas. Testes em GNOME, KDE e Xfce, escalas mistas e monitores reais ainda devem compor a matriz de validação; build/testes automatizados não comprovam esse comportamento visual.

O Flatpak não recebe acesso geral à pasta pessoal nem à rede. Acesso X11 é necessário para o comportamento atual das janelas e tem o isolamento limitado próprio desse protocolo. Links web/e-mail usam o aplicativo padrão por Gio/portal; caminhos locais fora do sandbox não estão disponíveis sem seleção explícita. O PIN protege apenas a interface: textos, títulos, caminhos e nomes dos anexos permanecem sem criptografia no SQLite e nos backups. Os arquivos anexados continuam sob as permissões da pasta de origem. Não há sincronização, telemetria ou migração automática de dados.

## Compilar e desenvolver

Instale `flatpak-builder`, Flatpak e o remoto Flathub. Na raiz:

```sh
flatpak-builder --user --install-deps-from=flathub --assumeyes --repo=repo build-dir packaging/io.orbitz.Postits.json
flatpak build-bundle repo orbitz-sticky-notes-x86_64.flatpak io.orbitz.Postits --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo
```

Para desenvolvimento nativo: Python 3.10+, PyGObject, GTK 3.24 e SQLite. Execute `python3 sticky-notes/postits.py` em sessão gráfica; isso usa o diretório nativo `~/.local/share/orbitz-postits/` (ou `$XDG_DATA_HOME/orbitz-postits/`). Use um `XDG_DATA_HOME` temporário para testes. `make test` executa a suíte com bancos temporários. `make install PREFIX=/caminho` é para empacotadores; o instalador recomendado ao usuário é Flatpak.

Veja [a origem e o estado de validação](docs/validation.md).
