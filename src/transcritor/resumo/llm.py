"""Cliente mínimo do Ollama (só a biblioteca padrão)."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


class ErroLLM(RuntimeError):
    pass


def extrair_json(texto: str) -> dict:
    """Pega o objeto JSON de uma resposta, mesmo com cercas de markdown ou texto em volta."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio >= 0 and fim > inicio:
            return json.loads(texto[inicio : fim + 1])
        raise


class Ollama:
    def __init__(self, modelo: str = "llama3.1:8b", url: str | None = None, num_ctx: int = 8192):
        self.modelo = modelo
        self.url = (url or os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        self.num_ctx = num_ctx

    def _post(self, caminho: str, corpo: dict, timeout: int = 600) -> dict:
        req = urllib.request.Request(
            self.url + caminho, data=json.dumps(corpo).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise ErroLLM(f"Não consegui falar com o Ollama em {self.url}: {exc}. Ele está rodando?") from exc

    def disponivel(self, timeout: float = 5) -> bool:
        try:
            urllib.request.urlopen(self.url + "/api/tags", timeout=timeout)
            return True
        except Exception:  # noqa: BLE001
            return False

    def gerar_json(self, sistema: str, prompt: str) -> dict:
        """Pede uma resposta em JSON. Se vier inválida, tenta mais uma vez avisando o erro."""
        corpo = {
            "model": self.modelo, "system": sistema, "prompt": prompt, "stream": False, "format": "json",
            "options": {"temperature": 0.2, "num_ctx": self.num_ctx},
        }
        resposta = self._post("/api/generate", corpo)["response"]
        try:
            return extrair_json(resposta)
        except json.JSONDecodeError as exc:
            corpo["prompt"] = prompt + f"\n\nSua resposta anterior não era JSON válido ({exc}). Responda só com o JSON corrigido."
            return extrair_json(self._post("/api/generate", corpo)["response"])

    def descarregar(self) -> None:
        """Libera a GPU, só se o modelo estiver carregado (pedir descarregar um modelo fora da memória o carrega)."""
        try:
            with urllib.request.urlopen(self.url + "/api/ps", timeout=5) as resp:
                carregados = [m["name"] for m in json.loads(resp.read()).get("models", [])]
            for nome in carregados:
                self._post("/api/generate", {"model": nome, "keep_alive": 0}, timeout=30)
        except Exception:  # noqa: BLE001 - liberar a GPU é um favor, não pode derrubar o resumo
            pass
