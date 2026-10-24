"""Decide de quem é a voz e mede o quanto dá para confiar nessa decisão."""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from ..config import home
from .embedding import MODELO_PADRAO_VOZ
from .perfis import normalizar

LIMIAR_PADRAO = 0.45   # valores calibrados de verdade são gravados por `transcritor vozes avaliar --salvar`
MARGEM_PADRAO = 0.05


@dataclass
class Resultado:
    nome: str | None          # None = "desconhecido"
    confianca: float          # similaridade (cosseno) com a pessoa mais parecida
    melhor: str | None        # pessoa mais parecida, mesmo quando não passou do limiar
    margem: float             # diferença para a segunda mais parecida


def configuracao() -> dict:
    """Modelo, limiar e margem em uso (arquivo ~/.transcritor/vozes.json, se existir)."""
    padrao = {"modelo": MODELO_PADRAO_VOZ, "limiar": LIMIAR_PADRAO, "margem": MARGEM_PADRAO}
    caminho = home() / "vozes.json"
    if caminho.exists():
        try:
            padrao.update(json.loads(caminho.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return padrao


def salvar_configuracao(modelo: str, limiar: float, margem: float) -> None:
    (home() / "vozes.json").write_text(
        json.dumps({"modelo": modelo, "limiar": round(limiar, 3), "margem": round(margem, 3)}, indent=2), encoding="utf-8")


def pontuar(vetor: np.ndarray, perfis: dict[str, np.ndarray]) -> list[tuple[str, float]]:
    """Similaridade (cosseno) do vetor com cada perfil, da maior para a menor."""
    return sorted(((nome, float(np.dot(vetor, p))) for nome, p in perfis.items()), key=lambda x: x[1], reverse=True)


def decidir(vetor: np.ndarray, perfis: dict[str, np.ndarray], limiar: float, margem: float) -> Resultado:
    """Só dá um nome quando a similaridade passa do limiar E a segunda opção está longe o bastante."""
    if not perfis:
        return Resultado(None, 0.0, None, 0.0)
    ordem = pontuar(vetor, perfis)
    melhor_nome, melhor = ordem[0]
    diferenca = melhor - ordem[1][1] if len(ordem) > 1 else melhor
    aceito = melhor >= limiar and diferenca >= margem
    return Resultado(melhor_nome if aceito else None, melhor, melhor_nome, diferenca)


def avaliar_sem_um(embeddings: dict[str, np.ndarray], rotulos: dict[str, str]) -> list[dict]:
    """Validação leave-one-out: cada áudio é identificado usando só os OUTROS como cadastro."""
    resultados = []
    for chave, vetor in embeddings.items():
        verdadeiro = rotulos[chave]
        por_nome: dict[str, list[np.ndarray]] = {}
        for outra, v in embeddings.items():
            if outra != chave:
                por_nome.setdefault(rotulos[outra], []).append(v)
        if verdadeiro not in por_nome:
            continue  # essa pessoa só tem este áudio: não dá para testar
        perfis = {nome: normalizar(np.mean(vs, axis=0)) for nome, vs in por_nome.items()}
        ordem = pontuar(vetor, perfis)
        notas = dict(ordem)
        outras = [s for nome, s in ordem if nome != verdadeiro]
        resultados.append({
            "arquivo": chave, "verdadeiro": verdadeiro, "melhor": ordem[0][0], "score": ordem[0][1],
            "margem": ordem[0][1] - (ordem[1][1] if len(ordem) > 1 else 0.0),
            "score_certo": notas[verdadeiro], "score_outro": max(outras) if outras else 0.0,
        })
    return resultados


FOLGA_SEM_DESCONHECIDOS = 0.05


def calibrar(resultados: list[dict], desconhecidos: list[float] | None = None) -> dict | None:
    """Limiar e margem a partir dos acertos do leave-one-out. Só existe se ninguém foi confundido com outra pessoa.

    A margem é metade da menor folga entre o acerto e a segunda opção. Quem decide se uma voz de fora do cadastro
    é barrada é o limiar: com `desconhecidos` (a melhor similaridade de áudios de outras pessoas) ele fica no meio
    entre a maior delas e o pior acerto, e é None se as faixas se tocam. Sem exemplos de fora, fica um pouco abaixo
    do pior acerto, o que é só um palpite (`validado` = False).
    """
    if not resultados or any(r["melhor"] != r["verdadeiro"] for r in resultados):
        return None
    pior_certo = min(r["score_certo"] for r in resultados)
    folga = min(r["score_certo"] - r["score_outro"] for r in resultados)
    margem = round(min(0.15, folga / 2), 3)
    if desconhecidos:
        maior_desconhecido = max(desconhecidos)
        if maior_desconhecido >= pior_certo:
            return None
        limiar = (pior_certo + maior_desconhecido) / 2
    else:
        maior_desconhecido = None
        limiar = pior_certo - FOLGA_SEM_DESCONHECIDOS
    return {"limiar": round(limiar, 3), "margem": margem, "pior_certo": pior_certo, "folga": folga,
            "maior_desconhecido": maior_desconhecido, "validado": bool(desconhecidos)}


def varrer(resultados: list[dict], limiares=None, margens=(0.0, 0.02, 0.05, 0.08, 0.1)) -> list[dict]:
    """Para cada par (limiar, margem): quantos acertos, erros de pessoa e "desconhecidos"."""
    limiares = limiares if limiares is not None else [round(x, 2) for x in np.arange(0.10, 0.95, 0.025)]
    linhas = []
    for limiar in limiares:
        for margem in margens:
            acertos = erros = desconhecidos = 0
            for r in resultados:
                if r["score"] >= limiar and r["margem"] >= margem:
                    if r["melhor"] == r["verdadeiro"]:
                        acertos += 1
                    else:
                        erros += 1
                else:
                    desconhecidos += 1
            linhas.append({"limiar": limiar, "margem": margem, "acertos": acertos, "erros": erros, "desconhecidos": desconhecidos})
    return linhas


def escolher(linhas: list[dict]) -> dict | None:
    """Entre os pares sem nenhum erro de pessoa, o que tem mais acertos; no empate, o do meio da faixa
    (mais folga dos dois lados do que o primeiro limiar que funciona)."""
    sem_erro = [l for l in linhas if l["erros"] == 0]
    if not sem_erro:
        return None
    melhor = max(l["acertos"] for l in sem_erro)
    empatados = sorted((l for l in sem_erro if l["acertos"] == melhor), key=lambda l: (l["limiar"], l["margem"]))
    return empatados[len(empatados) // 2]
