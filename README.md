# Transcritor

Transcritor local de áudios, feito em cima do [faster-whisper](https://github.com/SYSTRAN/faster-whisper) e pensado
para os áudios de WhatsApp. **Tudo roda no seu computador; nenhum áudio sai dele.**

O que ele faz:

- **Transcreve** um arquivo ou uma pasta inteira (`.ogg`, `.opus`, `.mp3`, `.m4a`, `.wav`, vídeo e outros) para
  `txt`, `md`, `json`, `srt` e `vtt`.
- **Links de vídeo** (opcional): cole o link de um vídeo do YouTube (ou de outro site que o
  [yt-dlp](https://github.com/yt-dlp/yt-dlp) conheça) e o pipeline baixa o áudio, transcreve e, se quiser, resume.
- **Glossário** de nomes e termos que cresce com o uso e é passado ao Whisper como dica.
- **Antirrepetição e alertas:** remove loops e trechos corrompidos e avisa quando algo parece estranho.
- **Busca** em todas as transcrições (SQLite, sem diferenciar acentos nem maiúsculas).
- **Quem fala** (opcional): identifica a pessoa de cada áudio comparando a voz com as pessoas cadastradas.
- **Resumo** (opcional): o que foi definido, o que está em aberto, tarefas e um fluxograma Mermaid, usando o
  [Ollama](https://ollama.com) local.
- **Interface web** com fila, cancelamento, prévia do texto, busca e glossário, só neste computador.
- Funciona como **comando** (`transcritor`) e como **biblioteca Python**.

## O que você precisa

| | Mínimo | Recomendado |
|---|---|---|
| Sistema | Windows 10/11 (é onde foi testado). Linux e macOS devem funcionar no modo CPU, mas não foram testados | Windows 11 |
| Python | 3.10 ou mais novo | 3.11+ |
| Placa de vídeo | Nenhuma (use `--cpu`, bem mais lento) | NVIDIA com 6 GB ou mais |
| Disco | ~0,5 GB sem GPU; ~2,5 GB com as bibliotecas CUDA; ~3 GB para o modelo do Whisper | 10 GB livres |
| Internet | Só para instalar e para baixar os modelos na primeira vez | |

Não precisa instalar o ffmpeg: a leitura de áudio já vem junto com o faster-whisper.

## Instalar

**1. Baixe o projeto**

```
git clone https://github.com/gfernandes4/transcritor.git
cd transcritor
```

**2. Crie um ambiente virtual e ative**

Windows (PowerShell):

```
python -m venv .venv
.venv\Scripts\Activate.ps1
```

(Se `python` não for reconhecido mas o Python estiver instalado, tente `py -m venv .venv`.)

Linux ou macOS:

```
python3 -m venv .venv
source .venv/bin/activate
```

> No Windows com Python da Microsoft Store, crie o ambiente numa pasta fora de `AppData`, senão o Windows
> redireciona os arquivos e o ambiente quebra.

**3. Instale o Transcritor.** Escolha uma linha, conforme o que você quer usar:

```
pip install -e ".[gpu,web]"             # placa NVIDIA + interface web (o caminho mais comum)
pip install -e ".[web]"                 # sem placa NVIDIA (use --cpu ao transcrever)
pip install -e ".[gpu,web,youtube]"     # com links do YouTube
pip install -e ".[gpu,web,vozes]"       # com identificação de voz
pip install -e ".[gpu,web,vozes,youtube,dev]"   # tudo, mais os testes
```

Extras: `gpu` (bibliotecas CUDA), `web` (interface no navegador), `youtube` (transcrever a partir de links),
`vozes` (quem fala), `dev` (testes).
O resumo não precisa de extra, só do Ollama.

**4. Confira que funcionou**

```
transcritor --help
```

## Primeiros passos

**Pela interface web (o jeito mais fácil):**

```
transcritor web
```

Abra http://127.0.0.1:8800 no navegador, arraste os áudios, escolha os formatos e clique em Transcrever.
Na primeira transcrição o modelo `large-v3` (~3 GB) é baixado; as seguintes já começam direto.

A interface só escuta em `127.0.0.1` e não tem login: não deixe exposta na internet.

**Pela linha de comando:**

```
transcritor transcrever pasta_de_audios/                  # uma pasta inteira (ou um arquivo)
transcritor transcrever audio.ogg --formatos txt,srt,md
transcritor transcrever audio.ogg --cpu                   # sem placa NVIDIA
transcritor glossario add "Lamine Yamal"                  # o glossário cresce com o uso
transcritor glossario listar
transcritor glossario sugerir pasta_de_audios/transcricoes   # nomes novos que apareceram 2x ou mais
transcritor buscar "cartão SD"                            # busca em tudo o que já foi transcrito
transcritor resumir pasta_de_audios/transcricoes          # resumo.md + resumo.json + fluxo.mmd
```

Por padrão grava `.txt`, `.md` e `.json` em `<pasta>/transcricoes/`. `--bruto` volta ao comportamento mais simples
(sem glossário, ajustes nem limpeza), útil para comparar.

### Transcrever a partir de um link (opcional)

```
pip install -e ".[youtube]"
transcritor transcrever "https://www.youtube.com/watch?v=XXXXXXXXXXX"
transcritor transcrever "<link 1>" "<link 2>" audio.ogg pasta/      # pode misturar links, arquivos e pastas
transcritor transcrever "<link>" --saida meus_videos --resumir      # transcreve e resume na mesma rodada
```

O áudio é baixado numa pasta temporária, transcrito e apagado em seguida. O resultado leva o título do vídeo,
o canal e o link (no `.md` e no `.json`), entra na busca e fica em `./transcricoes/` (ou na pasta de `--saida`).
Na interface web é só colar o link no campo "Ou cole links de vídeo" e, se quiser, marcar "Resumir depois".
Na biblioteca: `transcrever("https://...")` ou `transcrever_url(...)`.

Cada link é um vídeo só (playlists e canais são recusados com um aviso). A identificação de voz não se aplica a
links, porque o apresentador não está entre as pessoas cadastradas.

### Resumo (opcional)

Instale o [Ollama](https://ollama.com), baixe um modelo e rode o resumo **depois** da transcrição:

```
ollama pull llama3.1:8b
transcritor resumir pasta_de_audios/transcricoes
```

Ou na mesma rodada, com `--resumir` (a interface web tem a caixa "Resumir depois"): o Whisper é descarregado da
placa de vídeo antes do Ollama começar. Se o resumo falhar, a transcrição já está salva.

Há dois modos, escolhidos sozinhos (`--modo-resumo auto`, o padrão) ou à força com `--modo-resumo conversa|video`:

- **Conversa** (áudios de gente conversando): o que ficou definido, o que está em aberto, tarefas com responsável,
  pessoas citadas e um fluxograma Mermaid (`resumo.md`, `resumo.json`, `fluxo.mmd`).
- **Vídeo** (quando tudo veio de links): "Resumo do vídeo" com um resumo em poucas linhas, o passo a passo numerado
  com o minuto de cada passo, os pontos principais e as ferramentas citadas (`resumo.md`, `resumo.json`), sem lista
  de pessoas nem fluxograma. Textos longos são lidos em partes, então o vídeo inteiro entra no resumo. Num tutorial
  de 27 minutos, o resumo levou ~4 minutos numa RTX 3050.

Whisper e Ollama não cabem juntos em 6 GB de placa de vídeo, por isso o resumo roda sempre depois.
O modelo de 8 bilhões de parâmetros serve de ponto de partida, não de verdade final: confira antes de usar.

### Quem fala (opcional)

```
transcritor vozes baixar-modelo                          # baixa o CAM++ (~28 MB) e confere o SHA-256
transcritor vozes cadastrar Ana pasta_com_audios_da_ana  # cinco ou mais áudios de cada pessoa ajudam
transcritor vozes testar audio.ogg                       # mostra de quem é
transcritor transcrever pasta --falantes                 # grava o falante no JSON e na busca
transcritor vozes aplicar pasta_audios --transcricoes pasta_json   # em transcrições que já existem
transcritor buscar SD --falante Ana
```

Abaixo do limiar de similaridade o áudio fica como "desconhecido", em vez de receber um nome errado.
É **um falante por arquivo**: separar várias vozes dentro do mesmo áudio não está no escopo.

Para medir e calibrar com áudios que você já sabe de quem são, monte um JSON `{"arquivo.ogg": "Nome"}` e rode:

```
transcritor vozes avaliar pasta rotulos.json --desconhecidos <áudios de outras pessoas> --salvar --cadastrar
```

Cada áudio é identificado usando só os outros como cadastro (leave-one-out). O limiar fica entre a pior
similaridade de um acerto e a maior de uma voz de fora; a margem exigida sobre a segunda pessoa é metade da menor
folga. Em 39 áudios de duas pessoas, o resultado foi 39 de 39 certos, sem nenhum erro de pessoa. A folga para vozes de
fora foi pequena (0,70 contra 0,74), então recalibre com `--desconhecidos` se o tipo de áudio mudar.

## Usar em outros projetos (Python)

```python
from transcritor import transcrever, buscar

t = transcrever("audio.ogg", glossario=["Davi", "Elisa"])
print(t.texto)            # "[00:00:00] Opa, fala aí meu." ...
print(t.alertas)          # trechos suspeitos, se houver
t.salvar("saida/", formatos=["txt", "srt"])

v = transcrever("https://www.youtube.com/watch?v=XXXXXXXXXXX")   # precisa do extra [youtube]
print(v.origem["titulo"], v.texto_simples[:200])

for achado in buscar("cartão SD"):
    print(achado["arquivo"], achado["inicio"], achado["texto"])
```

Para várias transcrições seguidas, reaproveite o modelo: `Motor` em `transcritor.nucleo.whisper` (carrega uma vez)
ou `transcrever_pasta()`.

## Onde ficam seus dados

Em `~/.transcritor/` (no Windows, `C:\Users\<você>\.transcritor\`): `glossario.txt`, `db.sqlite` (busca e vozes),
`vozes.json` (calibração) e `modelos/`. Para usar outra pasta, defina a variável `TRANSCRITOR_HOME`. Nada disso fica
dentro do repositório.

## Limites conhecidos

- Nomes que não estão no glossário podem sair errados. Use `glossario sugerir` depois de transcrever.
- O resumo de vídeo é um rascunho: o modelo local pode errar nomes de ferramentas que a transcrição escreveu errado
  (por exemplo, "Veo 3" virar "Vio 3"), juntar ou dividir passos de um jeito diferente do seu, e esquecer detalhes.
  Confira com o vídeo antes de usar.
- Links: o YouTube muda com frequência, então o yt-dlp precisa de atualização de vez em quando
  (`pip install -U yt-dlp`). Às vezes o YouTube pede verificação anti-robô; o Transcritor não tenta contornar isso,
  só avisa, e você pode baixar o vídeo por outro meio e enviar o arquivo. Use apenas com conteúdo que você pode
  transcrever e respeite os termos do site e os direitos do autor.
- Fora do escopo: separar várias vozes no mesmo áudio, transcrição em tempo real, tradução e clonagem de voz.
- Testado no Windows 11 com uma RTX 3050 de 6 GB. Em Linux e macOS ainda não foi testado.
- Se aparecer erro de `cublas` ou `cudnn`, instale com o extra `gpu` ou rode com `--cpu`.

## Interface

A avaliação da interface web pelas 10 heurísticas de Nielsen está em
[docs/interface-nielsen.md](docs/interface-nielsen.md). Nenhum script, fonte ou imagem vem da internet.

## Testes

```
pip install -e ".[dev,web]"
python -m pytest        # rápidos, sem baixar modelo
```

## Licença

[MIT](LICENSE)
