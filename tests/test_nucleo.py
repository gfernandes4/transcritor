"""Testes do núcleo (sem modelo, rápidos)."""
import json

import pytest

from transcritor import busca, exportar
from transcritor.nucleo import alertas, glossario
from transcritor.nucleo.audio import listar_audios
from transcritor.nucleo.whisper import Parametros
from transcritor.transcricao import Transcricao


@pytest.fixture(autouse=True)
def home_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRITOR_HOME", str(tmp_path / "home"))


def seg(inicio, fim, texto):
    return {"inicio": inicio, "fim": fim, "texto": texto}


def modelo_de_transcricao(**extra):
    base = dict(
        arquivo="a.ogg", duracao_s=12.5, modelo="large-v3", idioma="pt",
        segmentos=[seg(0.0, 3.2, "Opa, fala aí meu."), seg(3.2, 8.0, "O cartão SD corrompeu.")],
        sha1="abc",
    )
    base.update(extra)
    return Transcricao(**base)


# --- alertas -----------------------------------------------------------------


def test_linha_repetida_em_sequencia_e_removida():
    segs = [seg(0, 2, "Isso, dado a data."), seg(2, 4, "Isso, dado a data."), seg(4, 6, "isso dado a data"), seg(6, 8, "Outra coisa.")]
    limpos, avisos = alertas.limpar_e_alertar(segs)
    assert [s["texto"] for s in limpos] == ["Isso, dado a data.", "Outra coisa."]
    assert [a["tipo"] for a in avisos].count("repeticao_removida") == 2


def test_frase_repetida_dentro_do_trecho_vira_uma_vez():
    limpos, avisos = alertas.limpar_e_alertar([seg(0, 5, "muito aceita, muito aceita, muito aceita, muito aceita pelo público")])
    assert limpos[0]["texto"].count("muito aceita") == 1
    assert avisos and avisos[0]["tipo"] == "repeticao_removida"


def test_caracteres_de_outro_alfabeto_geram_alerta():
    _, avisos = alertas.limpar_e_alertar([seg(0, 3, "texto normal Gleich 코 バラ"), seg(3, 6, "tudo certo aqui.")])
    assert [a["tipo"] for a in avisos] == ["caracteres_estranhos"]
    assert avisos[0]["inicio"] == 0


def test_texto_longo_sem_pontuacao_gera_alerta():
    texto = " ".join(f"palavra{i}" for i in range(45))
    _, avisos = alertas.limpar_e_alertar([seg(0, 40, texto)])
    assert any(a["tipo"] == "sem_pontuacao" for a in avisos)


def test_texto_normal_nao_gera_alerta():
    _, avisos = alertas.limpar_e_alertar([seg(0, 5, "Olha só, deixa eu te falar um lance aqui.")])
    assert avisos == []


# --- exportação --------------------------------------------------------------


def test_srt_tem_virgula_nos_milissegundos_e_numeracao():
    srt = exportar.gerar(modelo_de_transcricao(), "srt")
    assert srt.startswith("1\n00:00:00,000 --> 00:00:03,200\nOpa, fala aí meu.")
    assert "2\n00:00:03,200 --> 00:00:08,000" in srt


def test_vtt_tem_cabecalho_e_ponto_nos_milissegundos():
    vtt = exportar.gerar(modelo_de_transcricao(), "vtt")
    assert vtt.startswith("WEBVTT") and "00:00:03.200 --> 00:00:08.000" in vtt


def test_txt_e_md_e_json():
    t = modelo_de_transcricao(falante={"nome": "Ana", "confianca": 0.93}, alertas=[{"tipo": "x", "inicio": 1.0, "detalhe": "d"}])
    assert exportar.gerar(t, "txt").startswith("[00:00:00] Opa, fala aí meu.")
    md = exportar.gerar(t, "md")
    assert "Ana (93%)" in md and "## Alertas" in md
    assert json.loads(exportar.gerar(t, "json"))["segmentos"][1]["texto"] == "O cartão SD corrompeu."


def test_formato_desconhecido_explica_as_opcoes():
    with pytest.raises(ValueError, match="txt, md, json, srt, vtt"):
        exportar.gerar(modelo_de_transcricao(), "pdf")


def test_salvar_grava_um_arquivo_por_formato(tmp_path):
    caminhos = modelo_de_transcricao().salvar(tmp_path / "saida", ["txt", "json"])
    assert sorted(p.name for p in caminhos) == ["a.json", "a.txt"]
    assert Transcricao.de_dict(json.loads(caminhos[1].read_text(encoding="utf-8"))).segmentos[0]["texto"] == "Opa, fala aí meu."


# --- glossário ---------------------------------------------------------------


def test_glossario_comeca_com_os_termos_confirmados():
    termos = glossario.listar()
    for esperado in ("Ana", "Davi", "Caio", "SD", "eMMC", "Ollama"):
        assert esperado in termos


def test_glossario_adicionar_remover_sem_diferenciar_maiusculas():
    assert glossario.adicionar("Fermín") is True
    assert glossario.adicionar("fermín") is False
    assert "Fermín" in glossario.listar()
    assert glossario.remover("FERMÍN") is True
    assert glossario.remover("Fermín") is False


def test_glossario_soma_arquivo_extra_e_termos_avulsos(tmp_path):
    extra = tmp_path / "extra.txt"
    extra.write_text("# comentário\nBetis\n\nSD\n", encoding="utf-8")
    termos = glossario.carregar(arquivo=extra, termos=["Yamal"])
    assert "Betis" in termos and "Yamal" in termos
    assert termos.count("SD") == 1  # não duplica


def test_glossario_sugere_nomes_novos_e_ignora_os_conhecidos():
    textos = ["Eu falei com o Davi e com o Kimmich ontem.", "Depois o Kimmich ligou, mas o Davi não atendeu.", "Só o Raphinha apareceu."]
    sugestoes = dict(glossario.sugerir(textos, minimo=2))
    assert sugestoes == {"Kimmich": 2}  # Davi já está no glossário; Raphinha aparece uma vez


# --- parâmetros do Whisper ---------------------------------------------------


def test_modo_bruto_so_manda_o_basico_ao_whisper():
    assert set(Parametros().para_whisper()) == {"language", "beam_size", "vad_filter"}


def test_modo_melhorado_desliga_contexto_anterior_e_usa_glossario():
    kw = Parametros.melhorado().para_whisper(["Davi", "Elisa"])
    assert kw["condition_on_previous_text"] is False
    assert kw["hotwords"] == "Davi, Elisa"
    assert kw["compression_ratio_threshold"] == 2.4


# --- áudios e busca ----------------------------------------------------------


def test_listar_audios_filtra_extensoes_e_ordena(tmp_path):
    for nome in ("b.ogg", "a.mp3", "nota.txt", "c.OPUS"):
        (tmp_path / nome).write_bytes(b"x")
    assert [p.name for p in listar_audios(tmp_path)] == ["a.mp3", "b.ogg", "c.OPUS"]
    assert [p.name for p in listar_audios(tmp_path / "b.ogg")] == ["b.ogg"]
    with pytest.raises(FileNotFoundError):
        listar_audios(tmp_path / "nao_existe")


def test_busca_acha_sem_diferenciar_acento_e_mostra_o_horario():
    busca.indexar(modelo_de_transcricao(falante={"nome": "Ana", "confianca": 0.9}), "a.json")
    achados = busca.buscar("cartao sd")
    assert len(achados) == 1 and achados[0]["inicio"] == 3.2 and achados[0]["falante"] == "Ana"
    assert busca.buscar("cartão SD", falante="bruno") == []
    assert busca.buscar("   ") == []
    assert busca.buscar('aspas " quebradas') == []  # não quebra a sintaxe do índice


def test_indexar_o_mesmo_audio_substitui_em_vez_de_duplicar():
    busca.indexar(modelo_de_transcricao(), "a.json")
    busca.indexar(modelo_de_transcricao(segmentos=[seg(0, 2, "Texto novo sobre o SD.")]), "a.json")
    assert busca.buscar("corrompeu") == []
    assert len(busca.buscar("novo")) == 1
