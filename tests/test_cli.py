"""Testes do comando `transcritor` (sem modelo)."""
import pytest

from transcritor import busca
from transcritor.cli import main
from transcritor.transcricao import Transcricao


@pytest.fixture(autouse=True)
def home_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRITOR_HOME", str(tmp_path / "home"))


def test_glossario_add_listar_remover(capsys):
    main(["glossario", "add", "Lamine Yamal"])
    main(["glossario", "add", "lamine yamal"])
    main(["glossario", "listar"])
    saida = capsys.readouterr().out
    assert "adicionado: Lamine Yamal" in saida and "já existia: lamine yamal" in saida
    assert "Davi" in saida and "Lamine Yamal" in saida
    main(["glossario", "remover", "Lamine Yamal"])
    assert "removido: Lamine Yamal" in capsys.readouterr().out


def test_glossario_add_sem_termo_explica(capsys):
    with pytest.raises(SystemExit):
        main(["glossario", "add"])
    assert "informe" in capsys.readouterr().err


def test_buscar_mostra_arquivo_horario_e_texto(capsys):
    busca.indexar(Transcricao(arquivo="x.ogg", duracao_s=5, modelo="m", idioma="pt", sha1="1",
                              segmentos=[{"inicio": 65.0, "fim": 70.0, "texto": "O cartão SD corrompeu."}]))
    main(["buscar", "sd", "corrompeu"])
    saida = capsys.readouterr().out
    assert "x.ogg [00:01:05]" in saida and "O cartão SD corrompeu." in saida
    main(["buscar", "inexistente"])
    assert "Nada encontrado." in capsys.readouterr().out


def test_transcrever_caminho_que_nao_existe_da_erro_claro(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["transcrever", str(tmp_path / "nao_existe")])
    assert "Não encontrei" in str(exc.value)


def test_transcrever_formato_invalido_lista_as_opcoes(tmp_path):
    (tmp_path / "a.ogg").write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        main(["transcrever", str(tmp_path), "--formatos", "pdf"])
    assert "txt, md, json, srt, vtt" in str(exc.value)
