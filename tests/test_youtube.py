"""Testes dos links de vídeo, sem internet e sem modelo: o yt-dlp e o Whisper são trocados por versões de mentira."""
import sys
import types
from pathlib import Path

import pytest

from transcritor import api, busca, cli, exportar
from transcritor.nucleo import youtube
from transcritor.resumo import resumir
from transcritor.transcricao import Transcricao

LINK = "https://www.youtube.com/watch?v=5Pr1kNiDwAE"


@pytest.fixture(autouse=True)
def home_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRITOR_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)


class MotorFalso:
    nome = "falso"

    def __init__(self, ordem=None):
        self.ordem = ordem if ordem is not None else []

    def transcrever(self, caminho, parametros, termos):
        return [{"inicio": 0.0, "fim": 2.0, "texto": "Olá, mundo."}], 2.0, "pt"

    def descarregar(self):
        self.ordem.append("descarregou")


def baixar_de_mentira(url, pasta):
    arquivo = Path(pasta) / "5Pr1kNiDwAE.webm"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_bytes(b"audio")
    return youtube.Baixado(arquivo=arquivo, url=url, titulo="Como criar uma IA v2.0", canal="Canal X", duracao_s=1620, id="5Pr1kNiDwAE")


# ---------- reconhecer e limpar ----------

@pytest.mark.parametrize("texto, esperado", [
    (LINK, True), ("  http://exemplo.com/x  ", True), ("HTTPS://X.COM/a", True),
    ("audio.ogg", False), ("C:\\pasta\\audio.ogg", False), ("youtube.com/watch?v=1", False), ("ftp://x.com", False), ("", False), (None, False),
])
def test_eh_url(texto, esperado):
    assert youtube.eh_url(texto) is esperado


def test_nome_seguro_tira_pontos_e_caracteres_proibidos():
    # um ponto no meio do título enganaria a extensão do arquivo (Path.stem)
    assert youtube.nome_seguro('IA 100% Grátis: v2.0 / "teste"?') == "IA 100% Grátis v2 0 teste"
    assert youtube.nome_seguro("...") == "video"
    assert len(youtube.nome_seguro("x" * 300)) == 80


def test_nome_e_origem_do_video():
    b = baixar_de_mentira(LINK, Path("."))
    assert b.nome == "Como criar uma IA v2 0 [5Pr1kNiDwAE]"
    assert b.origem() == {"url": LINK, "titulo": "Como criar uma IA v2.0", "canal": "Canal X"}
    assert Path(b.nome).stem == b.nome   # não perde pedaço do nome ao gravar


@pytest.mark.parametrize("mensagem, trecho", [
    ("ERROR: [youtube] x: Sign in to confirm you’re not a bot", "anti-robô"),
    ("ERROR: Private video. Sign in", "privado"),
    ("ERROR: Video unavailable", "privado"),
    ("ERROR: Sign in to confirm your age. This video may be inappropriate", "idade"),
    ("ERROR: Unsupported URL: https://x.com", "reconheci"),
    ("ERROR: <urlopen error [Errno 11001] getaddrinfo failed>", "internet"),
    ("ERROR: algo que ninguém previu", "algo que ninguém previu"),
])
def test_erros_do_ytdlp_viram_mensagem_que_diz_o_que_fazer(mensagem, trecho):
    assert trecho in youtube.traduzir_erro(mensagem)


# ---------- download (yt-dlp de mentira) ----------

def instalar_ytdlp_falso(monkeypatch, info=None, erro=None):
    class DownloadError(Exception):
        pass

    class FalsoYDL:
        def __init__(self, opcoes):
            self.opcoes = opcoes

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            if erro:
                raise DownloadError(erro)
            Path(self.opcoes["outtmpl"].replace("%(id)s.%(ext)s", "abc.m4a")).write_bytes(b"x")
            return info if info is not None else {"id": "abc", "title": "Meu vídeo", "uploader": "Eu", "duration": 61}

        def prepare_filename(self, info):
            return self.opcoes["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", "m4a")

    modulo = types.SimpleNamespace(YoutubeDL=FalsoYDL, utils=types.SimpleNamespace(DownloadError=DownloadError))
    monkeypatch.setitem(sys.modules, "yt_dlp", modulo)
    monkeypatch.setattr(youtube, "disponivel", lambda: True)
    return modulo


def test_baixar_audio_devolve_arquivo_e_dados(tmp_path, monkeypatch):
    instalar_ytdlp_falso(monkeypatch)
    b = youtube.baixar_audio(LINK, tmp_path / "pasta")
    assert b.arquivo.exists() and b.titulo == "Meu vídeo" and b.canal == "Eu" and b.duracao_s == 61 and b.id == "abc"


def test_baixar_audio_pede_so_o_video_do_link_e_so_o_audio(tmp_path, monkeypatch):
    modulo = instalar_ytdlp_falso(monkeypatch)
    guardado = {}
    original = modulo.YoutubeDL.__init__

    def espiao(self, opcoes):
        guardado.update(opcoes)
        original(self, opcoes)

    modulo.YoutubeDL.__init__ = espiao
    youtube.baixar_audio(LINK, tmp_path)
    assert guardado["noplaylist"] is True and guardado["format"].startswith("bestaudio")


def test_playlist_e_recusada_com_instrucao(tmp_path, monkeypatch):
    instalar_ytdlp_falso(monkeypatch, info={"_type": "playlist", "id": "p", "entries": []})
    with pytest.raises(youtube.ErroDownload, match="playlist"):
        youtube.baixar_audio("https://www.youtube.com/playlist?list=1", tmp_path)


def test_erro_do_ytdlp_vira_erro_com_mensagem_clara(tmp_path, monkeypatch):
    instalar_ytdlp_falso(monkeypatch, erro="ERROR: Sign in to confirm you’re not a bot")
    with pytest.raises(youtube.ErroDownload, match="anti-robô"):
        youtube.baixar_audio(LINK, tmp_path)


def test_sem_o_extra_instalado_explica_como_instalar(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "disponivel", lambda: False)
    with pytest.raises(youtube.ErroDownload, match=r"transcritor\[youtube\]"):
        youtube.baixar_audio(LINK, tmp_path)


def test_texto_que_nao_e_link_e_recusado(tmp_path):
    with pytest.raises(youtube.ErroDownload, match="não parece um link"):
        youtube.baixar_audio("audio.ogg", tmp_path)


# ---------- biblioteca ----------

def test_transcrever_url_baixa_transcreve_e_apaga_o_audio(monkeypatch):
    baixados = []

    def baixar(url, pasta):
        b = baixar_de_mentira(url, pasta)
        baixados.append(b.arquivo)
        return b

    monkeypatch.setattr(youtube, "baixar_audio", baixar)
    etapas = []
    t = api.transcrever_url(LINK, motor=MotorFalso(), ao_etapa=lambda e, d: etapas.append((e, d)), falantes=True)
    assert t.arquivo == "Como criar uma IA v2 0 [5Pr1kNiDwAE]"
    assert t.origem["url"] == LINK and t.origem["canal"] == "Canal X"
    assert t.texto_simples == "Olá, mundo." and t.falante is None
    assert etapas == [("baixando", LINK), ("transcrevendo", "Como criar uma IA v2.0")]
    assert not baixados[0].exists()   # a pasta temporária some depois


def test_transcrever_aceita_o_link_direto(monkeypatch):
    monkeypatch.setattr(youtube, "baixar_audio", baixar_de_mentira)
    t = api.transcrever(LINK, motor=MotorFalso())
    assert t.origem["url"] == LINK


def test_origem_aparece_no_markdown_e_sobrevive_ao_json():
    t = Transcricao(arquivo="x [abc]", duracao_s=5, modelo="m", idioma="pt", origem={"url": LINK, "titulo": "Meu vídeo", "canal": "Eu"},
                    segmentos=[{"inicio": 0.0, "fim": 1.0, "texto": "oi"}])
    md = exportar.gerar(t, "md")
    assert f"[Meu vídeo]({LINK})" in md and "Canal: Eu" in md
    assert Transcricao.de_dict(t.para_dict()).origem["titulo"] == "Meu vídeo"
    assert "Fonte" not in exportar.gerar(Transcricao(arquivo="a", duracao_s=1, modelo="m", idioma="pt"), "md")


# ---------- linha de comando ----------

def test_cli_com_link_sem_o_extra_explica(monkeypatch):
    monkeypatch.setattr(youtube, "disponivel", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["transcrever", LINK])
    assert "transcritor[youtube]" in str(exc.value)


def preparar_cli(monkeypatch, ordem):
    monkeypatch.setattr(youtube, "disponivel", lambda: True)
    monkeypatch.setattr(cli, "Motor", lambda *a, **k: MotorFalso(ordem))

    def falso(url, **kw):
        return api.transcrever_url(url, **kw)

    monkeypatch.setattr(youtube, "baixar_audio", baixar_de_mentira)
    monkeypatch.setattr(cli, "transcrever_url", falso)


def test_cli_transcreve_link_grava_na_pasta_e_indexa(tmp_path, monkeypatch, capsys):
    preparar_cli(monkeypatch, [])
    cli.main(["transcrever", LINK, "--saida", str(tmp_path / "saida")])
    saida = capsys.readouterr().out
    assert "baixando o áudio de" in saida and "Pronto." in saida
    assert (tmp_path / "saida" / "Como criar uma IA v2 0 [5Pr1kNiDwAE].json").exists()
    assert busca.buscar("mundo")[0]["arquivo"] == "Como criar uma IA v2 0 [5Pr1kNiDwAE]"


def test_cli_sem_saida_usa_a_pasta_atual_para_links(tmp_path, monkeypatch):
    preparar_cli(monkeypatch, [])
    cli.main(["transcrever", LINK])
    assert (tmp_path / "transcricoes" / "Como criar uma IA v2 0 [5Pr1kNiDwAE].txt").exists()


def test_cli_link_que_falha_nao_derruba_os_outros(tmp_path, monkeypatch, capsys):
    ordem = []
    preparar_cli(monkeypatch, ordem)
    ruim = "https://www.youtube.com/watch?v=ruim"

    def baixar(url, pasta):
        if "ruim" in url:
            raise youtube.ErroDownload("O YouTube pediu uma verificação anti-robô")
        return baixar_de_mentira(url, pasta)

    monkeypatch.setattr(youtube, "baixar_audio", baixar)
    with pytest.raises(SystemExit) as exc:
        cli.main(["transcrever", ruim, LINK, "--saida", str(tmp_path / "s")])
    assert "1 link(s) não foram transcritos" in str(exc.value)
    assert "anti-robô" in capsys.readouterr().err
    assert (tmp_path / "s" / "Como criar uma IA v2 0 [5Pr1kNiDwAE].json").exists()


def test_cli_todos_os_links_falhando_diz_que_nada_foi_transcrito(tmp_path, monkeypatch):
    preparar_cli(monkeypatch, [])
    monkeypatch.setattr(youtube, "baixar_audio", lambda u, p: (_ for _ in ()).throw(youtube.ErroDownload("sem internet")))
    with pytest.raises(SystemExit) as exc:
        cli.main(["transcrever", LINK, "--saida", str(tmp_path / "s")])
    assert "Nenhum item foi transcrito" in str(exc.value)


def test_cli_resumir_roda_depois_de_liberar_o_whisper_e_so_com_o_que_acabou_de_sair(tmp_path, monkeypatch):
    ordem = []
    preparar_cli(monkeypatch, ordem)
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "antigo.json").write_text('{"arquivo": "antigo.ogg", "segmentos": []}', encoding="utf-8")
    chamadas = {}

    def resumo_falso(pasta, **kw):
        ordem.append("resumiu")
        chamadas.update(kw)
        return Path(pasta) / "resumo"

    monkeypatch.setattr("transcritor.resumo.resumir_pasta", resumo_falso)
    cli.main(["transcrever", LINK, "--saida", str(tmp_path / "s"), "--resumir"])
    assert ordem == ["descarregou", "resumiu"]
    assert [p.name for p in chamadas["somente"]] == ["Como criar uma IA v2 0 [5Pr1kNiDwAE].json"]
    assert "Como criar uma IA v2.0" in chamadas["contexto"] and "vídeo" in chamadas["contexto"]


def test_cli_resumo_que_falha_mantem_as_transcricoes(tmp_path, monkeypatch):
    preparar_cli(monkeypatch, [])

    def quebra(*a, **k):
        raise RuntimeError("O Ollama não responde")

    monkeypatch.setattr("transcritor.resumo.resumir_pasta", quebra)
    with pytest.raises(SystemExit) as exc:
        cli.main(["transcrever", LINK, "--saida", str(tmp_path / "s"), "--resumir"])
    assert "transcrições estão salvas" in str(exc.value) and "Ollama" in str(exc.value)
    assert list((tmp_path / "s").glob("*.json"))


# ---------- resumo de vídeos ----------

def test_id_curto_usa_o_id_do_video():
    assert resumir._id_curto("Título longo do vídeo [5Pr1kNiDwAE]") == "5Pr1kNiDwAE"
    assert resumir._id_curto("WhatsApp Ptt 2026-10-15 at 11.24.16.ogg") == "11.24.16"


def test_contexto_de_videos_cita_titulo_e_canal():
    um = resumir.contexto_de_videos([{"url": LINK, "titulo": "Meu vídeo", "canal": "Eu"}])
    assert "um vídeo" in um and "Meu vídeo" in um and "(Eu)" in um and "Não é uma conversa" in um
    assert "vídeos" in resumir.contexto_de_videos([{"url": LINK, "titulo": "A", "canal": ""}, {"url": LINK + "2", "titulo": "B", "canal": ""}])


def test_carregar_transcricoes_pode_limitar_a_alguns_arquivos(tmp_path):
    for nome in ("a", "b"):
        (tmp_path / f"{nome}.json").write_text(f'{{"arquivo": "{nome}.ogg", "segmentos": []}}', encoding="utf-8")
    assert [t["arquivo"] for t in resumir.carregar_transcricoes(tmp_path)] == ["a.ogg", "b.ogg"]
    assert [t["arquivo"] for t in resumir.carregar_transcricoes(tmp_path, somente=[tmp_path / "b.json"])] == ["b.ogg"]
