# Integração com o Vimeo

## Por que o backend fala com o Vimeo

A seção 8 do MVP sugere usar o MCP oficial do Vimeo quando ele expuser as
operações necessárias. **O MCP oficial existe** — `https://mcp.vimeo.com/mcp`,
em beta público, exigindo plano Pro ou superior e login OAuth de cada pessoa —,
**mas ele não entra no produto**. Três motivos:

* ele não conhece a regra de rascunho e aprovação (§6): pelo MCP do Vimeo o
  modelo mexeria no acervo direto, fora do nosso fluxo;
* ele autentica uma pessoa num cliente de chat, e o portal precisa de credencial
  de servidor para job, sincronização e reconciliação, sem ninguém logado;
* a tela do aluno e o snapshot no PostgreSQL dependem da API REST de qualquer
  forma.

Então quem conversa com o Vimeo é o nosso backend, pela API REST oficial, que é
a alternativa que a própria especificação prevê. O agente chega ao acervo pela
tool `listar_videos_vimeo`. Como ferramenta pessoal do professor, em paralelo ao
produto, o MCP oficial é bem-vindo — o job de reconciliação é quem percebe o que
for alterado por fora.

A pesquisa completa das capacidades da API, com matriz, gaps e plano de
implementação, está em [vimeo-integracao/](vimeo-integracao/README.md).

## Credencial: Personal Access Token

Não é o client secret — esse serve ao fluxo OAuth de autenticar terceiros.
Para ler o *próprio* acervo:

1. [developer.vimeo.com/apps](https://developer.vimeo.com/apps) → crie ou abra um app
2. aba **Authentication** → seção *Personal Access Tokens* → **Generate**
3. marque **Authenticated** e os escopos **Public** e **Private**
4. copie o valor (aparece uma vez só) para `VIMEO_ACCESS_TOKEN` no `.env`

`Private` é o que libera pastas e vídeos não públicos. **Não** marque:

* `video_files` — libera os arquivos de vídeo em si; usamos o player embutido;
* `upload` / `edit` / `delete` / `interact` — a POC só lê.

Menos escopo, menos estrago se o token vazar.

Sem token, o backend usa um **acervo de demonstração** embutido (`VimeoDemo`,
com pastas Atomística, Estequiometria e Cinética) e a POC roda inteira sem
credencial. `GET /api/saude` diz qual dos dois está ativo:

```json
{"ok": true, "vimeo": "api-real", "mcp": "/mcp"}
```

## Vídeos unlisted precisam do hash

O embed de um vídeo unlisted exige o hash de privacidade:

```
https://player.vimeo.com/video/76979871?h=8272103f6e
```

Montar a URL a partir do id perde o `?h=` e o player responde *"This video does
not exist"*. Por isso o backend guarda o `player_embed_url` **como a API
devolve** (coluna `videos.embed_url`) em vez de construir a URL, e a tool
`listar_videos_vimeo` repassa esse campo para a importação. Dois testes cobrem
o caso.

Se o vídeo estiver com **embed restrito por domínio**, libere `localhost` nas
configurações dele (*Where can this be embedded?*) — senão o player recusa
mesmo com o hash correto.

## Filtro de rede corporativa

Em 08/09/2026, na rede em que a POC foi desenvolvida, o Vimeo estava bloqueado
por filtro de DNS (OpenDNS). O mapa do bloqueio:

| host | uso | estado |
|---|---|---|
| `api.vimeo.com` | consultar pastas e vídeos | **bloqueado** |
| `vimeo.com` | links do acervo | **bloqueado** |
| `player.vimeo.com` | embed na tela do aluno | liberado |
| `i.vimeocdn.com` | thumbnails | liberado |

Ou seja: **o aluno consegue assistir, mas o agente não consegue consultar o
acervo.** O fluxo A da demonstração depende de `api.vimeo.com`.

Para conferir rapidamente onde você está:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://api.vimeo.com/
```

`401` significa liberado (a API pede autenticação). `403` com HTML de bloqueio
significa filtro no caminho.

O cliente detecta isso e devolve uma mensagem explicando, em vez de estourar um
erro de SSL no meio da apresentação:

> Não foi possível falar com https://api.vimeo.com (ConnectError). Verifique se
> a rede libera api.vimeo.com — filtros corporativos costumam bloquear o
> domínio.

**Antes da apresentação**, decida uma das opções: pedir a liberação do domínio,
apresentar de outra rede, ou rodar com o acervo de demonstração (deixando
`VIMEO_ACCESS_TOKEN` vazio) e explicar que a integração real está pronta mas
bloqueada pela rede.

## Estado da integração

A implementação real (`VimeoAPI`) **nunca foi exercida contra a API do Vimeo**,
porque a rede de desenvolvimento a bloqueia. O que está testado são o parsing
das respostas e o acervo de demonstração. Reserve tempo para o primeiro teste
em rede liberada: o esperado é que funcione, mas é a única parte do sistema sem
verificação de ponta a ponta.
