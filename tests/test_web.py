"""Testes da interface web, com um executor de mentira (sem Whisper)."""
import io
import time
import zipfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from transcritor.web.app import Fila, criar_app  # noqa: E402


@pytest.fixture(autouse=True)
def home_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRITOR_HOME", str(tmp_path / "home"))


def executor_falso(job):
    job.saida.mkdir(parents=True, exist_ok=True)
    for arquivo in job.arquivos:
        (job.saida / f"{arquivo.stem}.txt").write_text("[00:00:00] texto de teste\n", encoding="utf-8")
        job.feitos += 1


def esperar(cliente, estado, tentativas=50):
    for _ in range(tentativas):
        jobs = cliente.get("/api/fila").json()
        if jobs and jobs[0]["status"] == estado:
            return jobs[0]
        time.sleep(0.05)
    raise AssertionError(f"Não chegou em '{estado}': {jobs}")


def test_envio_vai_para_a_fila_e_vira_zip():
    cliente = TestClient(criar_app(Fila(executar=executor_falso)))
    resp = cliente.post("/enviar", files=[("arquivos", ("a.ogg", b"x", "audio/ogg")), ("arquivos", ("b.mp3", b"y", "audio/mpeg"))],
                        data={"formatos": "txt", "termos": "Yamal\nBetis"})
    assert resp.status_code == 200 and resp.json()["total"] == 2
    job = esperar(cliente, "concluído")
    assert job["feitos"] == 2
    zip_bytes = cliente.get(f"/resultado/{job['id']}")
    assert zip_bytes.status_code == 200
    assert sorted(zipfile.ZipFile(io.BytesIO(zip_bytes.content)).namelist()) == ["a.txt", "b.txt"]


def test_tipo_de_arquivo_nao_suportado_e_recusado():
    cliente = TestClient(criar_app(Fila(executar=executor_falso)))
    resp = cliente.post("/enviar", files=[("arquivos", ("virus.exe", b"x", "application/octet-stream"))])
    assert resp.status_code == 400 and "não suportado" in resp.json()["detail"]


def test_formato_invalido_e_recusado():
    cliente = TestClient(criar_app(Fila(executar=executor_falso)))
    resp = cliente.post("/enviar", files=[("arquivos", ("a.ogg", b"x", "audio/ogg"))], data={"formatos": "pdf"})
    assert resp.status_code == 400


def test_nome_de_arquivo_com_caminho_nao_escapa_da_pasta():
    cliente = TestClient(criar_app(Fila(executar=executor_falso)))
    resp = cliente.post("/enviar", files=[("arquivos", ("../../fora.ogg", b"x", "audio/ogg"))])
    assert resp.status_code == 200 and resp.json()["arquivos"] == ["fora.ogg"]


def test_erro_no_job_aparece_na_fila_sem_derrubar_o_servidor():
    def quebra(job):
        raise RuntimeError("GPU indisponível")

    cliente = TestClient(criar_app(Fila(executar=quebra)))
    cliente.post("/enviar", files=[("arquivos", ("a.ogg", b"x", "audio/ogg"))])
    assert "GPU indisponível" in esperar(cliente, "erro")["erro"]


def test_resultado_antes_de_ficar_pronto_da_404():
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    job = cliente.post("/enviar", files=[("arquivos", ("a.ogg", b"x", "audio/ogg"))]).json()
    assert cliente.get(f"/resultado/{job['id']}").status_code == 404


def test_glossario_pela_interface():
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    assert "Davi" in cliente.get("/api/glossario").json()
    assert cliente.post("/api/glossario", data={"termo": "Fermín"}).json() == {"adicionado": True}
    assert cliente.post("/api/glossario", data={"termo": "fermín"}).json() == {"adicionado": False}
    assert cliente.post("/api/glossario", data={"termo": "  "}).status_code == 400


def test_pagina_inicial_abre():
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    resp = cliente.get("/")
    assert resp.status_code == 200 and "Transcritor" in resp.text


def test_pagina_nao_depende_de_nada_de_fora():
    """Promessa da interface: nenhum script, fonte ou imagem vem da internet."""
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    html = cliente.get("/").text
    assert "http://" not in html and "https://" not in html and "//cdn" not in html
    assert "<script src" not in html and "<link" not in html


def test_cancelar_na_fila_impede_o_inicio_e_mantem_o_servidor_de_pe():
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    job = cliente.post("/enviar", files=[("arquivos", ("a.ogg", b"x", "audio/ogg"))]).json()
    assert cliente.post(f"/api/fila/{job['id']}/cancelar").json()["status"] == "cancelado"
    assert cliente.get(f"/resultado/{job['id']}").status_code == 404   # nada ficou pronto
    assert cliente.post("/api/fila/nao-existe/cancelar").status_code == 404


def test_cancelar_em_andamento_para_depois_do_arquivo_atual_e_entrega_o_que_ficou_pronto():
    fila = Fila(iniciar_worker=False)

    def devagar(job):
        job.saida.mkdir(parents=True, exist_ok=True)
        for arquivo in job.arquivos:
            if job.cancelado:
                break
            (job.saida / f"{arquivo.stem}.txt").write_text("ok", encoding="utf-8")
            job.feitos += 1
            fila.cancelar(job.id)          # o usuário cancela logo depois do primeiro áudio

    fila._executar = devagar
    cliente = TestClient(criar_app(fila))
    resp = cliente.post("/enviar", files=[("arquivos", ("a.ogg", b"x", "audio/ogg")), ("arquivos", ("b.ogg", b"y", "audio/ogg"))])
    fila._rodar(fila._fila.get_nowait())
    job = cliente.get("/api/fila").json()[0]
    assert job["status"] == "cancelado" and job["feitos"] == 1 and job["id"] == resp.json()["id"]
    zip_resp = cliente.get(f"/resultado/{job['id']}")
    assert zip_resp.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(zip_resp.content)).namelist() == ["a.txt"]


def test_previa_mostra_o_comeco_do_texto_com_falante_e_alertas():
    from transcritor.transcricao import Transcricao

    def com_json(job):
        for arquivo in job.arquivos:
            Transcricao(arquivo=arquivo.name, duracao_s=75, modelo="m", idioma="pt", sha1="1", falante={"nome": "Ana", "confianca": 0.9},
                        alertas=[{"tipo": "velocidade", "inicio": 0.0, "detalhe": "x"}],
                        segmentos=[{"inicio": 0.0, "fim": 5.0, "texto": "Texto " * 200}]).salvar(job.saida, ["json"])
            job.feitos += 1

    cliente = TestClient(criar_app(Fila(executar=com_json)))
    job = cliente.post("/enviar", files=[("arquivos", ("a.ogg", b"x", "audio/ogg"))]).json()
    esperar(cliente, "concluído")
    [item] = cliente.get(f"/api/fila/{job['id']}/previa", params={"limite": 50}).json()
    assert item["arquivo"] == "a.ogg" and item["falante"] == "Ana" and item["alertas"] == 1
    assert item["trecho"].endswith("…") and len(item["trecho"]) == 51
    assert cliente.get("/api/fila/nao-existe/previa").status_code == 404


def test_flag_de_falantes_chega_ao_job():
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    arquivos = [("arquivos", ("a.ogg", b"x", "audio/ogg"))]
    assert cliente.post("/enviar", files=arquivos, data={"falantes": "true"}).json()["falantes"] is True
    assert cliente.post("/enviar", files=arquivos).json()["falantes"] is False


def test_remover_termo_do_glossario():
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    cliente.post("/api/glossario", data={"termo": "Fermín"})
    assert cliente.delete("/api/glossario", params={"termo": "fermín"}).json() == {"removido": True}
    assert "Fermín" not in cliente.get("/api/glossario").json()
    assert cliente.delete("/api/glossario", params={"termo": "fermín"}).json() == {"removido": False}


def test_busca_com_filtro_de_falante():
    from transcritor import busca
    from transcritor.transcricao import Transcricao

    for nome, quem in (("d.ogg", "Ana"), ("g.ogg", "Bruno")):
        busca.indexar(Transcricao(arquivo=nome, duracao_s=5, modelo="m", idioma="pt", sha1=nome, falante={"nome": quem, "confianca": 0.9},
                                  segmentos=[{"inicio": 3.0, "fim": 4.0, "texto": "O cartão SD corrompeu."}]))
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    assert len(cliente.get("/api/buscar", params={"q": "sd"}).json()) == 2
    so_ana = cliente.get("/api/buscar", params={"q": "sd", "falante": "Ana"}).json()
    assert [r["arquivo"] for r in so_ana] == ["d.ogg"]


def test_vozes_sem_modelo_ou_cadastro_diz_que_nao_esta_disponivel():
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    dados = cliente.get("/api/vozes").json()
    assert dados["disponivel"] is False and dados["pessoas"] == []
