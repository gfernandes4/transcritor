"""Motor de transcrição: faster-whisper, na GPU quando der e na CPU quando não der."""
from __future__ import annotations

import gc
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import IDIOMA_PADRAO, MODELO_PADRAO
from .cuda import erro_de_cuda, registrar_cuda


@dataclass
class Parametros:
    """Parâmetros do Whisper. `None` significa "usar o padrão do faster-whisper"."""

    idioma: str | None = IDIOMA_PADRAO
    beam_size: int = 5
    vad_filter: bool = True
    condition_on_previous_text: bool | None = None
    temperatura: tuple[float, ...] | None = None
    compression_ratio_threshold: float | None = None
    no_speech_threshold: float | None = None
    repetition_penalty: float | None = None

    @classmethod
    def melhorado(cls, idioma: str | None = IDIOMA_PADRAO) -> "Parametros":
        """Ajustes contra loops e lixo: cada trecho é decodificado sem depender do anterior,
        e o Whisper tenta de novo com mais variação quando a saída parece repetitiva."""
        return cls(
            idioma=idioma,
            condition_on_previous_text=False,
            temperatura=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
            compression_ratio_threshold=2.4,
            no_speech_threshold=0.6,
        )

    def para_whisper(self, glossario: list[str] | None = None) -> dict:
        kw = {
            "language": self.idioma or None,
            "beam_size": self.beam_size,
            "vad_filter": self.vad_filter,
        }
        opcionais = {
            "condition_on_previous_text": self.condition_on_previous_text,
            "temperature": self.temperatura,
            "compression_ratio_threshold": self.compression_ratio_threshold,
            "no_speech_threshold": self.no_speech_threshold,
            "repetition_penalty": self.repetition_penalty,
        }
        kw.update({k: v for k, v in opcionais.items() if v is not None})
        if glossario:
            kw["hotwords"] = ", ".join(glossario)
        return kw


class Motor:
    """Carrega o modelo uma vez e transcreve vários arquivos. Chame `descarregar()` ao terminar."""

    def __init__(self, modelo: str = MODELO_PADRAO, forcar_cpu: bool = False):
        self.nome = modelo
        self.dispositivo = "cpu" if forcar_cpu else "cuda"
        self._modelo = None

    def _garantir(self):
        if self._modelo is not None:
            return
        registrar_cuda()
        from faster_whisper import WhisperModel

        if self.dispositivo == "cuda":
            self._modelo = WhisperModel(self.nome, device="cuda", compute_type="int8_float16")
        else:
            self._modelo = WhisperModel(self.nome, device="cpu", compute_type="int8")

    def transcrever(self, caminho: str | Path, parametros: Parametros, glossario: list[str] | None = None):
        """Devolve (segmentos, duracao_s, idioma). Cai para a CPU se a GPU não estiver utilizável."""
        self._garantir()
        try:
            return self._rodar(caminho, parametros, glossario)
        except Exception as exc:  # noqa: BLE001
            if self.dispositivo == "cuda" and erro_de_cuda(exc):
                print(f"Aviso: a GPU não está utilizável ({exc}). Usando a CPU, que é bem mais lenta.", file=sys.stderr)
                self.descarregar()
                self.dispositivo = "cpu"
                self._garantir()
                return self._rodar(caminho, parametros, glossario)
            raise

    def _rodar(self, caminho, parametros, glossario):
        segs, info = self._modelo.transcribe(str(caminho), **parametros.para_whisper(glossario))
        segmentos = [
            {"inicio": round(s.start, 2), "fim": round(s.end, 2), "texto": s.text.strip()}
            for s in segs
            if s.text.strip()
        ]
        return segmentos, float(info.duration), info.language

    def descarregar(self) -> None:
        self._modelo = None
        gc.collect()
