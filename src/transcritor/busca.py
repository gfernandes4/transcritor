"""Índice de busca em todas as transcrições (SQLite com FTS5, sem diferenciar acentos)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import caminho_db
from .transcricao import Transcricao

ESQUEMA = """
create table if not exists transcricoes(
    id integer primary key,
    arquivo text not null,
    sha1 text,
    duracao_s real,
    modelo text,
    falante text,
    criado_em text,
    json_path text
);
create unique index if not exists idx_transcricoes_sha1 on transcricoes(sha1) where sha1 != '';
create virtual table if not exists trechos using fts5(
    texto, transcricao_id unindexed, inicio unindexed,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(caminho_db())
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def indexar(t: Transcricao, json_path: str | Path = "") -> int:
    """Grava a transcrição no índice. Se o mesmo áudio (mesmo sha1) já estava, substitui. Devolve o id."""
    con = _conectar()
    with con:
        if t.sha1:
            antigo = con.execute("select id from transcricoes where sha1 = ?", (t.sha1,)).fetchone()
            if antigo:
                con.execute("delete from trechos where transcricao_id = ?", (antigo["id"],))
                con.execute("delete from transcricoes where id = ?", (antigo["id"],))
        cur = con.execute(
            "insert into transcricoes(arquivo, sha1, duracao_s, modelo, falante, criado_em, json_path) values (?,?,?,?,?,?,?)",
            (t.arquivo, t.sha1, t.duracao_s, t.modelo, (t.falante or {}).get("nome"), t.gerado_em, str(json_path)),
        )
        tid = cur.lastrowid
        con.executemany(
            "insert into trechos(texto, transcricao_id, inicio) values (?,?,?)",
            [(s["texto"], tid, s["inicio"]) for s in t.segmentos],
        )
    con.close()
    return tid


def _consulta_segura(consulta: str) -> str:
    """Cada palavra vira um termo entre aspas (todas precisam aparecer), sem quebrar a sintaxe do FTS5."""
    termos = [p.replace('"', "") for p in consulta.split() if p.strip('"')]
    return " ".join(f'"{p}"' for p in termos)


def buscar(consulta: str, falante: str | None = None, limite: int = 20) -> list[dict]:
    """Trechos que contêm todas as palavras da consulta, do mais relevante ao menos."""
    seguro = _consulta_segura(consulta)
    if not seguro:
        return []
    con = _conectar()
    sql = (
        "select t.arquivo, t.falante, t.json_path, r.inicio, r.texto "
        "from trechos r join transcricoes t on t.id = r.transcricao_id "
        "where trechos match ?"
    )
    params: list = [seguro]
    if falante:
        sql += " and lower(t.falante) = lower(?)"
        params.append(falante)
    sql += " order by rank limit ?"
    params.append(limite)
    linhas = [dict(l) for l in con.execute(sql, params)]
    con.close()
    return linhas
