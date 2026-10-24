"""Transcritor local de áudios."""
from .api import buscar, transcrever, transcrever_pasta
from .transcricao import Transcricao

__version__ = "0.1.0"
__all__ = ["transcrever", "transcrever_pasta", "buscar", "Transcricao", "__version__"]
