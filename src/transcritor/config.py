"""Caminhos e padrões do transcritor."""
from __future__ import annotations

import os
from pathlib import Path

MODELO_PADRAO = "large-v3"
IDIOMA_PADRAO = "pt"

# Termos que entram no glossário na primeira vez (exemplos; o glossário do usuário cresce com `transcritor glossario add`).
GLOSSARIO_INICIAL = [
    "Ana", "Bruno", "Caio", "Davi", "Elisa", "Acme", "SD", "CM4", "eMMC", "Ollama",
]


def home() -> Path:
    """Pasta de dados do usuário (glossário, banco, vozes). Fora do repositório."""
    pasta = Path(os.environ.get("TRANSCRITOR_HOME") or Path.home() / ".transcritor")
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def caminho_glossario() -> Path:
    return home() / "glossario.txt"


def caminho_db() -> Path:
    return home() / "db.sqlite"
