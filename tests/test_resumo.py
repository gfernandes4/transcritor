"""Testes do resumo, com um LLM de mentira (sem Ollama)."""
import json

from transcritor.resumo import mermaid, resumir as r
from transcritor.resumo.llm import extrair_json


def audio(arquivo, texto, falante=None):
    return {"arquivo": arquivo, "falante": falante, "segmentos": [{"inicio": 0.0, "fim": 5.0, "texto": texto}]}


class LLMFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.prompts = []

    def gerar_json(self, sistema, prompt):
        self.prompts.append(prompt)
        return self.respostas.pop(0)


def test_extrair_json_aceita_cerca_de_markdown_e_texto_em_volta():
    assert extrair_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extrair_json('Claro! {"a": 2} Espero ter ajudado.') == {"a": 2}


def test_id_curto_vem_do_horario_no_nome_do_whatsapp():
    assert r._id_curto("WhatsApp Ptt 2026-10-15 at 11.24.16.ogg") == "11.24.16"
    assert r._id_curto("reuniao.mp3") == "reuniao"


def test_blocos_respeitam_o_limite_e_nao_cortam_audio_no_meio():
    audios = [audio(f"a{i} 10.00.0{i}.ogg", "x" * 400) for i in range(6)]
    blocos = r.dividir_em_blocos(audios, limite=1000)
    assert len(blocos) == 3 and all(b.count("=====") // 2 == 2 for b in blocos)
    assert len(r.dividir_em_blocos([audio("grande 10.00.00.ogg", "y" * 5000)], limite=1000)) == 1


def test_unir_remove_itens_repetidos_e_soma_as_fontes():
    p1 = {"definido": [{"texto": "Não é lote.", "fontes": ["11.30.08"]}], "em_aberto": ["Foi a versão?"]}
    p2 = {"definido": [{"texto": "não é lote", "fontes": ["11.49.54"]}], "tarefas": [{"texto": "Pedir dados ao Caio", "responsavel": "Bruno", "fontes": []}]}
    final = r.unir([p1, p2])
    assert len(final["definido"]) == 1 and final["definido"][0]["fontes"] == ["11.30.08", "11.49.54"]
    assert final["em_aberto"][0]["texto"] == "Foi a versão?"
    assert final["tarefas"][0]["responsavel"] == "Bruno"


def test_unir_trata_responsavel_vazio_e_junta_itens_quase_iguais():
    p1 = {"em_aberto": ["Não sabemos se as falhas são causadas pelo SD ou pelo software"],
          "tarefas": [{"texto": "Falar com o Elisa e o Davi", "responsavel": "vazio", "fontes": ["18.13.19"]}]}
    p2 = {"em_aberto": ["Não se sabe se as falhas são causadas pelo SD ou pelo software"],
          "tarefas": [{"texto": "Falar com o Elisa e com o Davi", "responsavel": "Bruno", "fontes": ["18.23.05"]}]}
    final = r.unir([p1, p2])
    assert len(final["em_aberto"]) == 1
    assert len(final["tarefas"]) == 1
    assert final["tarefas"][0]["responsavel"] == "Bruno"
    assert final["tarefas"][0]["fontes"] == ["18.13.19", "18.23.05"]


def test_hipotese_dita_como_definida_vai_para_em_aberto():
    final = r.unir([{"definido": ["Lote não é a causa.", "O SD pode ser o responsável pelo problema.", "Talvez seja a atualização."]}])
    assert [d["texto"] for d in final["definido"]] == ["Lote não é a causa."]
    assert len(final["em_aberto"]) == 2


def test_responsavel_vazio_aparece_como_traco_no_markdown():
    final = r.unir([{"tarefas": [{"texto": "Anotar casos futuros", "responsavel": "vazio"}]}])
    final.update(audios=1, blocos=1)
    assert "| Anotar casos futuros | — |" in r.para_markdown(final)


def test_fluxo_dos_blocos_fica_encadeado_e_limitado():
    muitos = {"fluxo": [{"id": f"p{i}", "texto": f"passo {i}"} for i in range(20)]}
    final = r.unir([muitos, {"fluxo": [{"id": "p1", "texto": "outro bloco"}]}])
    ids = [p["id"] for p in final["fluxo"]]
    assert len([i for i in ids if i.startswith("b1_")]) == r.MAX_PASSOS_DO_FLUXO_POR_BLOCO
    ultimo_b1 = next(p for p in final["fluxo"] if p["id"] == f"b1_p{r.MAX_PASSOS_DO_FLUXO_POR_BLOCO - 1}")
    assert "b2_p1" in ultimo_b1["depois"]


def test_fluxograma_padrao_nao_inclui_as_listas():
    resultado = r.unir([{"definido": ["Fato"], "fluxo": [{"id": "p1", "texto": "Início"}]}])
    assert "subgraph" not in r.mermaid_do_resumo(resultado)
    assert "subgraph def" in r.mermaid_do_resumo(resultado, incluir_listas=True)


def test_unir_prefixa_ids_do_fluxo_por_bloco():
    p = {"fluxo": [{"id": "p1", "texto": "Problema", "depois": ["p2"]}, {"id": "p2", "texto": "Hipóteses", "depois": []}]}
    final = r.unir([p, p])
    assert [x["id"] for x in final["fluxo"]] == ["b1_p1", "b1_p2", "b2_p1", "b2_p2"]
    assert final["fluxo"][0]["depois"] == ["b1_p2"]


def test_resumir_chama_o_llm_uma_vez_por_bloco_e_leva_o_contexto():
    audios = [audio(f"a 10.00.0{i}.ogg", "z" * 7000) for i in range(2)]
    llm = LLMFalso([{"definido": ["A"]}, {"definido": ["B"]}])
    resultado = r.resumir(audios, llm, contexto="Conversa sobre o SD")
    assert len(llm.prompts) == 2 and "Conversa sobre o SD" in llm.prompts[0]
    assert resultado["blocos"] == 2 and [d["texto"] for d in resultado["definido"]] == ["A", "B"]


def test_resumir_sem_transcricao_explica_o_problema():
    import pytest

    with pytest.raises(ValueError):
        r.resumir([], LLMFalso([]))


def test_mermaid_descarta_ligacao_para_passo_inexistente_e_limpa_aspas():
    passos = [{"id": "a", "texto": 'Disse "oi" [teste]', "depois": ["b", "fantasma"]}, {"id": "b", "texto": "Fim", "depois": []}]
    saida = mermaid.renderizar(passos, ["Fato"], ["Dúvida"], ["Fazer X"])
    assert saida.startswith("flowchart TD")
    assert "n1 --> n2" in saida and "fantasma" not in saida
    assert '"' not in saida.split("n1[")[1].split("]")[0].strip('"')[1:-1]
    assert "subgraph def" in saida and "subgraph abe" in saida and "subgraph tar" in saida


def test_mermaid_sem_ligacoes_encadeia_na_ordem():
    passos = [{"id": "a", "texto": "Um"}, {"id": "b", "texto": "Dois"}, {"id": "c", "texto": "Três"}]
    saida = mermaid.renderizar(passos, [], [], [])
    assert "n1 --> n2" in saida and "n2 --> n3" in saida


def test_markdown_tem_as_secoes_e_o_bloco_mermaid():
    resultado = r.unir([{"definido": ["Lote descartado"], "em_aberto": ["Causa?"], "tarefas": [{"texto": "Contar SDs", "responsavel": "Bruno"}],
                         "pessoas": [{"nome": "Caio", "papel": "software"}], "fluxo": [{"id": "p1", "texto": "Problema"}]}])
    resultado.update(audios=3, blocos=1)
    md = r.para_markdown(resultado)
    for trecho in ("## O que ficou definido", "## Em aberto", "## Tarefas", "| Contar SDs | Bruno |", "```mermaid", "**Caio**: software"):
        assert trecho in md


def test_resumir_pasta_grava_os_tres_arquivos(tmp_path, monkeypatch):
    for nome in ("a 10.00.01.ogg", "b 10.00.02.ogg"):
        (tmp_path / f"{nome}.json").write_text(json.dumps(audio(nome, "texto de teste")), encoding="utf-8")
    llm = LLMFalso([{"definido": ["Fato"], "fluxo": [{"id": "p1", "texto": "Início"}]}])
    llm.disponivel = lambda: True
    llm.descarregar = lambda: None
    llm.url = "http://falso"
    monkeypatch.setattr(r, "Ollama", lambda *a, **k: llm)
    saida = r.resumir_pasta(tmp_path)
    assert sorted(p.name for p in saida.iterdir()) == ["fluxo.mmd", "resumo.json", "resumo.md"]
    assert "Fato" in (saida / "resumo.md").read_text(encoding="utf-8")
