"""POC da API do Vimeo: os passos de leitura de docs/vimeo-integracao/05-plano-de-poc.md.

Só faz GET e HEAD. Não cria, não altera e não apaga nada no Vimeo.

    export VIMEO_POC_TOKEN_LEITURA=...        # token pessoal, escopos public private
    .venv/bin/python scripts/poc_vimeo.py --pasta 1234567 --video 987654321

Cada resposta vira um arquivo em `.poc_vimeo/` (fora do git) e o resumo final
preenche a tabela de critério de saída em `.poc_vimeo/resumo.md`. O token nunca
é impresso nem gravado.

Os passos de escrita (W), upload (U) e webhook (H) do plano seguem manuais: eles
mexem na conta real e cada etapa pede decisão humana.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

BASE = "https://api.vimeo.com"
ACEITA = "application/vnd.vimeo.*+json;version=3.4"
AGENTE = "mvp-portal-aluno-poc/0.1"

# Legenda automática só existe para vídeos enviados depois desta data (FAQ oficial).
CORTE_LEGENDA_AUTOMATICA = datetime(2022, 5, 25, tzinfo=UTC)

CAMPOS_PASTA = (
    "uri,name,created_time,modified_time,has_subfolder,"
    "metadata.connections.parent_folder,metadata.connections.ancestor_path,"
    "metadata.connections.videos.total,metadata.connections.videos.deep_total,"
    "metadata.connections.folders.total"
)
CAMPOS_ITEM = (
    "type,folder.uri,folder.name,folder.has_subfolder,"
    "folder.metadata.connections.videos.deep_total,video.uri,video.name"
)
CAMPOS_VIDEO_IMPORTACAO = (
    "uri,name,description,duration,link,player_embed_url,pictures.base_link,"
    "status,transcode.status,is_playable,privacy.view,privacy.embed,"
    "transcript.status,parent_project,resource_key,created_time,modified_time,"
    "is_cold_storage,is_cold_privacy_restricted,metadata.connections.versions.current_uri"
)
CAMPOS_ESTADO = (
    "uri,name,created_time,status,transcode.status,is_playable,transcript.status,"
    "privacy.view,privacy.embed,is_cold_storage,is_cold_privacy_restricted"
)
CAMPOS_VERSAO = "uri,filename,filesize,duration,active,upload_date,transcode.status"
CAMPOS_FAIXA = (
    "id,type,language,provenance,active,link,link_expires_time,"
    "download_links,download_links_expires_time"
)


# --- utilidades ---------------------------------------------------------------


def titulo(passo: str, texto: str) -> None:
    print(f"\n== {passo} — {texto}")


def pular(passo: str, motivo: str) -> None:
    print(f"\n== {passo} — pulado: {motivo}")


def valor(objeto: Any, caminho: str) -> Any:
    """Lê um campo em notação de ponto, como o `fields` do Vimeo usa."""
    atual = objeto
    for parte in caminho.split("."):
        if not isinstance(atual, dict) or parte not in atual:
            return None
        atual = atual[parte]
    return atual


def data_http(quando: datetime) -> str:
    return quando.strftime("%a, %d %b %Y %H:%M:%S GMT")


class Api:
    """Cliente de leitura, com registro de rate limit e gravação das respostas."""

    def __init__(self, token: str, saida: Path) -> None:
        self._http = httpx.Client(
            base_url=BASE,
            timeout=httpx.Timeout(20.0, connect=5.0),
            headers={
                "Authorization": f"bearer {token}",
                "Accept": ACEITA,
                "User-Agent": AGENTE,
            },
        )
        self.saida = saida
        self.limite: dict[str, str] = {}
        self.chamadas = 0

    def fechar(self) -> None:
        self._http.close()

    def get(self, caminho: str, *, passo: str | None = None, **params: Any) -> tuple[int, Any]:
        limpos = {k: v for k, v in params.items() if v is not None}
        resposta = self._http.get(caminho, params=limpos or None)
        return self._processar(resposta, passo, {"get": caminho, "params": limpos})

    def get_uri(self, uri: str, *, passo: str | None = None) -> tuple[int, Any]:
        """GET numa URI que a própria API devolveu (paging.next, por exemplo)."""
        resposta = self._http.get(uri)
        return self._processar(resposta, passo, {"get": uri})

    def get_com_cabecalhos(
        self, caminho: str, cabecalhos: dict[str, str], *, passo: str | None = None, **params: Any
    ) -> tuple[int, Any]:
        limpos = {k: v for k, v in params.items() if v is not None}
        resposta = self._http.get(caminho, params=limpos or None, headers=cabecalhos)
        return self._processar(
            resposta, passo, {"get": caminho, "params": limpos, "cabecalhos": cabecalhos}
        )

    def paginar(
        self, caminho: str, *, passo: str, maximo_paginas: int = 20, **params: Any
    ) -> tuple[list[dict], Any, int]:
        """Percorre `paging.next`. Devolve (itens, total informado, páginas lidas)."""
        itens: list[dict] = []
        total: Any = None
        pagina = 0
        status, corpo = self.get(caminho, passo=f"{passo}-p1", per_page=100, **params)
        while status == 200 and isinstance(corpo, dict):
            pagina += 1
            itens.extend(corpo.get("data") or [])
            total = corpo.get("total", total)
            proxima = valor(corpo, "paging.next")
            if not proxima or pagina >= maximo_paginas:
                break
            status, corpo = self.get_uri(proxima, passo=f"{passo}-p{pagina + 1}")
        return itens, total, pagina

    def gravar(self, passo: str, dados: Any) -> None:
        (self.saida / f"{passo}.json").write_text(
            json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _processar(self, resposta: httpx.Response, passo: str | None, contexto: dict) -> tuple[int, Any]:
        self.chamadas += 1
        self._anotar_limite(resposta)
        try:
            corpo: Any = resposta.json()
        except ValueError:
            corpo = resposta.text[:2000]
        if passo:
            self.gravar(
                passo,
                {**contexto, "status": resposta.status_code, "rate_limit": dict(self.limite), "corpo": corpo},
            )
        self._respirar()
        return resposta.status_code, corpo

    def _anotar_limite(self, resposta: httpx.Response) -> None:
        for chave in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
            if chave in resposta.headers:
                self.limite[chave] = resposta.headers[chave]

    def _respirar(self) -> None:
        """Se a cota está no fim, espera a janela virar em vez de tomar 429."""
        restante = self.limite.get("X-RateLimit-Remaining")
        if restante is None:
            return
        try:
            if int(float(restante)) > 5:
                return
        except ValueError:
            return
        espera = 61.0
        reinicio = self.limite.get("X-RateLimit-Reset")
        if reinicio:
            try:
                alvo = datetime.fromisoformat(reinicio.replace("Z", "+00:00"))
                espera = max(1.0, (alvo - datetime.now(UTC)).total_seconds() + 1)
            except ValueError:
                pass
        espera = min(espera, 90.0)
        print(f"   cota quase no fim; esperando {espera:.0f}s")
        time.sleep(espera)


# --- passos de leitura -------------------------------------------------------


def r1_conta(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R1", "autenticação, plano e acesso de upload")
    status, _ = api.get("/oauth/verify", passo="R1-verify")
    print(f"   GET /oauth/verify -> HTTP {status}")
    status, corpo = api.get("/me", passo="R1-me", fields="uri,name,membership,upload_quota")
    if status != 200 or not isinstance(corpo, dict):
        achados["plano"] = f"falhou (HTTP {status})"
        return
    membership = corpo.get("membership")
    cota = corpo.get("upload_quota")
    print(f"   conta: {corpo.get('name')} ({corpo.get('uri')})")
    print(f"   membership: {json.dumps(membership, ensure_ascii=False)}")
    print(f"   upload_quota presente: {'sim' if cota else 'não'}")
    print(f"   rate limit: {dict(api.limite)}")
    achados["plano"] = json.dumps(membership, ensure_ascii=False) if membership else "não informado"
    achados["acesso_upload"] = "sim" if cota else "não — pedir liberação ao suporte"
    achados["rate_limit"] = api.limite.get("X-RateLimit-Limit", "?")


def r2_cota_com_fields(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R2", "`fields` dobra a cota?")
    api.get("/me", passo="R2-sem-fields")
    sem = api.limite.get("X-RateLimit-Limit")
    api.get("/me", passo="R2-com-fields", fields="uri")
    com = api.limite.get("X-RateLimit-Limit")
    print(f"   X-RateLimit-Limit sem fields: {sem} | com fields: {com}")
    achados["cota_fields"] = f"sem fields={sem}, com fields={com}"


def r3_pastas(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R3", "listagem de pastas")
    pastas, total, paginas = api.paginar(
        "/me/projects", passo="R3-pastas", fields=CAMPOS_PASTA, sort="name", direction="asc"
    )
    com_pai = [p for p in pastas if valor(p, "metadata.connections.parent_folder.uri")]
    print(f"   pastas devolvidas: {len(pastas)} | total informado: {total} | páginas: {paginas}")
    print(f"   com parent_folder (subpastas na mesma lista): {len(com_pai)}")
    for pasta in pastas[:10]:
        print(
            f"     - {pasta.get('name')} | {pasta.get('uri')}"
            f" | vídeos: {valor(pasta, 'metadata.connections.videos.total')}"
            f" | com subpastas: {valor(pasta, 'metadata.connections.videos.deep_total')}"
            f" | tem subpasta: {pasta.get('has_subfolder')}"
        )
    achados["projects_traz_subpastas"] = (
        f"sim ({len(com_pai)} de {len(pastas)} têm pai)" if com_pai else "não, parece só o primeiro nível"
    )
    if args.busca_pasta:
        _, corpo = api.get("/me/projects", passo="R3-busca", fields="uri,name", query=args.busca_pasta)
        nomes = [p.get("name") for p in (valor(corpo, "data") or [])]
        print(f"   busca por {args.busca_pasta!r}: {nomes[:10]}")


def r4_arvore(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R4", "árvore de subpastas via /items")
    if not args.pasta:
        pular("R4", "passe --pasta <id>")
        return

    status, _ = api.get(
        f"/me/projects/{args.pasta}/items",
        passo="R4-itens-com-fields",
        filter="folder",
        per_page=100,
        fields=CAMPOS_ITEM,
    )
    aceita_fields = status == 200
    achados["fields_em_items"] = "aceito" if aceita_fields else f"recusado (HTTP {status})"
    print(f"   fields aninhado em /items: {achados['fields_em_items']}")

    _, raiz = api.get(f"/me/projects/{args.pasta}", passo="R4-pasta-raiz", fields=CAMPOS_PASTA)
    fundo = valor(raiz, "metadata.connections.videos.deep_total")
    print(f"   pasta raiz: {valor(raiz, 'name')} | deep_total: {fundo}")

    visitadas: list[tuple[int, str, str]] = []

    def andar(pasta_id: str, profundidade: int) -> None:
        if profundidade > args.profundidade:
            return
        itens, _, _ = api.paginar(
            f"/me/projects/{pasta_id}/items",
            passo=f"R4-sub-{pasta_id}",
            filter="folder",
            fields=CAMPOS_ITEM if aceita_fields else None,
        )
        for item in itens:
            pasta = item.get("folder") or {}
            uri = pasta.get("uri") or ""
            visitadas.append((profundidade, pasta.get("name") or "?", uri))
            filho = uri.rsplit("/", 1)[-1]
            if filho and pasta.get("has_subfolder"):
                andar(filho, profundidade + 1)

    andar(str(args.pasta), 1)
    for profundidade, nome, uri in visitadas[:30]:
        print(f"     {'  ' * profundidade}- {nome} ({uri})")
    print(f"   subpastas encontradas: {len(visitadas)} (profundidade máxima pedida: {args.profundidade})")
    achados["arvore"] = f"{len(visitadas)} subpasta(s); deep_total da raiz: {fundo}"


def r5_ordem(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R5", "ordem e paginação dos vídeos da pasta")
    if not args.pasta:
        pular("R5", "passe --pasta <id>")
        return
    sequencias: dict[str, list[str]] = {}
    for rotulo, extra in {
        "default": {"sort": "default"},
        "alphabetical-asc": {"sort": "alphabetical", "direction": "asc"},
        "date-asc": {"sort": "date", "direction": "asc"},
    }.items():
        _, corpo = api.get(
            f"/me/projects/{args.pasta}/videos",
            passo=f"R5-{rotulo}",
            fields="uri,name",
            per_page=100,
            **extra,
        )
        dados = valor(corpo, "data") or []
        sequencias[rotulo] = [v.get("uri") for v in dados]
        print(f"   {rotulo}: total={valor(corpo, 'total')} primeiros={[v.get('name') for v in dados[:5]]}")

    iguais = [
        rotulo
        for rotulo, seq in sequencias.items()
        if rotulo != "default" and seq and seq == sequencias.get("default")
    ]
    achados["ordem_default"] = (
        "igual a " + ", ".join(iguais) if iguais else "diferente de alphabetical e de date"
    )

    _, corpo = api.get(f"/me/projects/{args.pasta}/videos", passo="R5-pagina1", fields="uri", per_page=100)
    proxima = valor(corpo, "paging.next")
    if proxima:
        status, corpo2 = api.get_uri(proxima, passo="R5-pagina2")
        print(f"   paging.next -> HTTP {status}, itens na página 2: {len(valor(corpo2, 'data') or [])}")
        achados["paginacao"] = f"ok, total {valor(corpo, 'total')}"
    else:
        achados["paginacao"] = f"uma página só, total {valor(corpo, 'total')}"


def r6_include_subfolders(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R6", "include_subfolders e parent_project")
    if not args.pasta:
        pular("R6", "passe --pasta <id>")
        return
    _, total_sem, _ = api.paginar(f"/me/projects/{args.pasta}/videos", passo="R6-sem", fields="uri")
    com, total_com, _ = api.paginar(
        f"/me/projects/{args.pasta}/videos",
        passo="R6-com",
        fields="uri,name,parent_project",
        include_subfolders=True,
    )
    _, raiz = api.get(f"/me/projects/{args.pasta}", passo="R6-pasta", fields=CAMPOS_PASTA)
    fundo = valor(raiz, "metadata.connections.videos.deep_total")
    print(f"   sem subpastas: {total_sem} | com subpastas: {total_com} | deep_total: {fundo}")
    exemplo = next((v.get("parent_project") for v in com if v.get("parent_project")), None)
    print(f"   parent_project de exemplo: {json.dumps(exemplo, ensure_ascii=False)[:300]}")
    achados["include_subfolders"] = f"sem={total_sem}, com={total_com}, deep_total={fundo}"
    achados["parent_project"] = (
        json.dumps(exemplo, ensure_ascii=False)[:200] if exemplo else "não veio no payload"
    )


def r7_video_completo(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R7", "payload completo de um vídeo")
    if not args.video:
        pular("R7", "passe --video <id>")
        return
    status, corpo = api.get(f"/videos/{args.video}", passo="R7-video-completo")
    quantos = len(corpo) if isinstance(corpo, dict) else 0
    print(f"   HTTP {status}; campos no primeiro nível: {quantos}")


def r8_campos_importacao(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R8", "os campos que a importação pede existem?")
    if not args.video:
        pular("R8", "passe --video <id>")
        return
    status, corpo = api.get(f"/videos/{args.video}", passo="R8-video-fields", fields=CAMPOS_VIDEO_IMPORTACAO)
    faltando = [campo for campo in CAMPOS_VIDEO_IMPORTACAO.split(",") if valor(corpo, campo) is None]
    print(f"   HTTP {status}; ausentes ou nulos: {faltando or 'nenhum'}")
    achados["campos_importacao"] = (
        "todos presentes" if not faltando else "ausentes ou nulos: " + ", ".join(faltando)
    )


def r9_estados(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R9", "estados do acervo e cobertura de transcrição")
    videos, total, paginas = api.paginar(
        "/me/videos", passo="R9-videos", fields=CAMPOS_ESTADO, maximo_paginas=args.max_paginas
    )
    por_status: dict[Any, int] = {}
    por_transcricao: dict[Any, int] = {}
    antigos = antigos_sem = recentes_sem = 0
    for video in videos:
        chave = video.get("status")
        por_status[chave] = por_status.get(chave, 0) + 1
        transcricao = valor(video, "transcript.status") or "sem campo"
        por_transcricao[transcricao] = por_transcricao.get(transcricao, 0) + 1
        criado = video.get("created_time")
        if not criado:
            continue
        try:
            quando = datetime.fromisoformat(criado.replace("Z", "+00:00"))
        except ValueError:
            continue
        antes_do_corte = quando < CORTE_LEGENDA_AUTOMATICA
        antigos += 1 if antes_do_corte else 0
        if transcricao != "completed":
            if antes_do_corte:
                antigos_sem += 1
            else:
                recentes_sem += 1
    print(f"   analisados {len(videos)} de {total} (páginas lidas: {paginas}; limite: {args.max_paginas})")
    print(f"   status: {por_status}")
    print(f"   transcript.status: {por_transcricao}")
    print(f"   anteriores a 25/05/2022: {antigos}, dos quais {antigos_sem} sem transcrição")
    print(f"   posteriores ao corte e sem transcrição: {recentes_sem}")
    achados["transcricoes"] = (
        f"{antigos_sem} antigos e {recentes_sem} recentes sem transcrição, de {len(videos)} analisados"
    )
    achados["estados_do_acervo"] = json.dumps(por_status, ensure_ascii=False)


def r11_dominios(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R11", "domínios liberados para embed")
    if not args.video:
        pular("R11", "passe --video <id>")
        return
    status, corpo = api.get(f"/videos/{args.video}/privacy/domains", passo="R11-dominios")
    dominios = [item.get("domain") for item in (valor(corpo, "data") or [])]
    print(f"   HTTP {status}; domínios: {dominios}")
    achados["dominios_embed"] = f"HTTP {status}: {dominios}"


def r12_transcricao(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R12", "faixas de texto e segmentos da transcrição")
    alvo = args.video_legenda or args.video
    if not alvo:
        pular("R12", "passe --video-legenda <id>")
        return
    status, corpo = api.get(f"/videos/{alvo}/texttracks", passo="R12-texttracks", fields=CAMPOS_FAIXA)
    faixas = valor(corpo, "data") or []
    print(f"   HTTP {status}; faixas: {len(faixas)}")
    for faixa in faixas[:5]:
        print(
            f"     - id={faixa.get('id')} tipo={faixa.get('type')} idioma={faixa.get('language')}"
            f" origem={faixa.get('provenance')} ativa={faixa.get('active')}"
            f" expira={faixa.get('download_links_expires_time')}"
        )
    achados["faixas_de_texto"] = f"HTTP {status}, {len(faixas)} faixa(s)"
    if not faixas:
        return
    faixa_id = faixas[0].get("id")
    status, corpo = api.get(f"/videos/{alvo}/transcripts/{faixa_id}", passo="R12-transcricao")
    print(f"   segmentos HTTP {status}; amostra: {json.dumps(corpo, ensure_ascii=False)[:300]}")
    achados["formato_transcricao"] = f"HTTP {status} (payload em .poc_vimeo/R12-transcricao.json)"


def r13_versoes(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R13", "versões, nome original e tamanho do arquivo")
    if not args.video:
        pular("R13", "passe --video <id>")
        return
    status, corpo = api.get(f"/videos/{args.video}/versions", passo="R13-versoes", fields=CAMPOS_VERSAO)
    versoes = valor(corpo, "data") or []
    print(f"   HTTP {status}; versões: {len(versoes)}")
    for versao in versoes[:5]:
        print(
            f"     - {versao.get('filename')} | {versao.get('filesize')} bytes"
            f" | ativa={versao.get('active')} | enviada={versao.get('upload_date')}"
        )
    ativa = next((v for v in versoes if v.get("active")), versoes[0] if versoes else None)
    achados["nome_original"] = (
        f"{ativa.get('filename')} ({ativa.get('filesize')} bytes)" if ativa else f"HTTP {status}, nada"
    )


def r14_thumbnails(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R14", "thumbnail: URL de hoje (repetir em 48 h para ver se muda)")
    if not args.video:
        pular("R14", "passe --video <id>")
        return
    status, corpo = api.get(f"/videos/{args.video}/pictures", passo="R14-thumbs", sizes="640x")
    imagens = valor(corpo, "data") or []
    tamanhos = (imagens[0].get("sizes") or []) if imagens else []
    link = tamanhos[0].get("link") if tamanhos else None
    print(f"   HTTP {status}; base_link: {valor(imagens[0], 'base_link') if imagens else None}")
    print(f"   link 640x: {str(link)[:120]}")
    achados["thumbnail"] = f"HTTP {status}; link salvo em .poc_vimeo/R14-thumbs.json"


def r15_busca(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R15", "busca no acervo próprio")
    if not args.busca:
        pular("R15", "passe --busca <termo>")
        return
    _, corpo = api.get(
        "/me/videos",
        passo="R15-busca",
        fields="uri,name",
        query=args.busca,
        query_fields="title",
        per_page=10,
    )
    nomes = [v.get("name") for v in (valor(corpo, "data") or [])]
    print(f"   total: {valor(corpo, 'total')}; primeiros: {nomes[:10]}")
    achados["busca"] = f"{valor(corpo, 'total')} resultado(s) para {args.busca!r}"


def r16_condicional(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R16", "If-Modified-Since em /me/videos")
    agora = data_http(datetime.now(UTC))
    antiga = data_http(datetime(2020, 1, 1, tzinfo=UTC))
    status_agora, _ = api.get_com_cabecalhos(
        "/me/videos", {"If-Modified-Since": agora}, passo="R16-agora", fields="uri", per_page=1
    )
    status_antiga, _ = api.get_com_cabecalhos(
        "/me/videos", {"If-Modified-Since": antiga}, passo="R16-antiga", fields="uri", per_page=1
    )
    print(f"   data de agora -> HTTP {status_agora} | data antiga -> HTTP {status_antiga}")
    achados["if_modified_since"] = f"agora={status_agora}, antiga={status_antiga}"


def r17_inexistente(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R17", "vídeo inexistente e vídeo sem acesso")
    status, corpo = api.get(f"/videos/{args.video_inexistente}", passo="R17-inexistente")
    print(f"   GET /videos/{args.video_inexistente} -> HTTP {status}: {json.dumps(corpo, ensure_ascii=False)[:200]}")
    achados["video_inexistente"] = f"HTTP {status}"
    if args.video_sem_acesso:
        status, corpo = api.get(f"/videos/{args.video_sem_acesso}", passo="R17-sem-acesso")
        print(f"   vídeo de outra conta -> HTTP {status}")
        achados["video_sem_acesso"] = f"HTTP {status}"


def r18_openapi(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R18", "especificação OpenAPI pela própria API")
    status, corpo = api.get("/", passo="R18-raiz")
    tamanho = len(json.dumps(corpo, ensure_ascii=False)) if corpo else 0
    print(f"   GET / -> HTTP {status}, {tamanho} bytes")
    status_spec, corpo_spec = api.get("/", passo="R18-openapi", openapi=1)
    tamanho_spec = len(json.dumps(corpo_spec, ensure_ascii=False)) if corpo_spec else 0
    print(f"   GET /?openapi=1 -> HTTP {status_spec}, {tamanho_spec} bytes")
    achados["openapi"] = f"GET / = HTTP {status} ({tamanho} bytes); ?openapi=1 = HTTP {status_spec} ({tamanho_spec} bytes)"


def r19_analytics(api: Api, args, achados: dict[str, str]) -> None:
    titulo("R19", "Analytics API (precisa de Enterprise e do escopo stats)")
    if not args.analytics:
        pular("R19", "passe --analytics para tentar")
        return
    ate = datetime.now(UTC).date().isoformat()
    de = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
    status, corpo = api.get(
        "/me/analytics", passo="R19-analytics", dimension="total", **{"from": de, "to": ate}
    )
    print(f"   HTTP {status}: {json.dumps(corpo, ensure_ascii=False)[:240]}")
    achados["analytics"] = f"HTTP {status}"


PASSOS = {
    "R1": r1_conta,
    "R2": r2_cota_com_fields,
    "R3": r3_pastas,
    "R4": r4_arvore,
    "R5": r5_ordem,
    "R6": r6_include_subfolders,
    "R7": r7_video_completo,
    "R8": r8_campos_importacao,
    "R9": r9_estados,
    "R11": r11_dominios,
    "R12": r12_transcricao,
    "R13": r13_versoes,
    "R14": r14_thumbnails,
    "R15": r15_busca,
    "R16": r16_condicional,
    "R17": r17_inexistente,
    "R18": r18_openapi,
    "R19": r19_analytics,
}

# Pergunta do critério de saída -> chaves de `achados` que a respondem.
RESUMO = [
    ("Plano da conta e acesso de upload (R1)", ("plano", "acesso_upload", "rate_limit")),
    ("`fields` dobra a cota? (R2)", ("cota_fields",)),
    ("`/me/projects` traz subpastas? (R3)", ("projects_traz_subpastas",)),
    ("`fields` aninhado em `/items` e árvore (R4)", ("fields_em_items", "arvore")),
    ("`sort=default` reproduz a ordem da interface? (R5)", ("ordem_default", "paginacao")),
    ("`include_subfolders` e formato de `parent_project` (R6)", ("include_subfolders", "parent_project")),
    ("Campos da importação existem? (R8)", ("campos_importacao",)),
    ("Estados do acervo e transcrições faltando (R9)", ("estados_do_acervo", "transcricoes")),
    ("Domínios de embed (R11)", ("dominios_embed",)),
    ("Faixas de texto e formato da transcrição (R12)", ("faixas_de_texto", "formato_transcricao")),
    ("Nome original do arquivo (R13)", ("nome_original",)),
    ("Thumbnail (R14)", ("thumbnail",)),
    ("Busca no acervo (R15)", ("busca",)),
    ("If-Modified-Since (R16)", ("if_modified_since",)),
    ("Vídeo inexistente e sem acesso (R17)", ("video_inexistente", "video_sem_acesso")),
    ("OpenAPI pela API (R18)", ("openapi",)),
    ("Analytics API (R19)", ("analytics",)),
]


def escrever_resumo(saida: Path, achados: dict[str, str], api: Api) -> Path:
    linhas = [
        "# Resultado da POC de leitura da API do Vimeo",
        "",
        f"Executada em {datetime.now(UTC).isoformat(timespec='seconds')} — {api.chamadas} chamadas.",
        "",
        "| Pergunta | Resultado |",
        "|---|---|",
    ]
    for pergunta, chaves in RESUMO:
        respostas = [achados[c] for c in chaves if c in achados]
        texto = " · ".join(respostas).replace("|", "\\|") if respostas else "não executado"
        linhas.append(f"| {pergunta} | {texto} |")
    linhas += [
        "",
        "Passos que continuam manuais: R10 (Player SDK no portal), escrita (W),",
        "upload (U) e webhooks (H). Ver docs/vimeo-integracao/05-plano-de-poc.md.",
        "",
    ]
    destino = saida / "resumo.md"
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino


def main() -> int:
    parser = argparse.ArgumentParser(description="POC de leitura da API do Vimeo.")
    parser.add_argument("--pasta", help="ID de uma pasta real, de preferência com subpastas")
    parser.add_argument("--video", help="ID de um vídeo real para inspecionar")
    parser.add_argument("--video-legenda", help="ID de um vídeo que tenha legenda automática")
    parser.add_argument("--video-sem-acesso", help="ID de um vídeo privado de outra conta")
    parser.add_argument("--video-inexistente", default="999999999999", help="ID que não existe")
    parser.add_argument("--busca", help="Termo para testar a busca no acervo")
    parser.add_argument("--busca-pasta", help="Termo para testar a busca de pastas por nome")
    parser.add_argument("--passos", help="Lista separada por vírgula, ex.: R1,R3,R5. O padrão roda todos")
    parser.add_argument("--profundidade", type=int, default=3, help="Profundidade máxima da árvore (R4)")
    parser.add_argument("--max-paginas", type=int, default=10, help="Páginas de 100 vídeos no R9")
    parser.add_argument("--analytics", action="store_true", help="Tenta o R19 (exige escopo stats)")
    parser.add_argument("--saida", default=".poc_vimeo", help="Pasta de saída (fora do git)")
    args = parser.parse_args()

    # No Windows o console costuma vir em cp1252 e engole os acentos.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    token = os.environ.get("VIMEO_POC_TOKEN_LEITURA")
    if not token:
        print("Defina VIMEO_POC_TOKEN_LEITURA com um token pessoal de escopos public private.")
        return 1

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    escolhidos = [p.strip().upper() for p in args.passos.split(",")] if args.passos else list(PASSOS)
    desconhecidos = [p for p in escolhidos if p not in PASSOS]
    if desconhecidos:
        print(f"Passos desconhecidos: {desconhecidos}. Disponíveis: {', '.join(PASSOS)}")
        return 1

    api = Api(token, saida)
    achados: dict[str, str] = {}
    print(f"POC de leitura — {len(escolhidos)} passo(s); respostas em {saida}/")
    try:
        for passo in escolhidos:
            try:
                PASSOS[passo](api, args, achados)
            except httpx.HTTPError as erro:
                print(f"   erro de rede em {passo}: {type(erro).__name__}: {erro}")
            except Exception as erro:  # a POC não para por causa de um passo
                print(f"   erro em {passo}: {type(erro).__name__}: {erro}")
    finally:
        api.fechar()

    destino = escrever_resumo(saida, achados, api)
    print(f"\nResumo em {destino} — {api.chamadas} chamadas, rate limit final: {dict(api.limite)}")
    print("Confira o resumo e leve as respostas para docs/vimeo-integracao/05-plano-de-poc.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
