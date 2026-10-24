"""Testes da interface web, com um executor de mentira (sem Whisper)."""
import io
import time
import zipfile
from pathlib import Path

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


# ---------- links de vídeo e resumo na fila ----------

LINK = "https://www.youtube.com/watch?v=5Pr1kNiDwAE"


def com_links_disponiveis(monkeypatch, ativo=True):
    from transcritor.nucleo import youtube

    monkeypatch.setattr(youtube, "disponivel", lambda: ativo)


def test_envio_so_com_link_entra_na_fila(monkeypatch):
    com_links_disponiveis(monkeypatch)
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    job = cliente.post("/enviar", data={"links": f"{LINK}\n\n  {LINK}  \nhttps://youtu.be/abc", "resumir": "true"}).json()
    assert job["links"] == [LINK, "https://youtu.be/abc"] and job["total"] == 2 and job["resumir"] is True and job["arquivos"] == []


def test_envio_mistura_arquivo_e_link(monkeypatch):
    com_links_disponiveis(monkeypatch)
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    job = cliente.post("/enviar", files=[("arquivos", ("a.ogg", b"x", "audio/ogg"))], data={"links": LINK}).json()
    assert job["total"] == 2 and job["arquivos"] == ["a.ogg"] and job["links"] == [LINK]


@pytest.mark.parametrize("dados, trecho", [
    ({}, "Escolha ao menos um áudio ou cole um link"),
    ({"links": "audio.ogg"}, "não parece um link"),
    ({"links": "\n".join(f"https://youtu.be/{i}" for i in range(11))}, "no máximo 10"),
])
def test_envio_com_entrada_invalida_explica(monkeypatch, dados, trecho):
    com_links_disponiveis(monkeypatch)
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    resp = cliente.post("/enviar", data=dados)
    assert resp.status_code == 400 and trecho in resp.json()["detail"]


def test_link_sem_o_extra_instalado_explica_como_instalar(monkeypatch):
    com_links_disponiveis(monkeypatch, ativo=False)
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    resp = cliente.post("/enviar", data={"links": LINK})
    assert resp.status_code == 400 and "transcritor[youtube]" in resp.json()["detail"]


def test_recursos_dizem_o_que_esta_disponivel(monkeypatch):
    from transcritor.resumo.llm import Ollama

    com_links_disponiveis(monkeypatch)
    monkeypatch.setattr(Ollama, "disponivel", lambda self, timeout=5: False)
    cliente = TestClient(criar_app(Fila(executar=executor_falso, iniciar_worker=False)))
    assert cliente.get("/api/recursos").json() == {"youtube": True, "ollama": False}


def montar_job(tmp_path, **extra):
    from transcritor.web.app import Job

    entrada = tmp_path / "entrada"
    entrada.mkdir(exist_ok=True)
    (entrada / "a.ogg").write_bytes(b"x")
    return Job(id="j1", arquivos=[entrada / "a.ogg"], saida=tmp_path / "saida", formatos=["txt", "json"], glossario=[], **extra)


def preparar_executor(monkeypatch, ordem, falha_no_resumo=None, link_ruim=None):
    """Troca Whisper, download e Ollama por versões de mentira que registram a ordem das chamadas."""
    from transcritor.nucleo import youtube
    from transcritor.transcricao import Transcricao
    from transcritor.web import app as app_mod

    class Motor:
        def __init__(self, *a, **k):
            pass

        def descarregar(self):
            ordem.append("whisper saiu")

    def feito(nome, origem=None):
        return Transcricao(arquivo=nome, duracao_s=3, modelo="m", idioma="pt", sha1=nome, origem=origem,
                           segmentos=[{"inicio": 0.0, "fim": 1.0, "texto": f"texto de {nome}"}])

    def transcrever(caminho, **kw):
        ordem.append(f"transcreveu {Path(caminho).name}")
        return feito(Path(caminho).name)

    def transcrever_url(url, ao_etapa=None, **kw):
        ao_etapa("baixando", url)
        if link_ruim and link_ruim in url:
            raise youtube.ErroDownload("O YouTube pediu uma verificação anti-robô")
        ordem.append(f"baixou {url}")
        return feito("Vídeo [abc12345678]", {"url": url, "titulo": "Vídeo", "canal": "Canal"})

    def resumir_pasta(pasta, **kw):
        ordem.append("resumiu")
        if falha_no_resumo:
            raise RuntimeError(falha_no_resumo)
        (Path(kw["saida"])).mkdir(parents=True, exist_ok=True)
        (Path(kw["saida"]) / "resumo.md").write_text("# Resumo", encoding="utf-8")
        ordem.append(sorted(p.name for p in kw["somente"]))
        return kw["saida"]

    monkeypatch.setattr(app_mod, "Motor", Motor)
    monkeypatch.setattr(app_mod, "transcrever", transcrever)
    monkeypatch.setattr(app_mod, "transcrever_url", transcrever_url)
    monkeypatch.setattr("transcritor.resumo.resumir_pasta", resumir_pasta)
    return app_mod


def test_job_com_arquivo_e_link_transcreve_tudo_e_so_resume_depois_de_liberar_o_whisper(tmp_path, monkeypatch):
    ordem = []
    app_mod = preparar_executor(monkeypatch, ordem)
    job = montar_job(tmp_path, urls=[LINK], resumir=True)
    app_mod.executar_job(job)
    assert ordem[:2] == ["transcreveu a.ogg", f"baixou {LINK}"]
    assert ordem[2:4] == ["whisper saiu", "resumiu"]
    assert ordem[4] == ["Vídeo [abc12345678].json", "a.json"]
    assert job.feitos == 2 and job.resumo_pronto and job.avisos == []


def test_link_que_falha_vira_aviso_e_o_resto_segue(tmp_path, monkeypatch):
    ordem = []
    app_mod = preparar_executor(monkeypatch, ordem, link_ruim="ruim")
    job = montar_job(tmp_path, urls=["https://www.youtube.com/watch?v=ruim"])
    app_mod.executar_job(job)
    assert job.feitos == 2 and len(job.avisos) == 1 and "anti-robô" in job.avisos[0] and "ruim" in job.avisos[0]


def test_se_todos_os_itens_falham_o_envio_vira_erro_com_o_motivo(tmp_path, monkeypatch):
    from transcritor.web.app import Fila

    app_mod = preparar_executor(monkeypatch, [], link_ruim="ruim")
    fila = Fila(executar=app_mod.executar_job, iniciar_worker=False)
    from transcritor.web.app import Job

    job = Job(id="j2", arquivos=[], saida=tmp_path / "s", formatos=["json"], glossario=[], urls=["https://www.youtube.com/watch?v=ruim"])
    fila.jobs[job.id] = job
    fila._rodar(job)
    assert job.status == "erro" and "anti-robô" in job.erro


def test_resumo_que_falha_nao_perde_as_transcricoes(tmp_path, monkeypatch):
    app_mod = preparar_executor(monkeypatch, [], falha_no_resumo="O Ollama não responde")
    job = montar_job(tmp_path, resumir=True)
    app_mod.executar_job(job)
    assert job.feitos == 1 and not job.resumo_pronto
    assert any("resumo falhou" in a and "Ollama" in a for a in job.avisos)
    assert (tmp_path / "saida" / "a.json").exists()


def test_job_cancelado_antes_de_comecar_nao_resume_nem_baixa(tmp_path, monkeypatch):
    ordem = []
    app_mod = preparar_executor(monkeypatch, ordem)
    job = montar_job(tmp_path, urls=[LINK], resumir=True)
    job.cancelado = True
    app_mod.executar_job(job)
    assert ordem == ["whisper saiu"] and job.feitos == 0


def test_resumo_e_zip_incluem_a_subpasta(tmp_path):
    def com_resumo(job):
        (job.saida / "resumo").mkdir(parents=True, exist_ok=True)
        (job.saida / "a.txt").write_text("oi", encoding="utf-8")
        (job.saida / "resumo" / "resumo.md").write_text("# Resumo do vídeo", encoding="utf-8")
        job.feitos += 1
        job.resumo_pronto = True

    cliente = TestClient(criar_app(Fila(executar=com_resumo)))
    job = cliente.post("/enviar", files=[("arquivos", ("a.ogg", b"x", "audio/ogg"))]).json()
    esperar(cliente, "concluído")
    assert cliente.get(f"/api/fila/{job['id']}/resumo").json() == {"markdown": "# Resumo do vídeo"}
    nomes = zipfile.ZipFile(io.BytesIO(cliente.get(f"/resultado/{job['id']}").content)).namelist()
    assert nomes == ["a.txt", "resumo/resumo.md"]
    assert cliente.get("/api/fila/nao-existe/resumo").status_code == 404
