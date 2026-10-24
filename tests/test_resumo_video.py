"""Testes do modo vídeo do resumo e da divisão de textos longos, sem Ollama de verdade."""
import json

import pytest

from transcritor.resumo import resumir, video


class LLMFalso:
    """Responde uma parte de cada vez e, quando pedem para juntar os resumos, devolve um resumo geral."""

    def __init__(self, partes=None, juncao=None):
        self.partes = list(partes or [])
        self.juncao = juncao
        self.prompts = []
        self.url = "http://falso"

    def gerar_json(self, sistema, prompt):
        self.prompts.append(prompt)
        if "Junte tudo" in prompt:
            if self.juncao is None:
                raise RuntimeError("falhou")
            return self.juncao
        return self.partes.pop(0) if self.partes else {}

    def disponivel(self, timeout=5):
        return True

    def descarregar(self):
        pass


def transcricao(n_segmentos=40, tamanho=100, **extra):
    segs = [{"inicio": i * 10.0, "fim": i * 10.0 + 9, "texto": f"trecho {i} " + "x" * tamanho} for i in range(n_segmentos)]
    return {"arquivo": "Meu vídeo [abc12345678]", "duracao_s": n_segmentos * 10.0, "segmentos": segs,
            "origem": {"url": "https://exemplo.com/v", "titulo": "Meu vídeo", "canal": "Canal X"}, **extra}


# ---------- dividir ----------

def test_partes_respeitam_o_limite_e_nao_perdem_trechos():
    t = transcricao(n_segmentos=40, tamanho=100)
    partes = video.dividir_em_partes(t, limite=1000)
    assert len(partes) > 3 and all(len(p) <= 1000 + 130 for p in partes)
    juntas = "\n".join(partes)
    assert all(f"trecho {i} " in juntas for i in range(40))
    assert partes[0].startswith("[00:00:00] trecho 0") and "[00:00:10]" in partes[0]


def test_video_curto_vira_uma_parte_so():
    assert len(video.dividir_em_partes(transcricao(n_segmentos=3))) == 1


def test_audio_longo_de_conversa_tambem_e_dividido_em_blocos():
    t = {"arquivo": "WhatsApp Ptt 2026-10-15 at 11.24.16.ogg", "falante": {"nome": "Ana"},
         "segmentos": [{"inicio": i, "fim": i + 1, "texto": f"fala {i} " + "y" * 200} for i in range(60)]}
    blocos = resumir.dividir_em_blocos([t], limite=3000)
    assert len(blocos) > 3 and all(len(b) <= 3000 for b in blocos)
    assert all(b.startswith("===== 11.24.16 · Ana =====") for b in blocos)
    assert all(f"fala {i} " in "\n".join(blocos) for i in range(60))


def test_audios_curtos_continuam_juntos_no_mesmo_bloco():
    curtos = [{"arquivo": f"a{i}.ogg", "segmentos": [{"inicio": 0, "fim": 1, "texto": "oi"}]} for i in range(3)]
    assert len(resumir.dividir_em_blocos(curtos)) == 1


# ---------- unir ----------

def test_unir_partes_tira_repeticoes_valida_horario_e_junta_ferramentas():
    unido = video.unir_partes([
        {"resumo": "Parte um.", "passos": [{"texto": "Abra o ChatGPT e crie um projeto", "minuto": "00:01:00"}, "Anexe a foto"],
         "pontos": ["Use retrato, não paisagem"], "ferramentas": [{"nome": "ChatGPT", "para_que": ""}, "Sora"]},
        {"resumo": "Parte dois.", "passos": [{"texto": "Abra o ChatGPT e crie um projeto novo", "minuto": "00:05:00"},
                                             {"texto": "Gere o vídeo", "minuto": "5 minutos"}],
         "pontos": ["use retrato, não paisagem", "Salve o prompt"], "ferramentas": [{"nome": "chatgpt", "para_que": "gera a imagem"}, {"nome": ""}, 7]},
    ])
    assert [p["texto"] for p in unido["passos"]] == ["Abra o ChatGPT e crie um projeto", "Anexe a foto", "Gere o vídeo"]
    assert [p["minuto"] for p in unido["passos"]] == ["00:01:00", "", ""]   # horário fora do formato é descartado
    assert unido["pontos"] == ["Use retrato, não paisagem", "Salve o prompt"]
    assert unido["ferramentas"] == [{"nome": "ChatGPT", "para_que": "gera a imagem"}, {"nome": "Sora", "para_que": ""}]
    assert unido["resumos_parciais"] == ["Parte um.", "Parte dois."]


@pytest.mark.parametrize("a, b, igual", [
    ("Nano Banana Pro", "NanoBanana Pro", True), ("Grok", "Grock", True), ("ChatGPT", "chatgpt", True),
    ("Sora 2", "Veo 3", False), ("Kling", "Flow", False), ("GPT", "Grok", False), ("Hailuo", "Hailu", True),
])
def test_nomes_de_ferramenta_parecidos_sao_a_mesma_ferramenta(a, b, igual):
    assert video._mesmo_nome(a, b) is igual


def test_ferramenta_com_nome_escrito_de_dois_jeitos_aparece_uma_vez():
    unido = video.unir_partes([{"ferramentas": [{"nome": "Grok", "para_que": "criar vídeos"}]}, {"ferramentas": [{"nome": "Grock", "para_que": ""}]}])
    assert unido["ferramentas"] == [{"nome": "Grok", "para_que": "criar vídeos"}]


def test_unir_partes_com_respostas_estranhas_do_modelo_nao_quebra():
    unido = video.unir_partes([{}, {"passos": None, "pontos": "texto solto", "ferramentas": [None, []]}, {"resumo": None}])
    assert unido["passos"] == [] and unido["ferramentas"] == [] and unido["resumos_parciais"] == []


def test_pontos_principais_tem_limite():
    muitos = [f"alfa{i} bravo{i} cobre{i} delta{i}" for i in range(20)]   # nenhuma palavra em comum: nada é "parecido"
    assert len(video.unir_partes([{"pontos": muitos}])["pontos"]) == video.MAX_PONTOS


# ---------- resumir um vídeo ----------

def test_video_em_varias_partes_pede_a_juncao_dos_resumos():
    llm = LLMFalso(partes=[{"resumo": "Começo."}, {"resumo": "Meio."}, {"resumo": "Fim."}], juncao={"resumo": "Resumo geral."})
    t = transcricao(n_segmentos=30, tamanho=600)
    v = video.resumir_video(t, llm)
    partes = video.dividir_em_partes(t)
    assert len(partes) == 3 and v["partes"] == 3 and v["resumo"] == "Resumo geral."
    assert "Parte 1 de 3" in llm.prompts[0] and "Meu vídeo" in llm.prompts[0] and "Canal X" in llm.prompts[0]
    assert "1. Começo." in llm.prompts[-1] and "3. Fim." in llm.prompts[-1]
    assert v["titulo"] == "Meu vídeo" and v["url"] == "https://exemplo.com/v"


def test_se_a_juncao_falhar_o_resumo_das_partes_serve():
    llm = LLMFalso(partes=[{"resumo": "Começo."}, {"resumo": "Fim."}], juncao=None)
    v = video.resumir_video(transcricao(n_segmentos=20, tamanho=500), llm)
    assert v["resumo"] == "Começo. Fim."


def test_video_de_uma_parte_nao_gasta_chamada_extra():
    llm = LLMFalso(partes=[{"resumo": "Tudo.", "passos": [{"texto": "Faça isto", "minuto": "00:00:05"}]}])
    v = video.resumir_video(transcricao(n_segmentos=3), llm)
    assert len(llm.prompts) == 1 and v["resumo"] == "Tudo." and v["passos"][0]["minuto"] == "00:00:05"


def test_progresso_conta_as_partes_de_todos_os_videos():
    visto = []
    llm = LLMFalso()
    video.resumir_videos([transcricao(n_segmentos=3), transcricao(n_segmentos=3)], llm, progresso=lambda i, n: visto.append((i, n)))
    assert visto == [(1, 2), (2, 2)]


# ---------- markdown ----------

def exemplo():
    return {"modo": "video", "audios": 1, "blocos": 1, "videos": [{
        "titulo": "Meu vídeo", "canal": "Canal X", "url": "https://exemplo.com/v", "duracao_s": 1632, "partes": 1,
        "resumo": "Ensina a criar uma imagem.",
        "passos": [{"texto": "Abra o site", "minuto": "00:01:05"}, {"texto": "Gere a imagem", "minuto": ""}],
        "pontos": ["Use retrato"], "ferramentas": [{"nome": "ChatGPT", "para_que": "gera a imagem"}, {"nome": "Sora", "para_que": ""}]}]}


def test_markdown_do_video_tem_so_as_secoes_pedidas():
    md = video.para_markdown_video(exemplo())
    assert md.startswith("# Resumo do vídeo")
    assert "[Meu vídeo](https://exemplo.com/v) · canal Canal X · 27:12" in md
    for secao in ("## Em resumo", "## Passo a passo", "## Pontos principais", "## Ferramentas citadas"):
        assert secao in md
    assert "1. Abra o site _(01:05)_" in md and "2. Gere a imagem" in md
    assert "- **ChatGPT**: gera a imagem" in md and "- **Sora**" in md
    assert "Pessoas" not in md and "mermaid" not in md and "Tarefas" not in md


def test_markdown_com_varios_videos_separa_por_titulo():
    r = exemplo()
    r["videos"].append({**r["videos"][0], "titulo": "Outro", "url": ""})
    md = video.para_markdown_video(r)
    assert md.startswith("# Resumo dos vídeos") and "## Meu vídeo" in md and "## Outro" in md and "### Passo a passo" in md


def test_markdown_de_video_sem_passos_diz_isso():
    r = exemplo()
    r["videos"][0].update(passos=[], pontos=[], ferramentas=[])
    md = video.para_markdown_video(r)
    assert "o vídeo não traz passos" in md and "(nenhuma)" in md


# ---------- resumir_pasta: escolha do modo ----------

@pytest.fixture
def pasta_com(tmp_path, monkeypatch):
    llm = LLMFalso(partes=[{"resumo": "Tudo.", "passos": [{"texto": "Faça isto", "minuto": ""}]}])
    monkeypatch.setattr(resumir, "Ollama", lambda modelo, url: llm)

    def criar(origem):
        dados = transcricao(n_segmentos=3)
        if not origem:
            dados.pop("origem")
        (tmp_path / "a.json").write_text(json.dumps(dados), encoding="utf-8")
        return tmp_path

    return criar


def test_modo_automatico_usa_video_quando_tudo_veio_de_link(pasta_com):
    pasta = pasta_com(origem=True)
    (pasta / "resumo").mkdir()
    (pasta / "resumo" / "fluxo.mmd").write_text("sobra", encoding="utf-8")
    saida = resumir.resumir_pasta(pasta)
    assert (saida / "resumo.md").read_text(encoding="utf-8").startswith("# Resumo do vídeo")
    assert json.loads((saida / "resumo.json").read_text(encoding="utf-8"))["modo"] == "video"
    assert not (saida / "fluxo.mmd").exists()   # o fluxograma de uma rodada antiga não fica para confundir


def test_sem_origem_o_modo_automatico_continua_sendo_conversa(pasta_com):
    saida = resumir.resumir_pasta(pasta_com(origem=False))
    assert "# Resumo da conversa" in (saida / "resumo.md").read_text(encoding="utf-8")
    assert (saida / "fluxo.mmd").exists()


def test_modo_conversa_pode_ser_forcado_mesmo_com_link(pasta_com):
    saida = resumir.resumir_pasta(pasta_com(origem=True), modo="conversa")
    assert "# Resumo da conversa" in (saida / "resumo.md").read_text(encoding="utf-8")


def test_modo_desconhecido_explica_as_opcoes(pasta_com):
    with pytest.raises(ValueError, match="auto, conversa ou video"):
        resumir.resumir_pasta(pasta_com(origem=True), modo="poema")
