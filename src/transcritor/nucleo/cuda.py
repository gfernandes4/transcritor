"""Bibliotecas CUDA no Windows: os pacotes pip `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` trazem DLLs
que o Python precisa saber onde estão antes de carregar o faster-whisper na GPU."""
from __future__ import annotations

import os
import site
from pathlib import Path


def registrar_cuda() -> None:
    if os.name != "nt":
        return
    bases = set(site.getsitepackages()) | {site.getusersitepackages()}
    for base in bases:
        for sub in ("cublas", "cudnn", "cuda_nvrtc"):
            pasta = Path(base) / "nvidia" / sub / "bin"
            if pasta.is_dir():
                os.add_dll_directory(str(pasta))
                os.environ["PATH"] = str(pasta) + os.pathsep + os.environ.get("PATH", "")


def erro_de_cuda(exc: Exception) -> bool:
    texto = str(exc).lower()
    return any(p in texto for p in ("cublas", "cudnn", "cuda", "cudart"))
