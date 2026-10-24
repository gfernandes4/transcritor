"""Comandos `transcritor vozes ...` (carregados só quando usados)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from .. import busca, exportar
from ..nucleo.audio import listar_audios
from ..transcricao import Transcricao
from . import identificar, identificar_arquivo, perfis
from .embedding import MODELOS, ErroVoz, Extrator, baixar_modelo
from .perfis import normalizar


def _extrator(args) -> Extrator:
    try:
        return Extrator(args.modelo or identificar.configuracao()["modelo"])
    except ErroVoz as exc:
        sys.exit(str(exc))


def baixar(args) -> None:
    for nome in ([args.nome] if args.nome else ["campp"]):
        print(f"Baixando o modelo '{nome}' ({MODELOS[nome]}) e conferindo o SHA-256...")
        print("Pronto:", baixar_modelo(nome))


def cadastrar(args) -> None:
    extrator = _extrator(args)
    arquivos: list[Path] = []
    for a in args.arquivos:
        arquivos += listar_audios(a)
    novos = perfis.cadastrar(args.nome, arquivos, extrator)
    print(f"{args.nome}: {len(novos)} amostra(s) nova(s) de {len(arquivos)} arquivo(s) (as repetidas foram ignoradas).")


def listar(_args) -> None:
    linhas = perfis.listar()
    if not linhas:
        print("Nenhuma voz cadastrada. Use: transcritor vozes cadastrar <nome> <arquivos>")
    for l in linhas:
        print(f"{l['nome']}: {l['amostras']} amostra(s) (modelo {l['modelo']})")
    cfg = identificar.configuracao()
    print(f"\nEm uso: modelo {cfg['modelo']}, limiar {cfg['limiar']}, margem {cfg['margem']}")


def remover(args) -> None:
    print(f"{perfis.remover(args.nome)} amostra(s) removida(s) de {args.nome}.")


def testar(args) -> None:
    extrator = _extrator(args)
    for a in args.arquivos:
        r = identificar_arquivo(a, extrator)
        quem = r.nome or "desconhecido"
        dica = f" (mais parecida com {r.melhor})" if r.nome is None and r.melhor else ""
        print(f"{Path(a).name}: {quem}{dica}  similaridade {r.confianca:.2f}, margem {r.margem:.2f}")


def _carregar_rotulos(pasta: Path, caminho: Path) -> dict[str, str]:
    bruto = json.loads(caminho.read_text(encoding="utf-8-sig"))
    rotulos = {nome: pessoa for nome, pessoa in bruto.items() if (pasta / nome).exists()}
    faltando = sorted(set(bruto) - set(rotulos))
    if faltando:
        print(f"Aviso: {len(faltando)} arquivo(s) do rótulo não estão na pasta (ex.: {faltando[0]}).", file=sys.stderr)
    return rotulos


def avaliar(args) -> None:
    pasta = Path(args.pasta)
    rotulos = _carregar_rotulos(pasta, Path(args.rotulos))
    if len(rotulos) < 4:
        sys.exit("Poucos áudios rotulados para avaliar.")
    extrator = _extrator(args)
    print(f"Modelo {extrator.nome}: calculando a voz de {len(rotulos)} áudios...")
    vetores = {nome: extrator.do_arquivo(pasta / nome) for nome in rotulos}
    resultados = identificar.avaliar_sem_um(vetores, rotulos)
    linhas = identificar.varrer(resultados)
    escolha = identificar.escolher(linhas)

    por_pessoa: dict[str, list[float]] = {}
    for r in resultados:
        por_pessoa.setdefault(r["verdadeiro"], []).append(r["score"] if r["melhor"] == r["verdadeiro"] else -r["score"])
    sem_filtro = sum(1 for r in resultados if r["melhor"] == r["verdadeiro"])
    print(f"\nSem nenhum limiar (sempre dá um nome): {sem_filtro}/{len(resultados)} certos ({sem_filtro / len(resultados):.0%}).")
    erros = [r for r in resultados if r["melhor"] != r["verdadeiro"]]
    for r in sorted(erros, key=lambda r: -r["score"])[:10]:
        print(f"  errou: {r['arquivo']} era {r['verdadeiro']}, deu {r['melhor']} (sim. {r['score']:.2f}, margem {r['margem']:.2f})")
    certos = sorted(r["score"] for r in resultados if r["melhor"] == r["verdadeiro"])
    errados = sorted(r["score"] for r in erros)
    if certos:
        print(f"  similaridade dos acertos: de {certos[0]:.2f} a {certos[-1]:.2f}; dos erros: {', '.join(f'{x:.2f}' for x in errados) or 'nenhum'}")

    total = len(resultados)
    notas_fora: list[float] = []
    if args.desconhecidos:
        arquivos_fora: list[Path] = []
        for a in args.desconhecidos:
            arquivos_fora += listar_audios(a)
        todos = {pessoa: normalizar(np.mean([vetores[n] for n, p in rotulos.items() if p == pessoa], axis=0))
                 for pessoa in set(rotulos.values())}
        notas_fora = [identificar.pontuar(extrator.do_arquivo(a), todos)[0][1] for a in arquivos_fora]
        print(f"\nVozes de fora do cadastro ({len(notas_fora)} áudios): melhor similaridade de {min(notas_fora):.2f} a {max(notas_fora):.2f}.")
    cal = identificar.calibrar(resultados, notas_fora)
    if cal:
        escolha = {"limiar": cal["limiar"], "margem": cal["margem"]}
        print(f"\nNenhum dos {total} áudios foi confundido com a outra pessoa; o pior acerto tem similaridade {cal['pior_certo']:.2f} e a menor folga para a outra pessoa é {cal['folga']:.2f}.")
        if cal["validado"]:
            print(f"Calibração: limiar {cal['limiar']} (entre {cal['maior_desconhecido']:.2f} das vozes de fora e {cal['pior_certo']:.2f} do pior acerto), margem {cal['margem']}.")
        else:
            print(f"Calibração provisória: limiar {cal['limiar']}, margem {cal['margem']}. Sem vozes de fora para conferir; use --desconhecidos <áudios de outras pessoas>.")
    elif escolha is None:
        print("\nNão existe limiar sem erro de pessoa para este modelo nestes áudios.")
        return
    else:
        print(f"\nAs faixas se misturam. Melhor combinação sem errar a pessoa: limiar {escolha['limiar']}, margem {escolha['margem']} -> "
              f"{escolha['acertos']}/{total} certos ({escolha['acertos'] / total:.0%}), {escolha['desconhecidos']} 'desconhecido', {escolha['erros']} erro(s).")
    if args.salvar:
        identificar.salvar_configuracao(extrator.nome, escolha["limiar"], escolha["margem"])
        print("Configuração salva em ~/.transcritor/vozes.json.")
    if args.cadastrar:
        for pessoa in sorted(set(rotulos.values())):
            arquivos = [pasta / n for n, p in rotulos.items() if p == pessoa]
            novos = perfis.cadastrar(pessoa, arquivos, extrator)
            print(f"Cadastrado: {pessoa} ({len(novos)} amostras novas, {len(arquivos)} arquivos)")


def aplicar(args) -> None:
    """Identifica a voz de cada áudio e grava o falante nas transcrições que já existem."""
    pasta_audios, pasta_trans = Path(args.pasta_audios), Path(args.transcricoes)
    extrator = _extrator(args)
    cfg = identificar.configuracao()
    todos = perfis.perfis(extrator.nome)
    if not todos:
        sys.exit("Nenhuma voz cadastrada para este modelo. Use `vozes cadastrar` ou `vozes avaliar --cadastrar`.")
    contagem: dict[str, int] = {}
    for audio in listar_audios(pasta_audios):
        caminho_json = pasta_trans / f"{audio.stem}.json"
        if not caminho_json.exists():
            continue
        r = identificar.decidir(extrator.do_arquivo(audio), todos, cfg["limiar"], cfg["margem"])
        t = Transcricao.de_dict(json.loads(caminho_json.read_text(encoding="utf-8")))
        t.falante = {"nome": r.nome, "confianca": round(r.confianca, 3)} if r.nome else None
        t.alertas = [a for a in t.alertas if a["tipo"] != "voz_desconhecida"]
        if not r.nome:
            t.alertas.append({"tipo": "voz_desconhecida", "inicio": 0.0,
                              "detalhe": f"voz não identificada (mais parecida com {r.melhor}, similaridade {r.confianca:.2f})"})
        formatos = [f for f in exportar.FORMATOS if (pasta_trans / f"{audio.stem}.{f}").exists()]
        t.salvar(pasta_trans, formatos)
        busca.indexar(t, caminho_json)
        contagem[r.nome or "desconhecido"] = contagem.get(r.nome or "desconhecido", 0) + 1
    print("Falantes gravados:", ", ".join(f"{k}: {v}" for k, v in sorted(contagem.items())) or "nenhum áudio com transcrição encontrada.")
