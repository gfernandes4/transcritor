"""Testes da identificação de voz com vetores de mentira (o modelo de verdade só roda no teste lento)."""
import os
from pathlib import Path

import numpy as np
import pytest

from transcritor.cli import main
from transcritor.vozes import identificar, perfis
from transcritor.vozes.embedding import ErroVoz, Extrator


@pytest.fixture(autouse=True)
def home_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRITOR_HOME", str(tmp_path / "home"))


def unitario(*valores):
    v = np.array(valores, dtype=np.float32)
    return v / np.linalg.norm(v)


class ExtratorFalso:
    """Devolve o vetor combinado com o nome do arquivo."""
    nome = "falso"

    def __init__(self, vetores):
        self.vetores = vetores

    def do_arquivo(self, caminho):
        return self.vetores[Path(caminho).name]


def criar_audios(pasta, nomes):
    for i, nome in enumerate(nomes):
        (pasta / nome).write_bytes(bytes([i]) * 10)  # conteúdo diferente = sha1 diferente
    return [pasta / n for n in nomes]


ANA, BRUNO = unitario(1, 0.1, 0), unitario(0.1, 1, 0)


def test_decidir_aceita_quando_passa_do_limiar_e_da_margem():
    r = identificar.decidir(unitario(1, 0.15, 0), {"Ana": ANA, "Bruno": BRUNO}, limiar=0.7, margem=0.1)
    assert r.nome == "Ana" and r.melhor == "Ana" and r.confianca > 0.9


def test_decidir_barra_voz_de_fora_e_diz_a_mais_parecida():
    r = identificar.decidir(unitario(0, 0, 1), {"Ana": ANA, "Bruno": BRUNO}, limiar=0.7, margem=0.0)
    assert r.nome is None and r.melhor in ("Ana", "Bruno")


def test_decidir_barra_quando_as_duas_pessoas_empatam():
    r = identificar.decidir(unitario(1, 1, 0), {"Ana": ANA, "Bruno": BRUNO}, limiar=0.5, margem=0.1)
    assert r.nome is None and r.margem < 0.1


def test_decidir_sem_perfis_nao_inventa_nome():
    assert identificar.decidir(ANA, {}, 0.5, 0.0).nome is None


def amostras():
    rotulos, vetores = {}, {}
    for i in range(4):
        rotulos[f"d{i}.ogg"] = "Ana"
        vetores[f"d{i}.ogg"] = unitario(1, 0.1 + 0.02 * i, 0.03 * i)
        rotulos[f"g{i}.ogg"] = "Bruno"
        vetores[f"g{i}.ogg"] = unitario(0.1 + 0.02 * i, 1, 0.03 * i)
    return vetores, rotulos


def test_leave_one_out_nao_usa_o_proprio_audio():
    vetores, rotulos = amostras()
    resultados = identificar.avaliar_sem_um(vetores, rotulos)
    assert len(resultados) == 8 and all(r["melhor"] == r["verdadeiro"] for r in resultados)
    # uma pessoa com um único áudio não pode ser testada: não há outro para cadastrar
    resultados = identificar.avaliar_sem_um({**vetores, "n.ogg": unitario(0, 0, 1)}, {**rotulos, "n.ogg": "Novo"})
    assert "n.ogg" not in [r["arquivo"] for r in resultados]


def test_calibrar_usa_vozes_de_fora_para_o_limiar():
    vetores, rotulos = amostras()
    resultados = identificar.avaliar_sem_um(vetores, rotulos)
    pior = min(r["score_certo"] for r in resultados)
    cal = identificar.calibrar(resultados, [0.3, 0.5])
    assert cal["validado"] and 0.5 < cal["limiar"] < pior
    assert cal["margem"] == pytest.approx(min(0.15, cal["folga"] / 2), abs=0.001)


def test_calibrar_recusa_quando_voz_de_fora_se_parece_com_o_cadastro():
    vetores, rotulos = amostras()
    resultados = identificar.avaliar_sem_um(vetores, rotulos)
    assert identificar.calibrar(resultados, [1.0]) is None


def test_calibrar_sem_vozes_de_fora_e_provisorio():
    vetores, rotulos = amostras()
    cal = identificar.calibrar(identificar.avaliar_sem_um(vetores, rotulos))
    assert cal["validado"] is False and cal["maior_desconhecido"] is None


def test_calibrar_recusa_quando_alguem_foi_confundido():
    vetores, rotulos = amostras()
    rotulos["d0.ogg"] = "Bruno"  # rótulo errado de propósito
    assert identificar.calibrar(identificar.avaliar_sem_um(vetores, rotulos)) is None


def test_varrer_e_escolher_nao_aceitam_erro_de_pessoa():
    vetores, rotulos = amostras()
    linhas = identificar.varrer(identificar.avaliar_sem_um(vetores, rotulos))
    escolha = identificar.escolher(linhas)
    assert escolha["erros"] == 0 and escolha["acertos"] == 8


def test_configuracao_salva_e_le(tmp_path):
    assert identificar.configuracao()["limiar"] == identificar.LIMIAR_PADRAO
    identificar.salvar_configuracao("campp", 0.7173, 0.0183)
    cfg = identificar.configuracao()
    assert cfg == {"modelo": "campp", "limiar": 0.717, "margem": 0.018}


def test_cadastro_guarda_perfil_e_ignora_arquivo_repetido(tmp_path):
    arquivos = criar_audios(tmp_path, ["a.ogg", "b.ogg"])
    ext = ExtratorFalso({"a.ogg": ANA, "b.ogg": unitario(1, 0.2, 0)})
    assert len(perfis.cadastrar("Ana", arquivos, ext)) == 2
    assert perfis.cadastrar("Ana", arquivos, ext) == []
    assert perfis.listar() == [{"nome": "Ana", "modelo": "falso", "amostras": 2}]
    perfil = perfis.perfis("falso")["Ana"]
    assert np.linalg.norm(perfil) == pytest.approx(1.0, abs=1e-5)
    assert perfis.remover("ana") == 2 and perfis.listar() == []


def test_cadastro_com_nome_vazio_da_erro(tmp_path):
    with pytest.raises(ValueError):
        perfis.cadastrar("   ", [], ExtratorFalso({}))


def test_comandos_sem_o_modelo_baixado_explicam_o_que_fazer(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["vozes", "testar", str(tmp_path / "x.ogg")])
    assert "baixar-modelo" in str(exc.value)


def test_extrator_sem_modelo_levanta_erro_claro():
    with pytest.raises(ErroVoz, match="baixar-modelo"):
        Extrator("campp")


def test_extrator_com_nome_desconhecido_lista_as_opcoes():
    with pytest.raises(ErroVoz, match="campp"):
        Extrator("inexistente")


def test_vozes_listar_sem_cadastro_explica(capsys):
    main(["vozes", "listar"])
    saida = capsys.readouterr().out
    assert "Nenhuma voz cadastrada" in saida and "Em uso: modelo campp" in saida


@pytest.mark.lento
@pytest.mark.skipif(os.environ.get("TRANSCRITOR_TESTES_LENTOS") != "1", reason="usa o modelo de verdade")
def test_modelo_real_gera_vetor_normalizado(monkeypatch):
    monkeypatch.setenv("TRANSCRITOR_HOME", str(Path.home() / ".transcritor"))  # onde o modelo foi baixado
    extrator = Extrator("campp")
    ruido = np.random.default_rng(0).normal(0, 0.1, 16_000 * 3).astype(np.float32)
    v = extrator.embedding(ruido)
    assert v.ndim == 1 and np.linalg.norm(v) == pytest.approx(1.0, abs=1e-4)
