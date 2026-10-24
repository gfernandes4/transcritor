"""Formatos de saída: txt, md, json, srt e vtt."""
from __future__ import annotations

import json

from .transcricao import Transcricao, formatar_tempo

FORMATOS = ("txt", "md", "json", "srt", "vtt")


def _tempo_legenda(segundos: float, separador: str) -> str:
    ms = int(round(segundos * 1000))
    h, resto = divmod(ms, 3_600_000)
    m, resto = divmod(resto, 60_000)
    s, ms = divmod(resto, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{separador}{ms:03d}"


def _txt(t: Transcricao) -> str:
    return t.texto + "\n"


def _md(t: Transcricao) -> str:
    minutos, segundos = divmod(int(t.duracao_s), 60)
    linhas = [f"# {t.arquivo}", "", f"- Duração: {minutos}:{segundos:02d} · Modelo: {t.modelo} · Idioma: {t.idioma}"]
    if t.origem:
        canal = f" · Canal: {t.origem['canal']}" if t.origem.get("canal") else ""
        linhas.append(f"- Fonte: [{t.origem.get('titulo') or t.origem['url']}]({t.origem['url']}){canal}")
    if t.falante:
        linhas.append(f"- Falante: {t.falante.get('nome')} ({t.falante.get('confianca', 0):.0%})")
    if t.alertas:
        linhas.append(f"- Alertas: {len(t.alertas)}")
    linhas += ["", "## Transcrição", ""]
    linhas += [f"**[{formatar_tempo(s['inicio'])}]** {s['texto']}" for s in t.segmentos]
    if t.alertas:
        linhas += ["", "## Alertas", ""]
        linhas += [f"- [{formatar_tempo(a['inicio'])}] {a['tipo']}: {a['detalhe']}" for a in t.alertas]
    return "\n".join(linhas) + "\n"


def _json(t: Transcricao) -> str:
    return json.dumps(t.para_dict(), ensure_ascii=False, indent=2) + "\n"


def _srt(t: Transcricao) -> str:
    blocos = []
    for n, s in enumerate(t.segmentos, 1):
        blocos.append(f"{n}\n{_tempo_legenda(s['inicio'], ',')} --> {_tempo_legenda(s['fim'], ',')}\n{s['texto']}\n")
    return "\n".join(blocos)


def _vtt(t: Transcricao) -> str:
    blocos = ["WEBVTT\n"]
    for s in t.segmentos:
        blocos.append(f"{_tempo_legenda(s['inicio'], '.')} --> {_tempo_legenda(s['fim'], '.')}\n{s['texto']}\n")
    return "\n".join(blocos)


_GERADORES = {"txt": _txt, "md": _md, "json": _json, "srt": _srt, "vtt": _vtt}


def gerar(t: Transcricao, formato: str) -> str:
    try:
        return _GERADORES[formato](t)
    except KeyError:
        raise ValueError(f"Formato desconhecido: {formato}. Use um destes: {', '.join(FORMATOS)}") from None
