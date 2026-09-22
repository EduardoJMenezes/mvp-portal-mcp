"""Sobe o adaptador — é o comando de partida do serviço no Railway.

    python -m app.servir

Um processo só, de propósito: a sessão do conector MCP mora na memória, e
duplicá-la faria o pedido do professor cair no processo errado.
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 — o contêiner só é alcançado pelo proxy da Railway
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
