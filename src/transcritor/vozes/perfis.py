"""Cadastro de vozes: cada amostra de uma pessoa fica no SQLite; o perfil é a média das amostras."""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import numpy as np

from ..config import caminho_db
from ..nucleo.audio import sha1_do_arquivo

ESQUEMA = """
create table if not exists vozes_amostras(
    id integer primary key,
    nome text not null,
    arquivo text,
    sha1 text,
    modelo text not null,
    embedding blob not null,
    criado_em text,
    unique(nome, sha1, modelo)
);
"""


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(caminho_db())
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def normalizar(vetor: np.ndarray) -> np.ndarray:
    norma = float(np.linalg.norm(vetor))
    return vetor / norma if norma else vetor


def cadastrar(nome: str, arquivos: list[Path], extrator) -> list[Path]:
    """Guarda a voz de `nome` a partir de cada arquivo. Devolve os arquivos novos (repetidos são ignorados)."""
    nome = " ".join(nome.split())
    if not nome:
        raise ValueError("nome vazio")
    novos = []
    con = _conectar()
    with con:
        for arquivo in arquivos:
            sha1 = sha1_do_arquivo(arquivo)
            if con.execute("select 1 from vozes_amostras where nome=? and sha1=? and modelo=?", (nome, sha1, extrator.nome)).fetchone():
                continue
            vetor = extrator.do_arquivo(arquivo).astype(np.float32)
            con.execute(
                "insert into vozes_amostras(nome, arquivo, sha1, modelo, embedding, criado_em) values (?,?,?,?,?,?)",
                (nome, Path(arquivo).name, sha1, extrator.nome, vetor.tobytes(), dt.datetime.now().isoformat(timespec="seconds")),
            )
            novos.append(Path(arquivo))
    con.close()
    return novos


def perfis(modelo: str) -> dict[str, np.ndarray]:
    """Perfil de cada pessoa cadastrada: a média das amostras, normalizada."""
    con = _conectar()
    por_nome: dict[str, list[np.ndarray]] = {}
    for linha in con.execute("select nome, embedding from vozes_amostras where modelo = ?", (modelo,)):
        por_nome.setdefault(linha["nome"], []).append(np.frombuffer(linha["embedding"], dtype=np.float32))
    con.close()
    return {nome: normalizar(np.mean(vetores, axis=0)) for nome, vetores in por_nome.items()}


def listar() -> list[dict]:
    con = _conectar()
    linhas = [dict(l) for l in con.execute("select nome, modelo, count(*) as amostras from vozes_amostras group by nome, modelo order by nome")]
    con.close()
    return linhas


def remover(nome: str) -> int:
    con = _conectar()
    with con:
        n = con.execute("delete from vozes_amostras where lower(nome) = lower(?)", (" ".join(nome.split()),)).rowcount
    con.close()
    return n
