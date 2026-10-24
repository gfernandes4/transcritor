"""Resultado de uma transcrição e como salvá-lo."""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from pathlib import Path


def formatar_tempo(segundos: float) -> str:
    segundos = int(segundos)
    return f"{segundos // 3600:02d}:{segundos % 3600 // 60:02d}:{segundos % 60:02d}"


@dataclass
class Transcricao:
    arquivo: str
    duracao_s: float
    modelo: str
    idioma: str
    segmentos: list[dict] = field(default_factory=list)  # [{inicio, fim, texto}]
    glossario: list[str] = field(default_factory=list)
    falante: dict | None = None                          # {nome, confianca} (módulo de voz)
    alertas: list[dict] = field(default_factory=list)    # [{tipo, inicio, detalhe}]
    sha1: str = ""
    origem: dict | None = None                           # {url, titulo, canal} quando veio de um link
    gerado_em: str = field(default_factory=lambda: dt.datetime.now().isoformat(timespec="seconds"))

    @property
    def texto(self) -> str:
        """Texto com o horário no começo de cada trecho."""
        return "\n".join(f"[{formatar_tempo(s['inicio'])}] {s['texto']}" for s in self.segmentos)

    @property
    def texto_simples(self) -> str:
        return " ".join(s["texto"] for s in self.segmentos)

    def para_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def de_dict(cls, dados: dict) -> "Transcricao":
        campos = {k: v for k, v in dados.items() if k in cls.__dataclass_fields__}
        return cls(**campos)

    def salvar(self, pasta: str | Path, formatos: tuple[str, ...] | list[str] = ("txt", "md", "json")) -> list[Path]:
        """Grava um arquivo por formato em `pasta`, com o nome do áudio. Devolve os caminhos."""
        from . import exportar

        pasta = Path(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        base = Path(self.arquivo).stem
        gravados = []
        for formato in formatos:
            caminho = pasta / f"{base}.{formato}"
            caminho.write_text(exportar.gerar(self, formato), encoding="utf-8")
            gravados.append(caminho)
        return gravados
