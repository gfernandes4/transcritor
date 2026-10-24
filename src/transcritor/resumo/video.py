"""Resumo de vídeos explicativos (aulas, tutoriais): resumo curto, passo a passo, pontos principais e ferramentas.

O resumo de conversa (definido, em aberto, tarefas) não serve para um vídeo: um tutorial não tem tarefas nem
posições em disputa. Aqui cada vídeo é lido em partes (um texto longo não cabe de uma vez no contexto do modelo),
e os resultados das partes são unidos em código, sem repetir itens.
"""
from __future__ import annotations

import difflib
import re

from ..transcricao import formatar_tempo
from .llm import Ollama
from .resumir import _norm, _parecidos

LIMITE_CARACTERES_POR_PARTE = 9_000   # com os horários, ~2.800 tokens: sobra espaço para o prompt e a resposta em 8192
MAX_PONTOS = 10
MAX_PASSOS_POR_PARTE = 6

SISTEMA_VIDEO = (
    "Você lê a transcrição de um vídeo explicativo (aula, tutorial ou apresentação) e extrai o conteúdo. "
    "Responda SOMENTE com JSON. Não invente nada: use só o que está no texto. "
    "A transcrição vem de reconhecimento de voz e pode errar nomes de ferramentas, marcas e pessoas."
)

_HORA = re.compile(r"^\d{2}:\d{2}:\d{2}$")


def dividir_em_partes(transcricao: dict, limite: int = LIMITE_CARACTERES_POR_PARTE) -> list[str]:
    """Quebra o texto do vídeo em partes de até `limite` caracteres, sempre entre dois trechos e com o horário de cada um."""
    partes, atual, tamanho = [], [], 0
    for s in transcricao["segmentos"]:
        linha = f"[{formatar_tempo(s['inicio'])}] {s['texto']}"
        if atual and tamanho + len(linha) > limite:
            partes.append("\n".join(atual))
            atual, tamanho = [], 0
        atual.append(linha)
        tamanho += len(linha) + 1
    if atual:
        partes.append("\n".join(atual))
    return partes


def _prompt_da_parte(texto: str, i: int, n: int, origem: dict) -> str:
    titulo = origem.get("titulo") or "sem título"
    canal = f" ({origem['canal']})" if origem.get("canal") else ""
    return (
        f'Parte {i} de {n} do vídeo "{titulo}"{canal}. Cada linha começa com o horário [hh:mm:ss].\n\n{texto}\n\n'
        "Devolva um JSON com estas chaves:\n"
        '- "resumo": 2 a 3 frases dizendo o que esta parte explica.\n'
        '- "passos": lista de {"texto": "ação curta no imperativo, por exemplo: Abra o site e crie um projeto", "minuto": "hh:mm:ss"}. '
        f"Só o que o vídeo manda fazer, na ordem em que aparece, no máximo {MAX_PASSOS_POR_PARTE} passos: junte ações miúdas "
        "(digitar, colar, apertar Enter, esperar) no passo maior a que pertencem. Não repita um passo.\n"
        '- "pontos": lista de frases curtas com as ideias, dicas e avisos mais importantes desta parte (o que não é um passo).\n'
        '- "ferramentas": lista de {"nome": "...", "para_que": "uma frase"} com os programas, sites e modelos de IA citados nesta parte. '
        "Escreva o nome como o vídeo fala; se parecer erro de reconhecimento de voz de um nome que você conhece com certeza, escreva o nome correto.\n"
        "Listas vazias são aceitas."
    )


def _texto(x) -> str:
    return " ".join(str(x or "").split())


def _mesmo_nome(a: str, b: str) -> bool:
    """'Nano Banana Pro' e 'NanoBanana Pro' são o mesmo nome; 'Grok' e 'Grock' (erro de reconhecimento de voz) também.
    Compara sem espaços nem acentos e aceita uma diferença pequena."""
    sem_espaco = lambda s: re.sub(r"\s+", "", _norm(s))  # noqa: E731
    x, y = sem_espaco(a), sem_espaco(b)
    return x == y or (min(len(x), len(y)) >= 4 and difflib.SequenceMatcher(None, x, y).ratio() >= 0.85)


def unir_partes(parciais: list[dict]) -> dict:
    """Junta as partes de um vídeo: passos em ordem, sem repetição; pontos sem repetição; ferramentas por nome."""
    passos, pontos, ferramentas, resumos = [], [], [], []
    for p in parciais:
        r = _texto(p.get("resumo"))
        if r:
            resumos.append(r)
        for bruto in p.get("passos", []) or []:
            eh_dict = isinstance(bruto, dict)
            item = {"texto": _texto(bruto.get("texto") if eh_dict else bruto), "minuto": _texto(bruto.get("minuto")) if eh_dict else ""}
            if item["texto"] and not any(_parecidos(e["texto"], item["texto"]) for e in passos):
                item["minuto"] = item["minuto"] if _HORA.match(item["minuto"]) else ""
                passos.append(item)
        for bruto in p.get("pontos", []) or []:
            texto = _texto(bruto.get("texto") if isinstance(bruto, dict) else bruto)
            if texto and not any(_parecidos(e, texto) for e in pontos):
                pontos.append(texto)
        for bruto in p.get("ferramentas", []) or []:
            if isinstance(bruto, str):
                bruto = {"nome": bruto}
            if not isinstance(bruto, dict):
                continue
            nome, para_que = _texto(bruto.get("nome")), _texto(bruto.get("para_que"))
            if not nome:
                continue
            igual = next((e for e in ferramentas if _mesmo_nome(e["nome"], nome)), None)
            if igual:
                igual["para_que"] = igual["para_que"] or para_que
            else:
                ferramentas.append({"nome": nome, "para_que": para_que})
    return {"resumos_parciais": resumos, "passos": passos, "pontos": pontos[:MAX_PONTOS], "ferramentas": ferramentas}


def _resumo_final(resumos: list[str], llm: Ollama, origem: dict) -> str:
    """Uma parte: o próprio resumo. Várias: o modelo junta os resumos das partes em 3 a 5 frases."""
    if not resumos:
        return ""
    if len(resumos) == 1:
        return resumos[0]
    prompt = (f'Estes são os resumos, em ordem, das partes do vídeo "{origem.get("titulo") or "sem título"}":\n\n'
              + "\n".join(f"{i}. {r}" for i, r in enumerate(resumos, 1))
              + '\n\nJunte tudo num único resumo de 3 a 5 frases, sem repetir. Devolva um JSON: {"resumo": "..."}')
    try:
        junto = _texto(llm.gerar_json(SISTEMA_VIDEO, prompt).get("resumo"))
    except Exception:  # noqa: BLE001 - se o modelo falhar aqui, o resumo das partes ainda serve
        junto = ""
    return junto or " ".join(resumos)


def resumir_video(transcricao: dict, llm: Ollama, progresso=None, deslocamento: int = 0, total: int | None = None) -> dict:
    origem = transcricao.get("origem") or {}
    partes = dividir_em_partes(transcricao)
    parciais = []
    for i, texto in enumerate(partes, 1):
        if progresso:
            progresso(deslocamento + i, total or len(partes))
        parciais.append(llm.gerar_json(SISTEMA_VIDEO, _prompt_da_parte(texto, i, len(partes), origem)))
    unido = unir_partes(parciais)
    return {
        "titulo": origem.get("titulo") or transcricao.get("arquivo", ""), "canal": origem.get("canal", ""), "url": origem.get("url", ""),
        "duracao_s": transcricao.get("duracao_s", 0), "partes": len(partes),
        "resumo": _resumo_final(unido["resumos_parciais"], llm, origem),
        "passos": unido["passos"], "pontos": unido["pontos"], "ferramentas": unido["ferramentas"],
    }


def resumir_videos(transcricoes: list[dict], llm: Ollama, progresso=None) -> dict:
    """Devolve {modo: "video", videos: [...], audios, blocos}. `llm` precisa de `gerar_json(sistema, prompt)`."""
    if not transcricoes:
        raise ValueError("Nenhuma transcrição para resumir.")
    total = sum(len(dividir_em_partes(t)) for t in transcricoes)
    videos, feitas = [], 0
    for t in transcricoes:
        v = resumir_video(t, llm, progresso, deslocamento=feitas, total=total)
        feitas += v["partes"]
        videos.append(v)
    return {"modo": "video", "videos": videos, "audios": len(transcricoes), "blocos": total}


def _curto(hora: str) -> str:
    """'00:05:12' -> '05:12'; '01:02:03' continua igual."""
    return hora[3:] if hora.startswith("00:") else hora


def para_markdown_video(r: dict) -> str:
    unico = len(r["videos"]) == 1
    nivel = "##" if unico else "###"
    linhas = ["# Resumo do vídeo" if unico else "# Resumo dos vídeos", "",
              "Gerado por IA local. Confira antes de usar: a transcrição pode ter erros de nomes de ferramentas.", ""]
    for v in r["videos"]:
        if not unico:
            linhas += [f"## {v['titulo']}", ""]
        origem = [f"[{v['titulo']}]({v['url']})" if v["url"] else f"**{v['titulo']}**"]
        if v["canal"]:
            origem.append(f"canal {v['canal']}")
        if v["duracao_s"]:
            origem.append(_curto(formatar_tempo(v["duracao_s"])))
        linhas += [" · ".join(origem), ""]
        linhas += [f"{nivel} Em resumo", "", v["resumo"] or "(nada encontrado)", ""]
        linhas += [f"{nivel} Passo a passo", ""]
        linhas += [f"{n}. {p['texto']}" + (f" _({_curto(p['minuto'])})_" if p["minuto"] else "")
                   for n, p in enumerate(v["passos"], 1)] or ["- (o vídeo não traz passos)"]
        linhas += ["", f"{nivel} Pontos principais", ""]
        linhas += [f"- {p}" for p in v["pontos"]] or ["- (nada encontrado)"]
        linhas += ["", f"{nivel} Ferramentas citadas", ""]
        linhas += [f"- **{f['nome']}**" + (f": {f['para_que']}" if f["para_que"] else "") for f in v["ferramentas"]] or ["- (nenhuma)"]
        linhas.append("")
    return "\n".join(linhas)
