# Conectar o MCP ao claude.ai

## Por que não bastava o token

A POC emite um token Bearer opaco por operador (§5 do MVP, simplificação
assumida). Isso resolve o Claude Code e os scripts: o token vai num header fixo
no arquivo de configuração do cliente.

```json
{ "portal-aluno": { "type": "http", "url": "https://SEU-APP/mcp",
                    "headers": { "Authorization": "Bearer pvm_..." } } }
```

**Conector personalizado do claude.ai não tem esse campo.** Ele recebe só uma
URL, bate no servidor, leva `401 WWW-Authenticate: Bearer` e sai procurando os
metadados de OAuth na raiz do domínio. Sem eles, desiste — e a conversa do
outro lado nem fica sabendo que o servidor existe: o modelo responde que não
encontrou conector nenhum, e vai tentar outra coisa.

Por isso o servidor passou a falar as duas línguas. Quem chega com token opaco
continua entrando; quem chega sem nada é mandado para o GitHub, volta com uma
identidade, e o backend decide se essa pessoa opera.

## Criar o app OAuth no GitHub

[github.com/settings/developers](https://github.com/settings/developers) →
**OAuth Apps** → **New OAuth App**:

| campo | valor |
|---|---|
| Application name | qualquer coisa (aparece na tela de autorização) |
| Homepage URL | `https://SEU-APP.up.railway.app` |
| Authorization callback URL | `https://SEU-APP.up.railway.app/auth/callback` |

O callback é o padrão do FastMCP (`redirect_path`). Errar esse caminho é o
motivo nº 1 de o login voltar com `redirect_uri_mismatch`.

Gere um **client secret** na mesma tela e copie os dois valores.

## Configurar o servidor

No Railway (ou no `.env`, em desenvolvimento):

```bash
MCP_BASE_URL=https://SEU-APP.up.railway.app      # a raiz, sem /mcp
MCP_OAUTH_GITHUB_CLIENT_ID=Ov23li...
MCP_OAUTH_GITHUB_CLIENT_SECRET=...
MCP_OAUTH_OPERADORES=SeuLoginNoGitHub=professor@escola.demo
```

`MCP_BASE_URL` é a **raiz**, não o endpoint do MCP: é dela que saem
`/authorize`, `/token` e os `/.well-known/...`, que o cliente procura na raiz.
O endpoint em si continua em `/mcp`, e é ele que a metadata anuncia como
recurso protegido.

Faltando qualquer uma das três primeiras, o servidor sobe como sempre foi — só
o token Bearer. É assim que a POC roda na máquina de quem desenvolve, sem
precisar de app OAuth nenhum.

### O mapa de operadores

O GitHub diz quem entrou; quem decide se essa pessoa opera é o cadastro daqui.
`MCP_OAUTH_OPERADORES` liga um ao outro:

```
MCP_OAUTH_OPERADORES=EduardoJMenezes=professor@escola.demo, outra=chefe@escola.demo
```

Sem entrada no mapa, vale o e-mail **público** do perfil do GitHub, se existir
como ADMIN ou GERENCIADOR. Como a maioria das contas não publica e-mail, na
prática quem resolve é o mapa, pelo login.

Quem não casar com nenhum operador não abre sessão: recebe 401, não um catálogo
de ferramentas que não poderia usar. Aluno mapeado também não entra — o papel
continua mandando (§4).

## Adicionar o conector no claude.ai

Configurações → **Conectores** → **Adicionar conector personalizado** → cole:

```
https://SEU-APP.up.railway.app/mcp
```

O claude.ai vai abrir o GitHub, pedir autorização e voltar. Depois disso as
tools aparecem na conversa (pode ser preciso habilitar o conector no seletor de
ferramentas daquela conversa).

## Conferir sem abrir o navegador

```bash
curl -s https://SEU-APP.up.railway.app/.well-known/oauth-protected-resource/mcp
```

Tem que sair JSON com `"resource": "https://SEU-APP.up.railway.app/mcp"`. Se
voltar HTML, o portal estático está na frente das rotas de OAuth — ver a
armadilha de ordem de montagem no [CLAUDE.md](../CLAUDE.md).

```bash
curl -si -X POST https://SEU-APP.up.railway.app/mcp -d '{}' | head -5
```

Tem que ser `401` com `www-authenticate: Bearer ... resource_metadata="..."`.
É seguindo essa URL que o cliente descobre o resto.

## Por dentro

```
claude.ai ──► /authorize ──► GitHub ──► /auth/callback ──► /token
                                                             │
                                          JWT do FastMCP ◄────┘
                                                 │
          toda chamada ──► verify_token ──► GitHub /user ──► operador daqui
```

O FastMCP entrega ao cliente um JWT **dele**, que serve de referência para o
token do GitHub guardado no servidor (*token swap*). A cada chamada ele valida
o token upstream e devolve quem é; `GitHubDaPlataforma.verify_token` completa
esse resultado com o operador correspondente, e daí para baixo tudo segue igual
— `identidade_da_sessao()` não sabe por qual porta a pessoa entrou.

Os registros de cliente e os tokens ficam no Postgres (tabela `oauth_mcp_kv`,
criada sozinha). O padrão do FastMCP seria um arquivo em disco, que no Railway
morre a cada deploy: o conector cairia toda vez que subisse uma versão.

## Quando der errado

| sintoma | causa provável |
|---|---|
| `redirect_uri_mismatch` no GitHub | callback do app OAuth diferente de `<base>/auth/callback` |
| `.well-known` devolve HTML | portal estático montado antes das rotas de OAuth |
| conecta e toda tool dá 401 | login do GitHub fora de `MCP_OAUTH_OPERADORES`, ou mapeado para alguém que não é ADMIN/GERENCIADOR |
| conector cai depois de um deploy | `DATABASE_URL` sem Postgres — o armazenamento voltou a ser o disco efêmero |
| `POST /register` responde 500 | o armazenamento não conectou no Postgres; o log traz `StoreSetupError` com o motivo |
| o Claude Code parou de entrar | o token opaco continua valendo; confira se o header não se perdeu na configuração do cliente |

## O que isto significa para a arquitetura

A §5 do MVP manda seguir o padrão de autorização do MCP para servidores
HTTP/OAuth, e permitiu a simplificação do token opaco **desde que documentada
como simplificação**. Este documento é o outro lado dessa conta: o caminho do
OAuth agora existe de verdade, e o token opaco continua como conveniência de
quem opera pelo terminal.

O que não mudou — e é o ponto — é de onde vem a autorização. O GitHub só diz
quem é a pessoa. O que ela pode fazer continua decidido pelo papel dela no
backend, a cada chamada, exatamente como antes.
