"""Identificação de voz por áudio (módulo opcional: `pip install "transcritor[vozes]"`).

Pensado para áudios de WhatsApp, em que cada arquivo tem uma voz só. Não separa vozes dentro do mesmo áudio.
"""
from . import identificar, perfis
from .embedding import ErroVoz, Extrator, baixar_modelo

__all__ = ["identificar", "perfis", "Extrator", "ErroVoz", "baixar_modelo", "identificar_arquivo"]


_extratores: dict[str, Extrator] = {}


def identificar_arquivo(caminho, extrator=None):
    """Devolve `Resultado` (nome ou None, confiança, margem) usando as vozes cadastradas e a calibração salva."""
    cfg = identificar.configuracao()
    if extrator is None:
        extrator = _extratores.get(cfg["modelo"]) or _extratores.setdefault(cfg["modelo"], Extrator(cfg["modelo"]))
    return identificar.decidir(extrator.do_arquivo(caminho), perfis.perfis(extrator.nome), cfg["limiar"], cfg["margem"])
