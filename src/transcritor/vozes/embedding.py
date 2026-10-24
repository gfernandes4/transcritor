"""Impressão digital da voz (embedding) com um modelo pequeno em ONNX, via sherpa-onnx.

Os modelos vêm do release oficial do projeto sherpa-onnx e são conferidos pelo SHA-256 publicado por eles.
"""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

import numpy as np

from ..config import home

URL_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
# Avaliados em 23/10/2026 nos 39 áudios de duas pessoas: o CAM++ acertou 39 de 39 (leave-one-out).
# O titanet pequeno do NeMo falhou no ONNX com áudios mais longos e foi descartado.
MODELOS = {
    "campp": "wespeaker_en_voxceleb_CAM++.onnx",      # ~28 MB
}
MODELO_PADRAO_VOZ = "campp"
TAXA = 16_000
MINIMO_SEGUNDOS = 1.0


class ErroVoz(RuntimeError):
    pass


def pasta_modelos() -> Path:
    pasta = home() / "modelos" / "voz"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def caminho_modelo(nome: str) -> Path:
    if nome not in MODELOS:
        raise ErroVoz(f"Modelo de voz desconhecido: {nome}. Opções: {', '.join(MODELOS)}")
    return pasta_modelos() / MODELOS[nome]


def _baixar(url: str, destino: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as resp, destino.open("wb") as f:
        while bloco := resp.read(1024 * 1024):
            f.write(bloco)


def baixar_modelo(nome: str) -> Path:
    """Baixa o modelo e confere o SHA-256 contra o `checksum.txt` do mesmo release."""
    destino = caminho_modelo(nome)
    arquivo = MODELOS[nome]
    with urllib.request.urlopen(URL_BASE + "checksum.txt", timeout=60) as resp:
        linhas = resp.read().decode("utf-8", "replace").splitlines()
    esperado = next((l.split()[-1] for l in linhas if l.split() and l.split()[0] == arquivo), None)
    if not esperado:
        raise ErroVoz(f"{arquivo} não está no checksum.txt do release; não vou usar um arquivo que não consigo conferir.")
    temporario = destino.with_suffix(".baixando")
    _baixar(URL_BASE + arquivo, temporario)
    obtido = hashlib.sha256(temporario.read_bytes()).hexdigest()
    if obtido != esperado:
        temporario.unlink()
        raise ErroVoz(f"O SHA-256 de {arquivo} não confere (esperado {esperado[:12]}…, veio {obtido[:12]}…). Arquivo descartado.")
    temporario.replace(destino)
    return destino


class Extrator:
    def __init__(self, nome: str = MODELO_PADRAO_VOZ, threads: int = 2):
        caminho = caminho_modelo(nome)
        if not caminho.exists():
            raise ErroVoz(f"Modelo de voz '{nome}' não encontrado. Rode: transcritor vozes baixar-modelo {nome}")
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise ErroVoz('Falta o módulo de voz. Instale com: pip install "transcritor[vozes]"') from exc
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(caminho), num_threads=threads, debug=False, provider="cpu")
        try:
            self._extrator = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        except Exception as exc:  # noqa: BLE001
            raise ErroVoz(f"Não consegui carregar o modelo de voz {caminho.name}: {exc}") from exc
        self.nome = nome

    def embedding(self, amostras: np.ndarray) -> np.ndarray:
        """Vetor normalizado (norma 1) que resume a voz das amostras (float32, mono, 16 kHz)."""
        stream = self._extrator.create_stream()
        stream.accept_waveform(sample_rate=TAXA, waveform=amostras.astype(np.float32))
        stream.input_finished()
        vetor = np.array(self._extrator.compute(stream), dtype=np.float32)
        norma = float(np.linalg.norm(vetor))
        return vetor / norma if norma else vetor

    def do_arquivo(self, caminho: str | Path) -> np.ndarray:
        from faster_whisper.audio import decode_audio

        amostras = decode_audio(str(caminho), sampling_rate=TAXA)
        if len(amostras) < TAXA * MINIMO_SEGUNDOS:
            raise ErroVoz(f"{Path(caminho).name}: áudio curto demais para identificar a voz (menos de {MINIMO_SEGUNDOS:.0f} s).")
        return self.embedding(amostras)
