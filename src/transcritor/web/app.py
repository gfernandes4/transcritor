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
from ..api import transcrever, transcrever_url
from ..config import MODELO_PADRAO, home
from ..nucleo import glossario as gl
from ..nucleo import youtube
from ..nucleo.audio import EXTENSOES
from ..nucleo.whisper import Motor
from ..transcricao import Transcricao

PAGINA = Path(__file__).with_name("pagina.html")
MAXIMO_DE_LINKS = 10


@dataclass
class Job:
    id: str
    arquivos: list[Path]
    saida: Path
    formatos: list[str]
    glossario: list[str]
    falantes: bool = False
    urls: list[str] = field(default_factory=list)
    resumir: bool = False
    status: str = "na fila"          # na fila | transcrevendo | concluído | cancelado | erro
    etapa: str = ""                  # baixando | transcrevendo | resumindo (enquanto o status é "transcrevendo")
    feitos: int = 0                  # itens terminados (com sucesso ou com falha)
    atual: str = ""                  # arquivo ou link em andamento
    erro: str = ""
    avisos: list[str] = field(default_factory=list)   # o que deu errado sem derrubar o envio
    resumo_pronto: bool = False
    cancelado: bool = False
    criado_em: float = field(default_factory=time.time)

    @property
    def total(self) -> int:
        return len(self.arquivos) + len(self.urls)

    def para_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "etapa": self.etapa, "feitos": self.feitos, "total": self.total,
                "arquivos": [a.name for a in self.arquivos], "links": self.urls, "atual": self.atual, "erro": self.erro,
                "avisos": self.avisos, "falantes": self.falantes, "resumir": self.resumir, "resumo_pronto": self.resumo_pronto,
                "criado_em": self.criado_em}


def _guardar(job: Job, t: Transcricao) -> Path:
    gravados = t.salvar(job.saida, job.formatos)
    json_path = next(p for p in gravados if p.suffix == ".json")
    busca.indexar(t, json_path)
    return json_path


def executar_job(job: Job) -> None:
    """Transcreve os arquivos e links do job com um único carregamento do modelo e, se pedido, resume no fim."""
    motor = Motor(MODELO_PADRAO)
    jsons: list[Path] = []
    origens: list[dict] = []
    try:
        for arquivo in job.arquivos:
            if job.cancelado:
                break
            job.etapa, job.atual = "transcrevendo", arquivo.name
            jsons.append(_guardar(job, transcrever(arquivo, glossario=job.glossario or None, motor=motor, falantes=job.falantes)))
            job.feitos += 1
        for url in job.urls:
            if job.cancelado:
                break
            job.etapa, job.atual = "baixando", url

            def marcar(etapa: str, detalhe: str) -> None:
                job.etapa, job.atual = etapa, detalhe

            try:
                t = transcrever_url(url, glossario=job.glossario or None, motor=motor, ao_etapa=marcar)
            except youtube.ErroDownload as exc:
                job.avisos.append(f"{url}: {exc}")
            else:
                jsons.append(_guardar(job, t))
                origens.append(t.origem)
            job.feitos += 1
    finally:
        motor.descarregar()   # a GPU precisa ficar livre para o Ollama
    if not jsons and not job.cancelado:
        raise RuntimeError(" ".join(job.avisos) or "Nada foi transcrito.")
    if job.resumir and jsons and not job.cancelado:
        job.etapa, job.atual = "resumindo", ""
        try:
            from ..resumo import contexto_de_videos, resumir_pasta

            contexto = contexto_de_videos(origens) if origens and len(origens) == len(jsons) else ""
            resumir_pasta(job.saida, saida=job.saida / "resumo", contexto=contexto, somente=jsons)
            job.resumo_pronto = True
        except Exception as exc:  # noqa: BLE001 - as transcrições já estão salvas; o resumo é um extra
            job.avisos.append(f"A transcrição está pronta, mas o resumo falhou: {exc}")


class Fila:
    def __init__(self, executar=executar_job, iniciar_worker: bool = True):
        self.jobs: dict[str, Job] = {}
        self._fila: queue.Queue[Job] = queue.Queue()
        self._executar = executar
        if iniciar_worker:
            threading.Thread(target=self._loop, daemon=True).start()

    def enviar(self, arquivos: list[Path], saida: Path, formatos: list[str], glossario: list[str],
               falantes: bool = False, job_id: str | None = None, urls: list[str] | None = None, resumir: bool = False) -> Job:
        job = Job(id=job_id or uuid.uuid4().hex[:8], arquivos=arquivos, saida=saida, formatos=formatos,
                  glossario=glossario, falantes=falantes, urls=urls or [], resumir=resumir)
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
            job.atual, job.etapa = "", ""


def criar_app(fila: Fila | None = None) -> FastAPI:
    app = FastAPI(title="Transcritor")
    fila = fila or Fila()
    pasta_web = home() / "web"

    @app.get("/")
    def pagina():
        return FileResponse(PAGINA, media_type="text/html; charset=utf-8")

    @app.post("/enviar")
    async def enviar(arquivos: list[UploadFile] = File(default=[]), formatos: str = Form("txt,md,json"), termos: str = Form(""),
                     falantes: bool = Form(False), links: str = Form(""), resumir: bool = Form(False)):
        lista_formatos = [f.strip() for f in formatos.split(",") if f.strip()]
        if any(f not in exportar.FORMATOS for f in lista_formatos):
            raise HTTPException(400, f"Formato inválido. Use: {', '.join(exportar.FORMATOS)}")
        arquivos = [up for up in arquivos if up.filename]
        urls = list(dict.fromkeys(l.strip() for l in links.splitlines() if l.strip()))
        if not arquivos and not urls:
            raise HTTPException(400, "Escolha ao menos um áudio ou cole um link.")
        for u in urls:
            if not youtube.eh_url(u):
                raise HTTPException(400, f"Isto não parece um link: {u[:60]}")
        if len(urls) > MAXIMO_DE_LINKS:
            raise HTTPException(400, f"Envie no máximo {MAXIMO_DE_LINKS} links de cada vez.")
        if urls and not youtube.disponivel():
            raise HTTPException(400, 'Falta o módulo de links. No terminal: pip install "transcritor[youtube]"')
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
                          falantes=falantes, job_id=job_id, urls=urls, resumir=resumir)
        return job.para_dict()

    @app.get("/api/recursos")
    def recursos():
        """O que está disponível agora: links (extra youtube) e resumo (Ollama aberto)."""
        from ..resumo.llm import Ollama

        return {"youtube": youtube.disponivel(), "ollama": Ollama().disponivel(timeout=1)}

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
            itens.append({"arquivo": t.arquivo, "duracao_s": t.duracao_s, "alertas": len(t.alertas), "origem": t.origem,
                          "falante": (t.falante or {}).get("nome"),
                          "trecho": texto[:limite] + ("…" if len(texto) > limite else "")})
        return itens

    @app.get("/api/fila/{job_id}/resumo")
    def resumo(job_id: str):
        job = fila.jobs.get(job_id)
        arquivo = job.saida / "resumo" / "resumo.md" if job else None
        if not arquivo or not arquivo.exists():
            raise HTTPException(404, "Esse envio não tem resumo.")
        return {"markdown": arquivo.read_text(encoding="utf-8")}

    @app.get("/resultado/{job_id}")
    def resultado(job_id: str):
        job = fila.jobs.get(job_id)
        if not job or not (job.status == "concluído" or (job.status == "cancelado" and job.feitos)):
            raise HTTPException(404, "Resultado ainda não está pronto.")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for caminho in sorted(p for p in job.saida.rglob("*") if p.is_file()):
                z.write(caminho, caminho.relative_to(job.saida).as_posix())
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
