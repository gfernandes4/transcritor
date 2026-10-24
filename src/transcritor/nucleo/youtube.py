"""Baixa o áudio de um link de vídeo (YouTube e outros sites que o yt-dlp conhece).

Módulo opcional: o `yt-dlp` só é carregado quando um link é usado (extra `youtube`).
Não tenta contornar bloqueios do site: se o YouTube pedir verificação, o erro explica o que fazer.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)
_RUNTIMES_JS = ("deno", "node", "bun")


class ErroDownload(RuntimeError):
    """Falha ao baixar o áudio, com uma mensagem que diz o que fazer."""


@dataclass
class Baixado:
    arquivo: Path        # áudio baixado (numa pasta temporária de quem chamou)
    url: str
    titulo: str
    canal: str
    duracao_s: float
    id: str

    @property
    def nome(self) -> str:
        """Nome para usar como identificação e nos arquivos de saída: título limpo + id do vídeo."""
        return f"{nome_seguro(self.titulo)} [{self.id}]"

    def origem(self) -> dict:
        return {"url": self.url, "titulo": self.titulo, "canal": self.canal}


def eh_url(texto: object) -> bool:
    return isinstance(texto, str) and bool(_URL.match(texto.strip()))


def disponivel() -> bool:
    """O extra `youtube` está instalado?"""
    return importlib.util.find_spec("yt_dlp") is not None


def nome_seguro(titulo: str, limite: int = 80) -> str:
    """Tira o que o Windows não aceita em nome de arquivo e os pontos (que enganariam a extensão)."""
    limpo = re.sub(r'[<>:"/\\|?*.\x00-\x1f]', " ", titulo or "")
    limpo = " ".join(limpo.split())[:limite].strip()
    return limpo or "video"


def traduzir_erro(mensagem: str) -> str:
    """Transforma a mensagem técnica do yt-dlp em algo que diz o que fazer."""
    texto = mensagem.removeprefix("ERROR: ").strip()
    baixo = texto.lower()
    if "confirm your age" in baixo or ("age" in baixo and "restrict" in baixo):   # antes do anti-robô: as duas dizem "sign in to confirm"
        return "O vídeo tem restrição de idade e não pode ser baixado sem entrar numa conta. Envie o arquivo no lugar do link."
    if "not a bot" in baixo:
        return ("O YouTube pediu uma verificação anti-robô e não deixou baixar este vídeo. "
                "Baixe o vídeo por outro meio e envie o arquivo de áudio ou vídeo no lugar do link.")
    if "private video" in baixo or "members-only" in baixo or "members only" in baixo or "video unavailable" in baixo:
        return "Esse vídeo é privado, só para membros ou não está mais disponível."
    if "unsupported url" in baixo:
        return "Não reconheci esse link como um vídeo. Confira se é o endereço de um vídeo e não de um canal ou busca."
    if "getaddrinfo" in baixo or "urlopen error" in baixo or "timed out" in baixo or "network" in baixo:
        return "Sem conexão com a internet para baixar o vídeo. Confira a conexão e tente de novo."
    return f"Não consegui baixar o vídeo: {texto}"


def baixar_audio(url: str, pasta: str | Path) -> Baixado:
    """Baixa só o áudio do vídeo para `pasta` (um vídeo por link; playlists não são aceitas)."""
    url = url.strip()
    if not eh_url(url):
        raise ErroDownload(f"Isso não parece um link: {url[:60]}")
    if not disponivel():
        raise ErroDownload('Falta o módulo de links. Instale com: pip install "transcritor[youtube]"')
    import yt_dlp

    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    opcoes: dict = {
        "format": "bestaudio/best", "outtmpl": str(pasta / "%(id)s.%(ext)s"), "noplaylist": True,
        "quiet": True, "no_warnings": True, "noprogress": True, "restrictfilenames": True,
    }
    runtime = next((r for r in _RUNTIMES_JS if shutil.which(r)), None)
    if runtime:   # o YouTube exige um runtime de JavaScript para listar todos os formatos
        opcoes["js_runtimes"] = {runtime: {}}
    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise ErroDownload("O site não devolveu nenhum vídeo para esse link.")
            if info.get("_type") == "playlist":
                raise ErroDownload("Esse link é de uma playlist ou canal. Envie o link de um vídeo só.")
            arquivo = Path(ydl.prepare_filename(info))
    except ErroDownload:
        raise
    except yt_dlp.utils.DownloadError as exc:
        raise ErroDownload(traduzir_erro(str(exc))) from exc
    if not arquivo.exists():   # alguns formatos mudam a extensão depois de baixar
        achados = sorted(pasta.glob(f"{info['id']}.*"))
        if not achados:
            raise ErroDownload("O download terminou, mas não achei o arquivo de áudio.")
        arquivo = achados[0]
    return Baixado(arquivo=arquivo, url=url, titulo=info.get("title") or "", canal=info.get("uploader") or info.get("channel") or "",
                   duracao_s=float(info.get("duration") or 0), id=str(info["id"]))
