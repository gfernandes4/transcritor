"""Interface web mínima: enviar áudios, acompanhar a fila (um job por vez, por causa da GPU) e baixar os resultados.

Só escuta em 127.0.0.1. Não há login: não é feita para ser exposta na internet.
"""
from __future__ import annotations

import io
import json
import queue
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from .. import busca, exportar
from ..api import transcrever
from ..config import MODELO_PADRAO, home
from ..nucleo import glossario as gl
from ..nucleo.audio import EXTENSOES
from ..nucleo.whisper import Motor
from ..transcricao import Transcricao

PAGINA = Path(__file__).with_name("pagina.html")


@dataclass
class Job:
    id: str
    arquivos: list[Path]
    saida: Path
    formatos: list[str]
    glossario: list[str]
    falantes: bool = False
    status: str = "na fila"          # na fila | transcrevendo | concluído | cancelado | erro
    feitos: int = 0
    atual: str = ""                  # arquivo em andamento
    erro: str = ""
    cancelado: bool = False
    criado_em: float = field(default_factory=time.time)

    def para_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "feitos": self.feitos, "total": len(self.arquivos),
                "arquivos": [a.name for a in self.arquivos], "atual": self.atual, "erro": self.erro,
                "falantes": self.falantes, "criado_em": self.criado_em}


def executar_job(job: Job) -> None:
    """Transcreve os arquivos do job com um único carregamento do modelo."""
    motor = Motor(MODELO_PADRAO)
    try:
        for arquivo in job.arquivos:
            if job.cancelado:
                break
            job.atual = arquivo.name
            t = transcrever(arquivo, glossario=job.glossario or None, motor=motor, falantes=job.falantes)
            gravados = t.salvar(job.saida, job.formatos)
            busca.indexar(t, next(p for p in gravados if p.suffix == ".json"))
            job.feitos += 1
    finally:
        motor.descarregar()


class Fila:
    def __init__(self, executar=executar_job, iniciar_worker: bool = True):
        self.jobs: dict[str, Job] = {}
        self._fila: queue.Queue[Job] = queue.Queue()
        self._executar = executar
        if iniciar_worker:
            threading.Thread(target=self._loop, daemon=True).start()

    def enviar(self, arquivos: list[Path], saida: Path, formatos: list[str], glossario: list[str],
               falantes: bool = False, job_id: str | None = None) -> Job:
        job = Job(id=job_id or uuid.uuid4().hex[:8], arquivos=arquivos, saida=saida, formatos=formatos,
                  glossario=glossario, falantes=falantes)
        self.jobs[job.id] = job
        self._fila.put(job)
        return job

    def cancelar(self, job_id: str) -> Job | None:
        """Na fila, o job nem começa; em andamento, para depois do arquivo atual (o que já ficou pronto é mantido)."""
        job = self.jobs.get(job_id)
        if job and job.status in ("na fila", "transcrevendo"):
            job.cancelado = True
            if job.status == "na fila":
                job.status = "cancelado"
        return job

    def _loop(self) -> None:
        while True:
            self._rodar(self._fila.get())

    def _rodar(self, job: Job) -> None:
        if job.cancelado:
            job.status = "cancelado"
            return
        job.status = "transcrevendo"
        try:
            self._executar(job)
            job.status = "cancelado" if job.cancelado else "concluído"
        except Exception as exc:  # noqa: BLE001 - um job com erro não derruba a fila
            job.status, job.erro = "erro", str(exc)
        finally:
            job.atual = ""


def criar_app(fila: Fila | None = None) -> FastAPI:
    app = FastAPI(title="Transcritor")
    fila = fila or Fila()
    pasta_web = home() / "web"

    @app.get("/")
    def pagina():
        return FileResponse(PAGINA, media_type="text/html; charset=utf-8")

    @app.post("/enviar")
    async def enviar(arquivos: list[UploadFile] = File(...), formatos: str = Form("txt,md,json"), termos: str = Form(""),
                     falantes: bool = Form(False)):
        lista_formatos = [f.strip() for f in formatos.split(",") if f.strip()]
        if any(f not in exportar.FORMATOS for f in lista_formatos):
            raise HTTPException(400, f"Formato inválido. Use: {', '.join(exportar.FORMATOS)}")
        if "json" not in lista_formatos:
            lista_formatos.append("json")
        job_id = uuid.uuid4().hex[:8]
        entrada = pasta_web / job_id / "entrada"
        entrada.mkdir(parents=True, exist_ok=True)
        salvos = []
        for up in arquivos:
            nome = Path(up.filename or "audio").name  # nunca confiar em caminho vindo do navegador
            if Path(nome).suffix.lower() not in EXTENSOES:
                raise HTTPException(400, f"Tipo de arquivo não suportado: {nome}")
            destino = entrada / nome
            with destino.open("wb") as f:
                shutil.copyfileobj(up.file, f)
            salvos.append(destino)
        extras = [t.strip() for t in termos.splitlines() if t.strip()]
        job = fila.enviar(salvos, pasta_web / job_id / "saida", lista_formatos, gl.carregar(termos=extras),
                          falantes=falantes, job_id=job_id)
        return job.para_dict()

    @app.get("/api/fila")
    def listar_fila():
        return [j.para_dict() for j in sorted(fila.jobs.values(), key=lambda j: j.criado_em, reverse=True)]

    @app.post("/api/fila/{job_id}/cancelar")
    def cancelar(job_id: str):
        job = fila.cancelar(job_id)
        if not job:
            raise HTTPException(404, "Esse envio não existe mais.")
        return job.para_dict()

    @app.get("/api/fila/{job_id}/previa")
    def previa(job_id: str, limite: int = 400):
        """Começo do texto de cada áudio já transcrito, para conferir sem baixar o .zip."""
        job = fila.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Esse envio não existe mais.")
        itens = []
        for caminho in sorted(job.saida.glob("*.json")):
            try:
                t = Transcricao.de_dict(json.loads(caminho.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError):
                continue
            texto = t.texto
            itens.append({"arquivo": t.arquivo, "duracao_s": t.duracao_s, "alertas": len(t.alertas),
                          "falante": (t.falante or {}).get("nome"),
                          "trecho": texto[:limite] + ("…" if len(texto) > limite else "")})
        return itens

    @app.get("/resultado/{job_id}")
    def resultado(job_id: str):
        job = fila.jobs.get(job_id)
        if not job or not (job.status == "concluído" or (job.status == "cancelado" and job.feitos)):
            raise HTTPException(404, "Resultado ainda não está pronto.")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for caminho in sorted(job.saida.glob("*")):
                z.write(caminho, caminho.name)
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="transcricoes_{job_id}.zip"'})

    @app.get("/api/glossario")
    def ler_glossario():
        return gl.listar()

    @app.post("/api/glossario")
    def adicionar_termo(termo: str = Form(...)):
        try:
            return {"adicionado": gl.adicionar(termo)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/glossario")
    def remover_termo(termo: str):
        return {"removido": gl.remover(termo)}

    @app.get("/api/buscar")
    def buscar(q: str, limite: int = 20, falante: str | None = None):
        return busca.buscar(q, falante=falante or None, limite=min(limite, 100))

    @app.get("/api/vozes")
    def vozes():
        """Pessoas cadastradas e se dá para identificar quem fala (precisa do extra [vozes] e do modelo baixado)."""
        try:
            from ..vozes import identificar, perfis
            from ..vozes.embedding import caminho_modelo
        except ImportError:
            return {"disponivel": False, "modelo_baixado": False, "pessoas": []}
        cfg = identificar.configuracao()
        pessoas = [{"nome": p["nome"], "amostras": p["amostras"]} for p in perfis.listar() if p["modelo"] == cfg["modelo"]]
        baixado = caminho_modelo(cfg["modelo"]).exists()
        return {"disponivel": bool(baixado and pessoas), "modelo_baixado": baixado, "pessoas": pessoas}

    return app
