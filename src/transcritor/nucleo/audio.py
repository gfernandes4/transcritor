"""Localiza arquivos de áudio e vídeo."""
from __future__ import annotations

import hashlib
from pathlib import Path

EXTENSOES = {
    ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".oga", ".aac", ".flac", ".wma", ".amr",
    ".mp4", ".webm", ".mkv", ".mov",
}


def listar_audios(caminho: str | Path) -> list[Path]:
    """Um arquivo vira uma lista de um; uma pasta vira seus áudios, em ordem de nome."""
    caminho = Path(caminho)
    if caminho.is_file():
        return [caminho]
    if not caminho.is_dir():
        raise FileNotFoundError(f"Não encontrei {caminho}")
    return sorted(p for p in caminho.iterdir() if p.is_file() and p.suffix.lower() in EXTENSOES)


def sha1_do_arquivo(caminho: str | Path) -> str:
    h = hashlib.sha1()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()
