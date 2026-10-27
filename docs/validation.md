# Origem e validação

Extração em 27/10/2026 de `orbitzone/orbitz-widgets-for-gnome`, base Git `a0bcb0302405d176aa3be5118a5b211caf90d1fd`, usando as fontes Sticky Notes e traduções presentes no checkout nessa data. Não foram copiados bancos, backups pessoais, credenciais, arquivos históricos de instalação nem dependências vendorizadas de outros componentes.

`storage.py`, `card.py` e `link_targets.py` foram preservados. A inicialização independente não tenta importar `orbitz-widgets/notes.json`. O runtime de tradução é derivado de `i18n/ui_i18n.py`, com schema próprio `io.orbitz.Postits` e sem pesquisa nas pastas da extensão instalada. Os catálogos incluem somente chaves Sticky Notes.

Escopo: distribuições Linux com Flatpak/X11 ou XWayland; sem Windows/macOS, migração automática, ativação da instalação atual ou publicação no Flathub. Pacote inicial x86_64; outras arquiteturas precisam de build e validação próprios. CI gera artefato de teste, não equivale a homologação das distribuições. Rodadas e limites locais serão registrados após verificação.

Verificação local inicial: 84 testes herdados executados (82 aprovados, dois smokes GTK pulados por ausência de display), mais dois testes de empacotamento aprovados. Staging temporário, importação independente, locale inglês, criação SQLite em fixture, falha clara sem DISPLAY, cobertura de catálogos, desktop-file-validate e appstreamcli validate --no-net passaram. Revisão independente focada do instalador não encontrou bloqueio para publicar fontes; condicionou distribuir o bundle ao build e smoke de importação no CI. Nenhum teste usou notas pessoais. O arquivo card.py preserva uma linha vazia adicional no final herdada da origem.
