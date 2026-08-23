# Histórico de partida — Design

Nova página que mostra o perfil do jogador (nick, nível, elo) e as
últimas partidas jogadas (resultado, campeão, KDA, duração, modo),
puxados do OP.GG.

## Contexto

O app já fala com uma fonte externa para runas e itens: o servidor MCP
público do OP.GG (`mcp-api.op.gg`, sem chave), em `core/opgg.py`. A
mesma pesquisa que validou essa integração original mostrou que o
mesmo servidor também expõe perfil e histórico de partidas — dá para
reaproveitar a infraestrutura já existente em vez de integrar uma
segunda fonte.

Duas alternativas foram descartadas:

- **Riot API oficial** — chave de desenvolvedor expira a cada 24h
  (inviável para um app que roda sozinho todo dia); chave de produção
  exige aprovação da Riot, processo pensado para projetos maiores.
- **Histórico local do cliente (LCU)** — endpoint não-documentado que
  só funciona com o cliente aberto e devolveria a partida inteira (10
  participantes) para parsear, por um ganho que o OP.GG já entrega
  pronto e filtrado para o jogador certo.

### Verificado ao vivo (23/08/2026, cliente do LoL aberto)

`/lol-summoner/v1/current-summoner` devolve `gameName`, `tagLine`,
`summonerLevel`, entre outros. `/riotclient/region-locale` (rota do
Riot Client, servida pela mesma conexão do LCU) devolve um campo
`region` em maiúsculas (`"BR"`) — exatamente o formato que o MCP do
OP.GG pede (`"Server region code Examples: KR, BR, EUNE"`). Não é
necessária nenhuma tabela de tradução de região.

`tools/list` no MCP do OP.GG confirmou os nomes exatos das ferramentas
e seus `inputSchema`:

- `lol_get_summoner_profile(game_name, tag_line, region, lang,
  desired_output_fields)` → nível, ícone, elo por fila
  (`league_stats[]` com `game_type`, `tier_info`, `win`, `lose`).
- `lol_list_summoner_matches(game_name, tag_line, region, lang, limit
  [5–20], desired_output_fields)` → histórico com **um único
  participante por partida** (o próprio jogador buscado — o servidor já
  filtra), com campeão, resultado, KDA, CS, `game_length_second`,
  `game_type`, `created_at` (ISO 8601 com fuso).

Uma chamada real a cada ferramenta confirmou que a resposta chega no
mesmo formato compacto que `opgg.py` já sabe ler (`class X:
campo,campo` seguido de `Nome(valor,valor,...)`), então o parser
existente é reaproveitável quase sem mudança.

## Objetivos

1. Mostrar nick#tag, nível e elo (por fila) do jogador.
2. Mostrar as últimas 10 partidas: vitória/derrota, campeão, KDA, CS,
   duração, modo e há quanto tempo foi jogada.
3. Nova entrada na barra lateral, entre Análise e Campeões.

## Fora de escopo

Detalhe de uma partida específica (os 10 participantes), busca de
outro invocador que não o do cliente conectado, atualização automática
em tempo real, gráfico de progresso de elo. Nada disso foi pedido;
não implementar por antecipação.

## Arquitetura

```
lolqueue/core/
  mcp_format.py         parser do formato compacto do MCP do OP.GG,
                         extraído de opgg.py (rede + schema + unpack)
  opgg.py                passa a importar de mcp_format; comportamento
                         inalterado (Build, Stats, Counter, Synergy)
  summoner_history.py    Profile, RankEntry, MatchSummary,
                         SummonerHistorySource — usa mcp_format
  identity.py             current_identity(client): lê
                         current-summoner + region-locale da LCU
lolqueue/lcu/
  endpoints.py            + RIOT_REGION_LOCALE
lolqueue/ui/
  history_loader.py       QThread: identity → SummonerHistorySource
  pages/history.py        HistoryPage
  widgets/sidebar.py       + seção "Histórico"
  window.py                monta a página, liga o loader
```

### core/mcp_format.py

Extrai de `opgg.py` as partes que não são específicas de build de
campeão: a ida à rede (`send_tool`, JSON-RPC contra
`mcp-api.op.gg/mcp`) e o parser do formato compacto (`schema`,
`unpack`, `entries`, `first`, conversões `ints`/`floats`/`strings`).
`opgg.py` importa dali; suas classes públicas (`Build`, `OpggSource`,
`parse_build`) e o teste existente (`test_opgg.py`, que só usa essa
API pública) não mudam de comportamento.

Refatoração justificada por necessidade direta: sem ela,
`summoner_history.py` duplicaria ~150 linhas de parser.

### core/summoner_history.py

```python
@dataclass(frozen=True)
class RankEntry:
    queue_type: str            # "SOLORANKED", "FLEXRANKED", ...
    tier: str | None           # None = sem elo na fila
    division: int | None
    lp: int | None
    wins: int
    losses: int

@dataclass(frozen=True)
class Profile:
    game_name: str
    tag_line: str
    level: int
    ranks: tuple[RankEntry, ...] = ()

@dataclass(frozen=True)
class MatchSummary:
    match_id: str
    champion_id: int
    champion_name: str         # em inglês; a UI troca pelo nome PT-BR
                                # do catálogo já carregado quando existir
    result: str                 # "WIN" | "LOSE"
    kills: int
    deaths: int
    assists: int
    cs: int
    duration_seconds: int
    queue_type: str
    position: str
    played_at: datetime         # timezone-aware, de created_at

class SummonerHistorySource:
    def fetch_profile(self, game_name, tag_line, region,
                       lang="pt_BR") -> Profile | None: ...
    def fetch_matches(self, game_name, tag_line, region,
                       lang="pt_BR", limit=10) -> tuple[MatchSummary, ...]: ...
```

Mesma regra de falha que `OpggSource`: qualquer problema (rede, campo
faltando, formato mudou) devolve `None`/`()`, nunca uma exceção para
quem chama. Sem cache — histórico envelhece rápido, ao contrário de
build de campeão.

### core/identity.py

```python
@dataclass(frozen=True)
class Identity:
    game_name: str
    tag_line: str
    region: str
    level: int

def current_identity(client) -> Identity | None: ...
```

Lê os dois endpoints da LCU e devolve `None` se qualquer campo faltar
ou a chamada falhar (`LcuError`) — mesmo padrão de "falha vira estado
vazio" do resto do app.

### ui/history_loader.py

`QThread` no molde de `MatchupLoader`: descobre credenciais, monta o
`LcuClient`, resolve a identidade, busca perfil e partidas, emite
`ready(profile, matches)`. Uma consulta por vez, disparada ao abrir a
página e por um botão "Atualizar" — sem polling nem tempo real, para
não competir com a thread do motor.

### ui/pages/history.py

Cabeçalho com nick#tag, nível e elo (texto — sem baixar o ícone de
perfil remoto: os únicos ícones que o app já sabe buscar e cachear são
os de campeão, por id, via LCU; puxar uma imagem de URL arbitrária do
OP.GG seria um mecanismo novo para um ganho cosmético, cortado por
YAGNI). Abaixo, uma linha por partida: retrato do campeão (reaproveita
`IconStore`, quando já baixado — mesmo padrão de `AnalysisPage`, com
`icon_path` opcional), resultado, nome do campeão, KDA, CS, duração,
modo e tempo relativo ("há 2 h"). Sem cliente, sem identidade resolvida
ou falha do OP.GG: mesmo aviso de vazio que `AnalysisPage` já usa.

`relative_time(played_at, now) -> str` é uma função pura em
`core/summoner_history.py`, testável sem Qt: "agora", "há N min", "há
N h", "há N dias".

### Fiação em window.py

Nova página na posição entre Análise e Campeões — desloca os índices
seguintes; `SECTIONS` em `sidebar.py` muda na mesma ordem, e
`test_window.py` (que já existe para pegar esse tipo de dessincronia)
é atualizado junto. `MainWindow` guarda `SummonerHistorySource()` como
atributo de instância (sobrevive à reconexão, como `_opgg` e
`_matchups`), cria o `HistoryLoader` sob pedido, mantém a referência
enquanto ele roda (mesmo cuidado do `_matchup_loader` para não deixar
o Python coletar a thread cedo) e espera-o em `closeEvent`.

## Testes

- `core/mcp_format.py`: cobrível pelos testes já existentes de
  `opgg.py`, que passam a exercitar o código movido.
- `core/summoner_history.py`: `send` fake devolvendo o texto real
  capturado nas chamadas de verificação ao vivo — perfil com elo em
  duas filas e uma sem dados, partidas com vitória e derrota. Casos de
  falha: resposta vazia, campo faltando, exceção de rede.
- `core/identity.py`: client fake (dict de respostas por rota); casos
  de sucesso, campo faltando, `LcuError`.
- `relative_time`: minutos, horas, dias, e o limite "agora".
- `test_window.py`: dicionário `esperado` ganha `"Histórico":
  HistoryPage`; os dois testes de alinhamento continuam sem mudança de
  lógica.
