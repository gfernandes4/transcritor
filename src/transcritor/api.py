"""Funções para usar o transcritor em outros projetos.

    from transcritor import transcrever
    t = transcrever("audio.ogg")
    print(t.texto)
"""
from __future__ import annotations

import time
from pathlib import Path

from . import busca
from .config import IDIOMA_PADRAO, MODELO_PADRAO
from .nucleo import glossario as glossario_mod
from .nucleo.alertas import limpar_e_alertar
from .nucleo.audio import listar_audios, sha1_do_arquivo
from .nucleo.whisper import Motor, Parametros
from .transcricao import Transcricao


def transcrever(
    caminho: str | Path,
    *,
    glossario: list[str] | str | Path | None = None,
    modelo: str = MODELO_PADRAO,
    idioma: str | None = IDIOMA_PADRAO,
    motor: Motor | None = None,
    parametros: Parametros | None = None,
    limpar: bool | None = None,
    bruto: bool = False,
    falantes: bool = False,
) -> Transcricao:
    """Transcreve um arquivo e devolve a `Transcricao`.

    `falantes`: identifica de quem é a voz (precisa do extra `vozes` e de vozes cadastradas).

    `glossario`: lista de termos, ou caminho de um arquivo extra (soma ao glossário do usuário).
    `motor`: reaproveite o mesmo `Motor` para vários arquivos (o modelo carrega uma vez só).
    `bruto`: comportamento da primeira versão (sem glossário, sem ajustes, sem limpeza), útil para comparar.
    `limpar`: remove loops óbvios e gera alertas. Padrão: ligado, exceto no modo bruto.
    """
    caminho = Path(caminho)
    if bruto:
        termos: list[str] = []
    elif isinstance(glossario, (str, Path)):
        termos = glossario_mod.carregar(arquivo=glossario)
    else:
        termos = glossario_mod.carregar(termos=glossario)
    if parametros is None:
        parametros = Parametros(idioma=idioma) if bruto else Parametros.melhorado(idioma)
    limpar = (not bruto) if limpar is None else limpar
    dono_do_motor = motor is None
    motor = motor or Motor(modelo)
    try:
        segmentos, duracao, idioma_detectado = motor.transcrever(caminho, parametros, termos)
    finally:
        if dono_do_motor:
            motor.descarregar()
    alertas: list[dict] = []
    if limpar:
        segmentos, alertas = limpar_e_alertar(segmentos)
    resultado = Transcricao(
        arquivo=caminho.name, duracao_s=duracao, modelo=motor.nome, idioma=idioma_detectado,
        segmentos=segmentos, glossario=termos, alertas=alertas, sha1=sha1_do_arquivo(caminho),
    )
    if falantes:
        _identificar_falante(resultado, caminho)
    return resultado


def _identificar_falante(t: Transcricao, caminho: Path) -> None:
    """Preenche `t.falante`. Se não for possível, avisa em vez de derrubar a transcrição."""
    from .vozes import ErroVoz, identificar_arquivo

    try:
        r = identificar_arquivo(caminho)
    except ErroVoz as exc:
        t.alertas.append({"tipo": "voz_nao_identificada", "inicio": 0.0, "detalhe": str(exc)})
        return
    if r.nome:
        t.falante = {"nome": r.nome, "confianca": round(r.confianca, 3)}
    else:
        t.alertas.append({"tipo": "voz_desconhecida", "inicio": 0.0,
                          "detalhe": f"voz não identificada (mais parecida com {r.melhor}, similaridade {r.confianca:.2f})"})


def transcrever_pasta(
    pasta: str | Path,
    *,
    glossario: list[str] | str | Path | None = None,
    modelo: str = MODELO_PADRAO,
    idioma: str | None = IDIOMA_PADRAO,
    limpar: bool | None = None,
    bruto: bool = False,
    ao_terminar=None,
) -> list[Transcricao]:
    """Transcreve todos os áudios de uma pasta com um único carregamento do modelo.

    `ao_terminar(indice, total, transcricao, segundos)` é chamada a cada arquivo (para mostrar progresso).
    """
    arquivos = listar_audios(pasta)
    motor = Motor(modelo)
    resultados = []
    try:
        for i, arq in enumerate(arquivos, 1):
            inicio = time.time()
            t = transcrever(arq, glossario=glossario, idioma=idioma, motor=motor, limpar=limpar, bruto=bruto)
            resultados.append(t)
            if ao_terminar:
                ao_terminar(i, len(arquivos), t, time.time() - inicio)
    finally:
        motor.descarregar()
    return resultados


buscar = busca.buscar
