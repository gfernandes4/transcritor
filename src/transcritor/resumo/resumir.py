"""Resumo de uma pasta de transcrições: o que ficou definido, o que está em aberto, tarefas e um fluxograma.

Roda sempre DEPOIS da transcrição (o Whisper já foi descarregado da GPU) e usa o Ollama local.
Textos longos são divididos em blocos; os resultados parciais são unidos e deduplicados em código.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import mermaid
from .llm import Ollama

LIMITE_CARACTERES_POR_BLOCO = 11_000  # ~3.200 tokens em português; sobra espaço para o prompt e a resposta no contexto de 8192

SISTEMA = (
    "Você lê mensagens de áudio já transcritas (conversa de trabalho) e extrai o que importa. "
    "Responda SOMENTE com JSON. Não invente nada: use só o que está no texto. "
    "O que uma pessoa apenas supõe ou ainda quer provar NÃO é 'definido': vai em 'em_aberto'. "
    "As transcrições vêm de reconhecimento de voz e podem ter erros de nomes."
)


def carregar_transcricoes(pasta: str | Path, somente: list[str | Path] | None = None) -> list[dict]:
    """Lê os .json da pasta (formato do transcritor), em ordem de nome.

    `somente`: nomes (ou caminhos) dos .json que devem entrar; os outros da pasta são ignorados.
    """
    itens = []
    permitidos = {Path(s).name for s in somente} if somente is not None else None
    for caminho in sorted(Path(pasta).glob("*.json")):
        if permitidos is not None and caminho.name not in permitidos:
            continue
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if "segmentos" in dados:
            itens.append(dados)
    return itens


def _id_curto(arquivo: str) -> str:
    """'WhatsApp Ptt 2026-10-15 at 11.24.16.ogg' -> '11.24.16'; 'Título do vídeo [abc123XYZ_-]' -> 'abc123XYZ_-'."""
    video = re.search(r"\[([\w-]{11})\]\s*$", Path(arquivo).stem)
    if video:
        return video.group(1)
    achado = re.search(r"(\d{1,2}[.:]\d{2}[.:]\d{2})", arquivo)
    return achado.group(1) if achado else Path(arquivo).stem


def contexto_de_videos(origens: list[dict]) -> str:
    """Frase para orientar o resumo quando o texto vem de vídeos e não de uma conversa."""
    nomes = "; ".join(f"\"{o.get('titulo') or o['url']}\"" + (f" ({o['canal']})" if o.get("canal") else "") for o in origens)
    return (f"O texto é a transcrição de {'um vídeo' if len(origens) == 1 else 'vídeos'} da internet: {nomes}. "
            "Não é uma conversa entre pessoas: resuma o que o vídeo explica, o que ele conclui e o que sugere fazer.")


def _cabecalho_do_audio(t: dict) -> str:
    quem = (t.get("falante") or {}).get("nome")
    return f"===== {_id_curto(t['arquivo'])}" + (f" · {quem}" if quem else "") + " ====="


def _bloco_do_audio(t: dict) -> str:
    return _cabecalho_do_audio(t) + "\n" + " ".join(s["texto"] for s in t["segmentos"])


def _partes_do_audio(t: dict, limite: int) -> list[str]:
    """Um áudio que cabe vira um bloco só. Um áudio maior que `limite` é cortado entre trechos, com o mesmo cabeçalho
    em cada parte; sem isso o Ollama descartaria em silêncio o começo do texto que não cabe no contexto."""
    inteiro = _bloco_do_audio(t)
    if len(inteiro) <= limite:
        return [inteiro]
    cabecalho = _cabecalho_do_audio(t)
    partes, atual, tamanho = [], [], len(cabecalho)
    for s in t["segmentos"]:
        if atual and tamanho + len(s["texto"]) + 1 > limite:
            partes.append(cabecalho + "\n" + " ".join(atual))
            atual, tamanho = [], len(cabecalho)
        atual.append(s["texto"])
        tamanho += len(s["texto"]) + 1
    if atual:
        partes.append(cabecalho + "\n" + " ".join(atual))
    return partes


def dividir_em_blocos(transcricoes: list[dict], limite: int = LIMITE_CARACTERES_POR_BLOCO) -> list[str]:
    """Agrupa áudios inteiros em blocos de até `limite` caracteres; um áudio maior que o limite é cortado em partes."""
    blocos, atual, tamanho = [], [], 0
    for t in transcricoes:
        for texto in _partes_do_audio(t, limite):
            if atual and tamanho + len(texto) > limite:
                blocos.append("\n\n".join(atual))
                atual, tamanho = [], 0
            atual.append(texto)
            tamanho += len(texto)
    if atual:
        blocos.append("\n\n".join(atual))
    return blocos


def _prompt_do_bloco(texto: str, i: int, n: int, contexto: str) -> str:
    return (
        (f"Contexto: {contexto}\n\n" if contexto else "")
        + f"Parte {i} de {n} da conversa. Cada áudio começa com ===== id · Nome =====; o Nome é quem fala nesse áudio.\n"
        "Quando o item for a posição de uma pessoa, escreva quem disse (ex.: \"Ana defende que...\"). "
        "O que só UMA pessoa afirma e a outra não confirmou é 'em_aberto', não 'definido'. "
        "'definido' é só o que as duas partes aceitam ou o que foi decidido.\n\n"
        f"{texto}\n\n"
        "Devolva um JSON com estas chaves:\n"
        '- "definido": lista de {"texto": "...", "fontes": ["id do áudio"]}. SÓ o que alguém afirma como certo ou foi decidido. '
        'Hipótese, suposição e "pode ser" NÃO entram aqui.\n'
        '- "em_aberto": lista de {"texto": "...", "fontes": ["id do áudio"]}: dúvidas, hipóteses e o que ainda não foi provado. '
        "Escreva cada dúvida uma vez só.\n"
        '- "tarefas": lista de {"texto": "...", "responsavel": "...", "fontes": ["id do áudio"]}. '
        '"responsavel" é a pessoa que vai fazer, só se o texto disser; senão use "". Quem pede a tarefa não é o responsável.\n'
        '- "pessoas": lista de {"nome": "...", "papel": "..."}. Só inclua o papel se o texto disser claramente; senão use "".\n'
        f'- "fluxo": o raciocínio desta parte em no máximo {MAX_PASSOS_DO_FLUXO_POR_BLOCO} passos curtos e em ordem, cada um '
        '{"id": "p1", "texto": "frase curta", "depois": ["p2"]}.\n'
        "Listas vazias são aceitas. Não repita o mesmo item."
    )


def _norm(texto: str) -> str:
    return re.sub(r"\W+", " ", texto.casefold()).strip()


_SEM_RESPONSAVEL = {"", "vazio", "nenhum", "ninguém", "ninguem", "n/a", "-", "—", "não informado", "desconhecido", "null", "none"}
# Frases com estas marcas são hipótese ou suposição, não fato definido.
_MARCAS_DE_HIPOTESE = ("pode ", "podem ", "talvez", "provavelmente", "possivelmente", "hipótese", "hipotese", "suposição", "suposicao", "será que")
MAX_PASSOS_DO_FLUXO_POR_BLOCO = 8


def _item(x) -> dict | None:
    """Aceita item como dict ou como texto solto e devolve {texto, fontes, ...} ou None."""
    if isinstance(x, str):
        x = {"texto": x}
    if not isinstance(x, dict) or not str(x.get("texto", "")).strip():
        return None
    x = dict(x)
    x["texto"] = " ".join(str(x["texto"]).split())
    x["fontes"] = [str(f) for f in x.get("fontes", []) if f]
    if "responsavel" in x:
        resp = " ".join(str(x["responsavel"] or "").split())
        x["responsavel"] = "" if resp.casefold() in _SEM_RESPONSAVEL else resp
    return x


def _palavras(texto: str) -> set[str]:
    return {p for p in _norm(texto).split() if len(p) > 2}


def _parecidos(a: str, b: str, limite: float = 0.6) -> bool:
    """Quase o mesmo item escrito de outro jeito (sobreposição de palavras)."""
    pa, pb = _palavras(a), _palavras(b)
    if not pa or not pb:
        return _norm(a) == _norm(b)
    return len(pa & pb) / len(pa | pb) >= limite


def _eh_hipotese(texto: str) -> bool:
    baixo = " " + texto.casefold() + " "
    return any(marca in baixo for marca in _MARCAS_DE_HIPOTESE)


def unir(parciais: list[dict]) -> dict:
    """Junta os resultados dos blocos: lista única, sem itens repetidos, fontes somadas."""
    final = {"definido": [], "em_aberto": [], "tarefas": [], "pessoas": [], "fluxo": []}
    ultimo_do_bloco_anterior = None
    for n, parcial in enumerate(parciais, 1):
        for chave in ("definido", "em_aberto", "tarefas"):
            for bruto in parcial.get(chave, []) or []:
                item = _item(bruto)
                if not item:
                    continue
                destino = chave
                if chave == "definido" and _eh_hipotese(item["texto"]):
                    destino = "em_aberto"  # "pode ser", "talvez"...: ainda não é fato
                igual = next((e for e in final[destino] if _parecidos(e["texto"], item["texto"])), None)
                if igual:
                    igual["fontes"] = sorted(set(igual["fontes"]) | set(item["fontes"]))
                    if destino == "tarefas" and not igual.get("responsavel") and item.get("responsavel"):
                        igual["responsavel"] = item["responsavel"]
                else:
                    final[destino].append(item)
        for p in parcial.get("pessoas", []) or []:
            if isinstance(p, dict) and p.get("nome") and not any(_norm(e["nome"]) == _norm(p["nome"]) for e in final["pessoas"]):
                final["pessoas"].append({"nome": str(p["nome"]), "papel": str(p.get("papel", ""))})
        # Os ids dos passos são únicos por bloco; o prefixo evita colisão entre blocos.
        passos_do_bloco = []
        for passo in (parcial.get("fluxo", []) or [])[:MAX_PASSOS_DO_FLUXO_POR_BLOCO]:
            if isinstance(passo, dict) and passo.get("id") and passo.get("texto"):
                passos_do_bloco.append({
                    "id": f"b{n}_{passo['id']}", "texto": str(passo["texto"]),
                    "depois": [f"b{n}_{d}" for d in passo.get("depois", []) or []],
                })
        if passos_do_bloco:
            # Une os blocos: o último passo do bloco anterior leva ao primeiro deste.
            if ultimo_do_bloco_anterior is not None:
                ultimo_do_bloco_anterior["depois"].append(passos_do_bloco[0]["id"])
            ultimo_do_bloco_anterior = passos_do_bloco[-1]
            final["fluxo"].extend(passos_do_bloco)
    return final


def resumir(
    transcricoes: list[dict],
    llm: Ollama,
    contexto: str = "",
    progresso=None,
) -> dict:
    """Devolve {definido, em_aberto, tarefas, pessoas, fluxo, blocos}. `llm` precisa de `gerar_json(sistema, prompt)`."""
    if not transcricoes:
        raise ValueError("Nenhuma transcrição para resumir.")
    blocos = dividir_em_blocos(transcricoes)
    parciais = []
    for i, texto in enumerate(blocos, 1):
        if progresso:
            progresso(i, len(blocos))
        parciais.append(llm.gerar_json(SISTEMA, _prompt_do_bloco(texto, i, len(blocos), contexto)))
    resultado = unir(parciais)
    resultado["blocos"] = len(blocos)
    resultado["audios"] = len(transcricoes)
    return resultado


def para_markdown(r: dict, titulo: str = "Resumo da conversa") -> str:
    def lista(itens: list[dict]) -> list[str]:
        if not itens:
            return ["- (nada encontrado)"]
        return [f"- {i['texto']}" + (f" _(áudios {', '.join(i['fontes'])})_" if i["fontes"] else "") for i in itens]

    linhas = [f"# {titulo}", "", f"Gerado por IA local a partir de {r['audios']} áudio(s). Confira antes de usar: a transcrição pode ter erros de nomes.", ""]
    if r["pessoas"]:
        linhas += ["## Pessoas citadas", ""] + [f"- **{p['nome']}**" + (f": {p['papel']}" if p["papel"] else "") for p in r["pessoas"]] + [""]
    linhas += ["## O que ficou definido", ""] + lista(r["definido"]) + [""]
    linhas += ["## Em aberto", ""] + lista(r["em_aberto"]) + [""]
    linhas += ["## Tarefas", ""]
    if r["tarefas"]:
        linhas += ["| Tarefa | Responsável | Áudios |", "|---|---|---|"]
        linhas += [f"| {t['texto']} | {t.get('responsavel') or '—'} | {', '.join(t['fontes']) or '—'} |" for t in r["tarefas"]]
    else:
        linhas.append("- (nada encontrado)")
    linhas += ["", "## Fluxograma (rascunho)", "", "```mermaid", mermaid_do_resumo(r).rstrip(), "```", ""]
    return "\n".join(linhas)


def mermaid_do_resumo(r: dict, incluir_listas: bool = False) -> str:
    """Fluxograma do raciocínio. As listas (definido, em aberto, tarefas) já estão no resumo.md;
    só entram no desenho se `incluir_listas` for verdadeiro, porque deixam o gráfico enorme."""
    if not incluir_listas:
        return mermaid.renderizar(r["fluxo"], [], [], [])
    return mermaid.renderizar(
        r["fluxo"], [i["texto"] for i in r["definido"]], [i["texto"] for i in r["em_aberto"]], [i["texto"] for i in r["tarefas"]],
    )


def resumir_pasta(pasta: str | Path, saida: str | Path | None = None, modelo: str = "llama3.1:8b",
                  url: str | None = None, contexto: str = "", progresso=None, somente: list[str | Path] | None = None,
                  modo: str | None = None) -> Path:
    """Lê as transcrições da pasta, resume e grava o resumo. Devolve a pasta de saída.

    `somente`: resume só estes .json da pasta (útil quando a pasta já tem transcrições de outras rodadas).
    `modo`: "conversa" (definido, em aberto, tarefas, fluxograma: grava resumo.md, resumo.json e fluxo.mmd) ou "video"
    (resumo curto, passo a passo, pontos e ferramentas: grava resumo.md e resumo.json). Sem `modo`, é "video" quando
    todas as transcrições vieram de um link e "conversa" nos outros casos.
    """
    pasta = Path(pasta)
    transcricoes = carregar_transcricoes(pasta, somente)
    if not transcricoes:
        raise FileNotFoundError(f"Nenhuma transcrição .json em {pasta}. Rode `transcritor transcrever` primeiro.")
    if modo not in (None, "auto", "conversa", "video"):
        raise ValueError(f"Modo de resumo desconhecido: {modo}. Use auto, conversa ou video.")
    if modo in (None, "auto"):
        modo = "video" if all(t.get("origem") for t in transcricoes) else "conversa"
    llm = Ollama(modelo, url)
    if not llm.disponivel():
        raise RuntimeError(f"O Ollama não responde em {llm.url}. Inicie o Ollama e tente de novo.")
    try:
        if modo == "video":
            from .video import para_markdown_video, resumir_videos

            resultado = resumir_videos(transcricoes, llm, progresso=progresso)
            markdown = para_markdown_video(resultado)
        else:
            resultado = resumir(transcricoes, llm, contexto=contexto, progresso=progresso)
            markdown = para_markdown(resultado)
    finally:
        llm.descarregar()
    saida = Path(saida) if saida else pasta / "resumo"
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "resumo.md").write_text(markdown, encoding="utf-8")
    (saida / "resumo.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    if modo == "video":
        (saida / "fluxo.mmd").unlink(missing_ok=True)   # sobra de uma rodada antiga em modo conversa
    else:
        (saida / "fluxo.mmd").write_text(mermaid_do_resumo(resultado), encoding="utf-8")
    return saida
