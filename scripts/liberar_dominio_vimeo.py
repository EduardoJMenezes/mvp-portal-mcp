"""Libera um domínio para embed nos vídeos de uma pasta do Vimeo.

A privacidade de embed do Vimeo é **por vídeo**: na interface, liberar um
domínio novo significa abrir vídeo por vídeo. Este script faz isso em lote,
e só isso.

O que ele faz:

* lê os vídeos da pasta e a lista de domínios de cada um;
* acrescenta o domínio pedido em quem ainda não tem
  (`PUT /videos/{id}/privacy/domains/{domain}`).

O que ele **não** faz, por construção: não remove domínio, não muda
privacidade, não move, não apaga e não renomeia. A allowlist do transporte só
libera GET, HEAD e PUT, e as rotas destrutivas ficam barradas de qualquer jeito.

    export VIMEO_TOKEN_ESCRITA=...   # escopos public private edit
    python scripts/liberar_dominio_vimeo.py --pasta 27843651 \
        --dominio app-production-e5b7.up.railway.app --confirmo

Sem `--confirmo`, ele só mostra o que faria.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from app.integracoes.vimeo import ClienteVimeoLeitura, TransporteVimeo, VimeoErro  # noqa: E402


def limpar(dominio: str) -> str:
    """O Vimeo quer o domínio sem protocolo e sem barra final."""
    limpo = dominio.strip()
    for prefixo in ("https://", "http://"):
        if limpo.lower().startswith(prefixo):
            limpo = limpo[len(prefixo) :]
    return limpo.strip("/")


async def executar(args) -> int:
    token = os.environ.get("VIMEO_TOKEN_ESCRITA")
    if not token:
        print("Defina VIMEO_TOKEN_ESCRITA com um token de escopos public private edit.")
        return 1

    dominio = limpar(args.dominio)
    if dominio != args.dominio.strip():
        print(f"Domínio normalizado para {dominio!r} (sem protocolo e sem barra final).")

    transporte = TransporteVimeo(
        token,
        agente="mvp-portal-aluno/0.1 (liberar-dominio)",
        metodos_permitidos=("GET", "HEAD", "PUT"),
    )
    leitura = ClienteVimeoLeitura(transporte)
    liberados, ja_tinham, pulados, falhas = 0, 0, 0, 0
    try:
        videos = await leitura.listar_videos_da_pasta(
            args.pasta, campos="uri,name,privacy.view,privacy.embed"
        )
        print(f"\nPasta {args.pasta}: {len(videos)} vídeo(s).\n")
        for video in videos:
            atuais = await leitura.listar_dominios_de_embed(video.id)
            rotulo = f"{video.id} {(video.nome or '')[:28]:<28}"
            if video.privacidade_embed != "whitelist":
                print(f"  {rotulo} pulado: embed={video.privacidade_embed}, a lista de domínios não vale")
                pulados += 1
                continue
            if dominio in atuais:
                print(f"  {rotulo} já tinha o domínio")
                ja_tinham += 1
                continue
            if not args.confirmo:
                print(f"  {rotulo} LIBERARIA (atuais: {atuais})")
                continue
            try:
                resposta = await transporte.requisitar(
                    "PUT", f"/videos/{video.id}/privacy/domains/{dominio}"
                )
                depois = await leitura.listar_dominios_de_embed(video.id)
                ok = dominio in depois
                print(f"  {rotulo} HTTP {resposta.status_code} -> {'ok' if ok else 'não entrou'} {depois}")
                liberados += 1 if ok else 0
                falhas += 0 if ok else 1
            except VimeoErro as erro:
                print(f"  {rotulo} falhou: {erro}")
                falhas += 1
    finally:
        await transporte.aclose()

    if not args.confirmo:
        print("\nNada foi alterado. Rode de novo com --confirmo para valer.")
        return 0
    print(f"\nLiberados: {liberados} | já tinham: {ja_tinham} | pulados: {pulados} | falhas: {falhas}")
    return 0 if falhas == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Libera um domínio de embed nos vídeos de uma pasta.")
    parser.add_argument("--pasta", required=True, help="ID da pasta no Vimeo")
    parser.add_argument("--dominio", required=True, help="Domínio do portal, sem protocolo")
    parser.add_argument("--confirmo", action="store_true", help="Sem isto, só mostra o que faria")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return asyncio.run(executar(args))


if __name__ == "__main__":
    raise SystemExit(main())
