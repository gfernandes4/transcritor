"""Gera o fluxograma em Mermaid a partir dos passos que o modelo extraiu."""
from __future__ import annotations

import re


def _rotulo(texto: str, limite: int = 90) -> str:
    texto = re.sub(r"[\"\[\]{}<>|`]", "", " ".join(str(texto).split()))
    return (texto[: limite - 1] + "…") if len(texto) > limite else texto


def validar(passos: list[dict]) -> list[dict]:
    """Remove ligações para passos que não existem e passos sem texto."""
    ids = {p["id"] for p in passos if p.get("id") and p.get("texto")}
    limpos = []
    for p in passos:
        if p.get("id") in ids:
            limpos.append({"id": p["id"], "texto": p["texto"], "depois": [d for d in p.get("depois", []) if d in ids and d != p["id"]]})
    return limpos


def renderizar(passos: list[dict], definido: list[str], em_aberto: list[str], tarefas: list[str]) -> str:
    """`flowchart TD` com o raciocínio em ordem e três grupos laterais (definido, em aberto, tarefas)."""
    passos = validar(passos)
    mapa = {p["id"]: f"n{i}" for i, p in enumerate(passos, 1)}
    linhas = ["flowchart TD"]
    for p in passos:
        linhas.append(f'    {mapa[p["id"]]}["{_rotulo(p["texto"])}"]')
    for p in passos:
        for destino in p["depois"]:
            linhas.append(f"    {mapa[p['id']]} --> {mapa[destino]}")
    # Sem ligações vindas do modelo, encadeia na ordem em que os passos apareceram.
    if passos and not any(p["depois"] for p in passos):
        for a, b in zip(passos, passos[1:]):
            linhas.append(f"    {mapa[a['id']]} --> {mapa[b['id']]}")

    def grupo(nome: str, titulo: str, itens: list[str], classe: str) -> None:
        if not itens:
            return
        linhas.append(f'    subgraph {nome}["{titulo}"]')
        for i, texto in enumerate(itens, 1):
            linhas.append(f'        {nome}{i}["{_rotulo(texto)}"]:::{classe}')
        linhas.append("    end")

    grupo("def", "Definido", definido, "definido")
    grupo("abe", "Em aberto", em_aberto, "aberto")
    grupo("tar", "Tarefas", tarefas, "tarefa")
    linhas += [
        "    classDef definido fill:#e1f5ec,stroke:#1f8f5f",
        "    classDef aberto fill:#fff3d6,stroke:#d98a00,stroke-dasharray:4 3",
        "    classDef tarefa fill:#efe8fb,stroke:#7a4fc7",
    ]
    return "\n".join(linhas) + "\n"
