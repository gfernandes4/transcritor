"""Limpeza de repetições e alertas de trechos suspeitos.

O Whisper às vezes entra em loop (a mesma frase repetida) ou "alucina" texto em outros alfabetos.
Aqui o loop óbvio é removido e o resto vira um alerta para uma pessoa conferir.
"""
from __future__ import annotations

import re

# Cirílico, hebraico, árabe, tailandês, japonês, chinês e coreano.
_NAO_LATINO = re.compile(r"[Ѐ-ӿ֐-׿؀-ۿ฀-๿぀-ヿ㐀-鿿가-힯]")
_FRASE_REPETIDA = re.compile(r"(\b[\wÀ-ÿ][\wÀ-ÿ ,']{3,40}?)(?:[,.\s]+\1\b){2,}", re.IGNORECASE)

MAX_PALAVRAS_SEM_PONTUACAO = 40
MAX_PALAVRAS_POR_SEGUNDO = 8.0  # fala rápida chega a ~7; acima disso o trecho costuma estar errado


def _norm(texto: str) -> str:
    return re.sub(r"\W+", " ", texto.casefold()).strip()


def limpar_e_alertar(segmentos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Devolve (segmentos sem loops óbvios, alertas). Não altera a lista original."""
    alertas: list[dict] = []
    limpos: list[dict] = []
    anterior = None
    for seg in segmentos:
        texto = seg["texto"]
        chave = _norm(texto)
        if chave and chave == anterior:
            alertas.append({"tipo": "repeticao_removida", "inicio": seg["inicio"],
                            "detalhe": f"linha repetida removida: {texto[:60]}"})
            continue
        anterior = chave
        colapsado = _FRASE_REPETIDA.sub(r"\1", texto)
        if colapsado != texto:
            alertas.append({"tipo": "repeticao_removida", "inicio": seg["inicio"],
                            "detalhe": "frase repetida dentro do trecho foi reduzida a uma vez"})
            texto = colapsado
        novo = dict(seg, texto=texto)
        limpos.append(novo)

        if _NAO_LATINO.search(texto):
            alertas.append({"tipo": "caracteres_estranhos", "inicio": seg["inicio"],
                            "detalhe": "caracteres de outro alfabeto; o trecho pode estar corrompido"})
        palavras = texto.split()
        if len(palavras) > MAX_PALAVRAS_SEM_PONTUACAO and not re.search(r"[.!?,;:]", texto):
            alertas.append({"tipo": "sem_pontuacao", "inicio": seg["inicio"],
                            "detalhe": f"{len(palavras)} palavras sem pontuação"})
        duracao = max(seg["fim"] - seg["inicio"], 0.001)
        if len(palavras) >= 12 and len(palavras) / duracao > MAX_PALAVRAS_POR_SEGUNDO:
            alertas.append({"tipo": "velocidade", "inicio": seg["inicio"],
                            "detalhe": f"{len(palavras) / duracao:.1f} palavras por segundo (alto demais)"})
    return limpos, alertas
