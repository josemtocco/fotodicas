# Lista M3U do Fotodicas para SS IPTV / VLC

Lista de canais de TV aberta gerada a partir do site **fotodicas.com**, organizada por
categorias iguais às do site, com teste real de reprodução antes de publicar.

## Resultado da última geração

| Etapa | Quantidade |
|---|---|
| Páginas do site verificadas | 363 |
| Canais encontrados | 296 |
| **Canais na lista (tocando)** | **104** |
| Vídeo confirmado no teste | 106 |
| Somente áudio | 1 |
| Inconclusivo (bloqueio de região/rede) | 19 |
| Link quebrado de verdade | 19 |
| Só YouTube (não serve para IPTV) | 44 |
| Player de terceiros (sem link direto) | 8 |
| Sem link configurado no próprio site | 99 |

O teste abre o `.m3u8` de cada canal, entra na variante mais leve do HLS, baixa um
pedaço real do vídeo e confere com `ffprobe` se existe imagem. **Não é teste de
"respondeu 200"** — é teste de imagem decodificada.

## Como usar no SS IPTV

1. Suba o projeto no GitHub (veja `INSTALAR_NO_GITHUB.md`).
2. Copie o endereço da lista:
   `https://raw.githubusercontent.com/SEU-USUARIO/fotodicas-m3u/main/fotodicas.m3u`
3. No SS IPTV: **Configuração → Playlists → Adicionar playlist → URL externa**,
   cole o endereço e confirme.
4. As categorias do site aparecem como pastas (Globo, Record, SBT, Band, RedeTV,
   Notícias, Esporte, Filmes, Desenhos, Música, Rádios, Religiosos, TV Aberta,
   Documentário, Outros).

A lista já vai no repositório, então funciona na hora, sem esperar a primeira
automação. O SS IPTV recarrega sozinho quando o arquivo muda.

## O que a automação faz a cada 6 horas

- Varre o site inteiro: menu de categorias, paginação dos arquivos (botão
  "próximo"/"carregar mais" até acabar) e o sitemap. Nada de pegar só a primeira página.
- Abre o player de cada canal e extrai o link direto do stream.
- Testa o vídeo de verdade.
- Mantém a memória em `estado_canais.json`:
  - canal novo e funcionando → entra na lista;
  - canal que já estava na lista e falhou → **continua publicado** com o último
    link bom;
  - canal só sai depois de **6 falhas reais seguidas**;
  - falha por bloqueio de região/rede (`401`, `403`, `451`, tempo esgotado) é
    marcada como *inconclusivo* e **não conta falha**, para não derrubar canal
    bom só porque o servidor do GitHub fica nos Estados Unidos;
  - se o site sair do ar e voltar menos canais que 35% do total anterior, a
    rodada é abortada e a lista antiga é preservada (proteção contra lista vazia).

## Rodar no Brasil (recomendado na primeira vez)

O GitHub roda nos Estados Unidos, então parte dos canais brasileiros responde
`403` de lá. Rode uma vez no seu PC, no Brasil:

1. Clique com o botão direito em `rodar_no_brasil.bat` → **Executar**.
2. Ele confere o Python e o `ffmpeg`, gera `fotodicas.m3u` e mostra o resumo.
3. Suba os arquivos gerados (`fotodicas.m3u`, `estado_canais.json`,
   `relatorio_teste.csv`) para o repositório. A partir daí a automação cuida sozinha.

Se aparecer `[AVISO] ffmpeg nao encontrado`, instale o ffmpeg portátil: baixe
`ffmpeg-release-essentials.zip` em <https://www.gyan.dev/ffmpeg/builds/>,
descompacte e renomeie a pasta para `C:\ffmpeg` (deve existir
`C:\ffmpeg\bin\ffprobe.exe`). É só uma pasta: não instala nada no Windows e não
mexe em outros programas. Para desfazer, apague a pasta.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `fotodicas.m3u` | a lista pronta para o SS IPTV / VLC |
| `estado_canais.json` | memória das falhas e das 6 atualizações (não apague) |
| `relatorio_teste.csv` | relatório do teste, abre no Excel (separado por `;`) |
| `atualizar_m3u.py` | o script (só biblioteca padrão do Python, sem instalar nada) |
| `.github/workflows/atualizar.yml` | automação de 6 em 6 horas |
| `rodar_no_brasil.bat` | execução local no Windows |
| `testar_regras.py` | testes das regras de remoção/anti-lista-vazia |

## Observações importantes

- A lista só usa links que o próprio site publica; o projeto não hospeda conteúdo
  nenhum. Canais com transmissão restrita podem sair do ar a qualquer momento.
- Canais que o site exibe apenas por YouTube ou por player de terceiros ficam de
  fora: não geram link HLS e não funcionam no SS IPTV.
- Alguns canais são regionais e só abrem com internet brasileira. Se um canal seu
  aparecer como *inconclusivo* no relatório, teste de casa antes de concluir que
  ele morreu.
- Nomes, categorias e logos vêm do site. Quando o logo não carrega, o campo fica
  vazio em vez de mostrar imagem quebrada.
