"""Comando `transcritor`."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import busca, exportar
from .api import transcrever, transcrever_url
from .config import IDIOMA_PADRAO, MODELO_PADRAO
from .nucleo import glossario as gl
from .nucleo import youtube
from .nucleo.audio import listar_audios
from .nucleo.whisper import Motor
from .transcricao import formatar_tempo


def cmd_transcrever(args: argparse.Namespace) -> None:
    arquivos: list[Path] = []
    links: list[str] = []
    for item in args.entrada:
        if youtube.eh_url(item):
            links.append(item.strip())
            continue
        try:
            arquivos += listar_audios(Path(item))
        except FileNotFoundError as exc:
            sys.exit(str(exc))
    if not arquivos and not links:
        sys.exit(f"Nenhum áudio encontrado em {', '.join(args.entrada)}")
    if links and not youtube.disponivel():
        sys.exit('Para transcrever links, instale o extra: pip install "transcritor[youtube]"')
    formatos = [f.strip() for f in args.formatos.split(",") if f.strip()]
    for f in formatos:
        if f not in exportar.FORMATOS:
            sys.exit(f"Formato desconhecido: {f}. Use: {', '.join(exportar.FORMATOS)}")
    if "json" not in formatos:
        formatos.append("json")  # o JSON alimenta a busca e o resumo
    if args.saida:
        saida = Path(args.saida)
    elif len(args.entrada) == 1 and not links:
        entrada = Path(args.entrada[0])
        saida = (entrada if entrada.is_dir() else entrada.parent) / "transcricoes"
    else:
        saida = Path.cwd() / "transcricoes"

    glossario = args.glossario or None
    total = len(arquivos) + len(links)
    motor = Motor(args.modelo, forcar_cpu=args.cpu)
    completo, jsons, origens, falhas = [], [], [], []
    print(f"Modelo {args.modelo}: carregando e transcrevendo {total} item(ns)...", flush=True)

    def concluir(i: int, t, inicio: float) -> None:
        gravados = t.salvar(saida, formatos)
        json_path = next(p for p in gravados if p.suffix == ".json")
        jsons.append(json_path)
        if t.origem:
            origens.append(t.origem)
        if not args.sem_indexar:
            busca.indexar(t, json_path)
        completo.append(f"===== {t.arquivo} ({formatar_tempo(t.duracao_s)}) =====\n{t.texto}\n")
        extra = f", {len(t.alertas)} alerta(s)" if t.alertas else ""
        print(f"[{i}/{total}] {t.arquivo}: {formatar_tempo(t.duracao_s)} de áudio em {time.time() - inicio:.0f}s{extra}", flush=True)

    def etapa(nome: str, detalhe: str) -> None:
        print(("  baixando o áudio de " if nome == "baixando" else "  transcrevendo: ") + detalhe, flush=True)

    try:
        for i, arq in enumerate(arquivos, 1):
            inicio = time.time()
            concluir(i, transcrever(arq, glossario=glossario, idioma=args.idioma, motor=motor, bruto=args.bruto, falantes=args.falantes), inicio)
        for i, url in enumerate(links, len(arquivos) + 1):
            inicio = time.time()
            try:
                t = transcrever_url(url, glossario=glossario, idioma=args.idioma, motor=motor, bruto=args.bruto, ao_etapa=etapa)
            except youtube.ErroDownload as exc:
                falhas.append(url)
                print(f"[{i}/{total}] {url}: {exc}", file=sys.stderr, flush=True)
                continue
            concluir(i, t, inicio)
    finally:
        motor.descarregar()
    if not jsons:
        sys.exit("Nenhum item foi transcrito.")
    if len(jsons) > 1:
        (saida / "transcricao_completa.txt").write_text("\n".join(completo), encoding="utf-8")
    print(f"Pronto. Arquivos em: {saida}")
    if args.resumir:
        from .resumo import contexto_de_videos, resumir_pasta  # módulo opcional

        contexto = args.contexto or (contexto_de_videos(origens) if len(origens) == len(jsons) else "")
        print("Resumindo (o Whisper já saiu da GPU)...", flush=True)
        try:
            pasta_resumo = resumir_pasta(saida, modelo=args.modelo_llm, url=args.ollama, contexto=contexto, somente=jsons,
                                         progresso=lambda i, n: print(f"  bloco {i} de {n}...", flush=True))
        except (RuntimeError, FileNotFoundError) as exc:
            sys.exit(f"As transcrições estão salvas, mas o resumo falhou: {exc}")
        print(f"Resumo em: {pasta_resumo}")
    if falhas:
        sys.exit(f"{len(falhas)} link(s) não foram transcritos.")


def cmd_glossario(args: argparse.Namespace) -> None:
    if args.acao == "listar":
        for termo in gl.listar():
            print(termo)
        print(f"\n({len(gl.listar())} termos em {gl.garantir_arquivo()})")
    elif args.acao == "add":
        for termo in args.termos:
            print(f"{'adicionado' if gl.adicionar(termo) else 'já existia'}: {termo}")
    elif args.acao == "remover":
        for termo in args.termos:
            print(f"{'removido' if gl.remover(termo) else 'não estava no glossário'}: {termo}")
    elif args.acao == "sugerir":
        textos = []
        for arq in Path(args.termos[0]).glob("*.json"):
            dados = json.loads(arq.read_text(encoding="utf-8"))
            textos += [s["texto"] for s in dados.get("segmentos", [])]
        sugestoes = gl.sugerir(textos, minimo=2)
        if not sugestoes:
            print("Nenhuma sugestão nova.")
        for palavra, n in sugestoes[:40]:
            print(f"{palavra}  ({n}x)   -> transcritor glossario add \"{palavra}\"")


def cmd_buscar(args: argparse.Namespace) -> None:
    resultados = busca.buscar(" ".join(args.consulta), falante=args.falante, limite=args.limite)
    if not resultados:
        print("Nada encontrado.")
    for r in resultados:
        quem = f" ({r['falante']})" if r["falante"] else ""
        print(f"{r['arquivo']} [{formatar_tempo(r['inicio'])}]{quem}\n    {r['texto']}")


def cmd_resumir(args: argparse.Namespace) -> None:
    from .resumo import resumir_pasta  # módulo opcional: só carrega se for usado

    def progresso(i: int, n: int) -> None:
        print(f"Resumindo bloco {i} de {n}...", flush=True)

    saida = resumir_pasta(args.pasta, saida=args.saida, modelo=args.modelo_llm, url=args.ollama,
                          contexto=args.contexto, progresso=progresso)
    print(f"Pronto. Resumo em: {saida}\\resumo.md (fluxograma em fluxo.mmd)")


def cmd_vozes(args: argparse.Namespace) -> None:
    from .vozes import comandos  # módulo opcional

    funcoes = {"baixar-modelo": comandos.baixar, "cadastrar": comandos.cadastrar, "listar": comandos.listar,
               "remover": comandos.remover, "testar": comandos.testar, "avaliar": comandos.avaliar, "aplicar": comandos.aplicar}
    funcoes[args.acao](args)


def cmd_web(args: argparse.Namespace) -> None:
    try:
        from .web import servir
    except ImportError:
        sys.exit("A interface web precisa do extra: pip install \"transcritor[web]\"")
    print(f"Interface em http://127.0.0.1:{args.porta} (Ctrl+C para parar)")
    servir(args.porta)


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="transcritor", description="Transcritor local de áudios.")
    sub = ap.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("transcrever", help="transcreve um arquivo ou uma pasta de áudios")
    p.add_argument("entrada", nargs="+", help="arquivo, pasta ou link de vídeo (YouTube etc.); pode misturar")
    p.add_argument("--saida", help="pasta de saída (padrão: <entrada>/transcricoes; com links, ./transcricoes)")
    p.add_argument("--resumir", action="store_true", help="depois de transcrever, resume com o Ollama (precisa estar aberto)")
    p.add_argument("--modelo-llm", default="llama3.1:8b", help="modelo do Ollama usado em --resumir")
    p.add_argument("--ollama", help="endereço do Ollama (padrão: http://localhost:11434)")
    p.add_argument("--contexto", default="", help="uma frase sobre o conteúdo, para orientar o resumo")
    p.add_argument("--formatos", default="txt,md,json", help=f"separados por vírgula: {', '.join(exportar.FORMATOS)}")
    p.add_argument("--glossario", help="arquivo extra de termos (soma ao glossário do usuário)")
    p.add_argument("--modelo", default=MODELO_PADRAO)
    p.add_argument("--idioma", default=IDIOMA_PADRAO)
    p.add_argument("--cpu", action="store_true", help="não usar a GPU")
    p.add_argument("--bruto", action="store_true", help="sem glossário, ajustes e limpeza (comportamento da primeira versão)")
    p.add_argument("--sem-indexar", action="store_true", help="não gravar no índice de busca")
    p.add_argument("--falantes", action="store_true", help="identifica quem fala (precisa das vozes cadastradas)")
    p.set_defaults(funcao=cmd_transcrever)

    p = sub.add_parser("glossario", help="gerencia o glossário de nomes e termos")
    p.add_argument("acao", choices=["listar", "add", "remover", "sugerir"])
    p.add_argument("termos", nargs="*", help="termos (add/remover) ou a pasta de transcrições (sugerir)")
    p.set_defaults(funcao=cmd_glossario)

    p = sub.add_parser("buscar", help="procura um texto em todas as transcrições")
    p.add_argument("consulta", nargs="+")
    p.add_argument("--falante")
    p.add_argument("--limite", type=int, default=20)
    p.set_defaults(funcao=cmd_buscar)

    p = sub.add_parser("resumir", help="resume uma pasta de transcrições (definido, em aberto, tarefas, fluxograma)")
    p.add_argument("pasta", help="pasta com os .json gerados por `transcrever`")
    p.add_argument("--saida", help="pasta de saída (padrão: <pasta>/resumo)")
    p.add_argument("--modelo-llm", default="llama3.1:8b", help="modelo do Ollama")
    p.add_argument("--ollama", help="endereço do Ollama (padrão: http://localhost:11434)")
    p.add_argument("--contexto", default="", help="uma frase sobre a conversa, para orientar o resumo")
    p.set_defaults(funcao=cmd_resumir)

    p = sub.add_parser("vozes", help="identifica quem fala em cada áudio (módulo opcional)")
    acoes = p.add_subparsers(dest="acao", required=True)
    a = acoes.add_parser("baixar-modelo", help="baixa o modelo de voz e confere o SHA-256")
    a.add_argument("nome", nargs="?", choices=["campp"])
    a = acoes.add_parser("cadastrar", help="cadastra a voz de uma pessoa com alguns áudios dela")
    a.add_argument("nome")
    a.add_argument("arquivos", nargs="+", help="arquivos ou pastas")
    acoes.add_parser("listar", help="vozes cadastradas e a calibração em uso")
    a = acoes.add_parser("remover", help="apaga as amostras de uma pessoa")
    a.add_argument("nome")
    a = acoes.add_parser("testar", help="mostra de quem é a voz de cada arquivo")
    a.add_argument("arquivos", nargs="+")
    a = acoes.add_parser("avaliar", help="mede a precisão com áudios rotulados (leave-one-out) e calibra o limiar")
    a.add_argument("pasta", help="pasta com os áudios")
    a.add_argument("rotulos", help="JSON {\"arquivo.ogg\": \"Nome\"}")
    a.add_argument("--salvar", action="store_true", help="grava o limiar e a margem escolhidos")
    a.add_argument("--cadastrar", action="store_true", help="cadastra todos os áudios rotulados")
    a.add_argument("--desconhecidos", nargs="+", help="áudios de OUTRAS pessoas, para o limiar barrar quem não está no cadastro")
    a = acoes.add_parser("aplicar", help="grava o falante nas transcrições que já existem")
    a.add_argument("pasta_audios")
    a.add_argument("--transcricoes", required=True, help="pasta com os .json das transcrições")
    for nome_acao in ("cadastrar", "testar", "avaliar", "aplicar"):
        acoes.choices[nome_acao].add_argument("--modelo", choices=["campp"], help="modelo de voz (padrão: o da configuração)")
    p.set_defaults(funcao=cmd_vozes)

    p = sub.add_parser("web", help="abre a interface web (só neste computador)")
    p.add_argument("--porta", type=int, default=8800)
    p.set_defaults(funcao=cmd_web)

    args = ap.parse_args(argv)
    if args.comando == "glossario" and args.acao in ("add", "remover", "sugerir") and not args.termos:
        ap.error("informe o(s) termo(s)" if args.acao != "sugerir" else "informe a pasta de transcrições")
    args.funcao(args)


if __name__ == "__main__":
    main()
