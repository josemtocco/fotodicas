# Instalar no GitHub (passo a passo)

Tempo: cerca de 5 minutos. Depois disso a lista se atualiza sozinha a cada 6 horas.

## 1. Criar o repositório

1. Entre em <https://github.com/new>.
2. Nome: `fotodicas-m3u`.
3. Marque **Public** (o SS IPTV precisa ler o arquivo sem login) e clique em
   **Create repository**.

## 2. Subir os arquivos

1. Na página do repositório, clique em **uploading an existing file**.
2. Arraste **todos** os arquivos e a pasta `.github` do projeto:
   - `atualizar_m3u.py`
   - `fotodicas.m3u`
   - `estado_canais.json`
   - `relatorio_teste.csv`
   - `rodar_no_brasil.bat`
   - `LEIA-ME.md`, `INSTALAR_NO_GITHUB.md`
   - `.github/workflows/atualizar.yml`
3. Clique em **Commit changes**.

> Se o navegador não deixar arrastar a pasta `.github`, use **Add file → Create new
> file** e digite o caminho `.github/workflows/atualizar.yml`; cole o conteúdo do
> arquivo e confirme.

## 3. Liberar a automação para gravar

1. **Settings → Actions → General**.
2. Em **Workflow permissions**, marque **Read and write permissions** e salve.

Sem esse passo a automação roda mas não consegue publicar a lista nova.

## 4. Ligar a atualização automática

1. Aba **Actions** → escolha **Atualizar lista M3U (Fotodicas)**.
2. Clique em **Enable workflow** (se aparecer).
3. Clique em **Run workflow → Run workflow** para a primeira execução manual.
4. Espere uns 6 minutos. Ao terminar, o repositório terá a lista atualizada e um
   commit novo.

Depois disso ela roda sozinha nos horários `00h, 06h, 12h, 18h` (UTC).

## 5. Pegar o endereço da lista

```
https://raw.githubusercontent.com/SEU-USUARIO/fotodicas-m3u/main/fotodicas.m3u
```

Troque `SEU-USUARIO` pelo seu nome de usuário. Cole no SS IPTV em
**Configuração → Playlists → Adicionar playlist → URL externa**.

## 6. Conferir se está tudo certo

- **Code**: `fotodicas.m3u` com data de hoje.
- **Actions**: última execução verde.
- **relatorio_teste.csv**: mostra canal por canal o resultado do teste
  (`ok`, `audio`, `inconclusivo`, `quebrado`, `embed`, `youtube`, `sem_link`).

Se a execução ficar vermelha, abra o log e me mande o trecho do erro: eu ajusto
certinho.

## Dicas

- **Não apague** `estado_canais.json`: é a memória das 6 atualizações.
- Quer rodar na hora? **Actions → Run workflow**.
- Quer uma lista mais completa de canais brasileiros? Rode o
  `rodar_no_brasil.bat` no seu PC (IP brasileiro) e suba os 3 arquivos gerados.
- Repositório privado também funciona, mas aí o SS IPTV não consegue ler a URL.
