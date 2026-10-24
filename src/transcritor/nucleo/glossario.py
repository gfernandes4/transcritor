"""Glossário de nomes e termos: ajuda o Whisper a acertar pessoas, siglas e produtos.

O arquivo fica em ~/.transcritor/glossario.txt (um termo por linha; linhas com # são comentários)
e cresce com `transcritor glossario add "Termo"`.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from ..config import GLOSSARIO_INICIAL, caminho_glossario

CABECALHO = (
    "# Glossário do transcritor: um termo por linha.\n"
    "# Nomes de pessoas, siglas e produtos que o Whisper costuma errar.\n"
)


def _ler(caminho: Path) -> list[str]:
    termos = []
    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#"):
            termos.append(" ".join(linha.split()))
    return termos


def _unicos(termos: list[str]) -> list[str]:
    vistos: set[str] = set()
    saida = []
    for termo in termos:
        chave = termo.casefold()
        if chave not in vistos:
            vistos.add(chave)
            saida.append(termo)
    return saida


def garantir_arquivo() -> Path:
    """Cria o glossário com os termos iniciais na primeira vez."""
    caminho = caminho_glossario()
    if not caminho.exists():
        caminho.write_text(CABECALHO + "\n".join(GLOSSARIO_INICIAL) + "\n", encoding="utf-8")
    return caminho


def listar() -> list[str]:
    return _unicos(_ler(garantir_arquivo()))


def carregar(arquivo: str | Path | None = None, termos: list[str] | None = None) -> list[str]:
    """Glossário do usuário + (opcional) um arquivo extra + (opcional) termos avulsos."""
    todos = listar()
    if arquivo:
        todos += _ler(Path(arquivo))
    if termos:
        todos += [" ".join(t.split()) for t in termos if t.strip()]
    return _unicos(todos)


def adicionar(termo: str) -> bool:
    """Devolve False se o termo já existe (sem diferenciar maiúsculas)."""
    termo = " ".join(termo.split())
    if not termo:
        raise ValueError("termo vazio")
    if termo.casefold() in {t.casefold() for t in listar()}:
        return False
    with garantir_arquivo().open("a", encoding="utf-8") as f:
        f.write(termo + "\n")
    return True


def remover(termo: str) -> bool:
    caminho = garantir_arquivo()
    alvo = " ".join(termo.split()).casefold()
    linhas = caminho.read_text(encoding="utf-8-sig").splitlines()
    mantidas = [l for l in linhas if l.strip().casefold() != alvo]
    if len(mantidas) == len(linhas):
        return False
    caminho.write_text("\n".join(mantidas) + "\n", encoding="utf-8")
    return True


_CAPITALIZADA = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ-]{2,})")


def sugerir(textos: list[str], minimo: int = 2) -> list[tuple[str, int]]:
    """Palavras com inicial maiúscula no meio da frase que aparecem pelo menos `minimo` vezes
    e ainda não estão no glossário. São candidatas a nome próprio."""
    conhecidos = {t.casefold() for t in listar()}
    contagem: Counter[str] = Counter()
    for texto in textos:
        contagem.update(_CAPITALIZADA.findall(texto))
    return [(p, n) for p, n in contagem.most_common() if n >= minimo and p.casefold() not in conhecidos]
