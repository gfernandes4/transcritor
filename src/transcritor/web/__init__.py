"""Interface web mínima (módulo opcional): `transcritor web`."""


def servir(porta: int = 8800) -> None:
    import uvicorn

    from .app import criar_app

    # Só em 127.0.0.1: não há login, então não deve ficar acessível pela rede.
    uvicorn.run(criar_app(), host="127.0.0.1", port=porta, log_level="warning")
