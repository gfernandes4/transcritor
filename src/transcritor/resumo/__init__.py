"""Resumo automático das transcrições (módulo opcional; usa o Ollama local)."""
from .resumir import contexto_de_videos, resumir_pasta

__all__ = ["resumir_pasta", "contexto_de_videos"]
