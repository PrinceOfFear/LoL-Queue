# Histórico de partida — placar nativo — Design

> Revisão do "Histórico" entregue em `2026-08-23-historico-de-partida-design.md`.
> O usuário testou ao vivo e pediu para refazer: a lista deve ficar igual à
> tela de histórico do próprio cliente do LoL, e cada partida precisa abrir
> um placar completo (as duas equipes, os 10 jogadores) ao ser clicada,
> também igual ao cliente.

## Contexto

A versão anterior mostra uma linha simples por partida (retrato, nome,
resultado, KDA, CS, duração, "há X min"). O cliente do LoL mostra bem mais
por linha — grade de itens, duas runas, nível sobre o retrato, gold — e
permite clicar para abrir um placar com as duas equipes completas, bans e
objetivos. É esse comportamento que este design replica.

### Verificado ao vivo (23/08/2026, cliente do LoL aberto, conta Princee#adc)

**`lol_list_summoner_matches` já devolve itens/runas/feitiços/nível/gold do
próprio jogador**, sem chamada extra. Pedido real:

```
data.game_history[].{id,created_at,game_length_second,game_type}
data.game_history[].participants[].{champion_id,champion_name,position,items[],items_names[],spells[],team_key}
data.game_history[].participants[].rune.{primary_page_id,primary_rune_id,secondary_page_id}
data.game_history[].participants[].stats.{kill,death,assist,minion_kill,neutral_minion_kill,result,champion_level,gold_earned}
```

Resposta real (nome/tag reais, id de partida real — mesma conta já usada nos
testes existentes):

```
class LolListSummonerMatches: data
class Data: game_history
class GameHistory: id,created_at,game_type,game_length_second,participants
class Participant: champion_id,champion_name,team_key,position,items,items_names,rune,spells,stats
class Rune: primary_page_id,primary_rune_id,secondary_page_id
class Stats: champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,result

LolListSummonerMatches(Data([GameHistory("wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=","2026-08-23T17:18:49+09:00","SOLORANKED",958,[Participant(54,"Malphite","BLUE","TOP",[1056,3802,1001,1029,1026],["Anel de Doran","Capítulo Perdido","Botas","Couraça de Pano","Varinha Explosiva"],Rune(8200,8229,8400),[4,12],Stats(10,0,4,0,79,0,3901,"LOSE"))]),GameHistory("wgqT90Iiz72Bsm3unOefxkCMsMc-e8bCFWQ9MpHIUIo=","2026-08-23T16:56:57+09:00","SOLORANKED",1522,[Participant(22,"Ashe","BLUE","ADC",[1086,3153,2003,3085,3123],["Arco de Doran","Espada do Rei Destruído","Poção de Vida","Furacão de Runaan","Chamado do Carrasco"],Rune(8000,8008,8300),[4,21],Stats(13,4,12,2,155,4,8902,"LOSE"))])]))
```

Pontos confirmados por essa resposta:

- `items[]`/`items_names[]` têm tamanho **variável** (3 a 6 no que veio de
  volta) — a build real da partida, sem preenchimento de slot vazio. A
  grade da linha desenha o que veio, não um número fixo de casas.
- `Rune(primary_page_id, primary_rune_id, secondary_page_id)` — apesar do
  nome, `primary_page_id` é o **id da árvore primária** (ex.: 8200 =
  Feitiçaria), não um id de página. O ícone da runa-chave vem de
  `PerkCatalog.perk(primary_rune_id).icon`; o da árvore secundária, de
  `PerkCatalog.style(secondary_page_id).icon`. Catálogo já carregado hoje
  em `window.py` (`self._perks`) — nenhuma consulta nova.
- `spells[]` são os dois ids de feitiço de invocador (ex.: `[4,12]` =
  Flash + Teleporte).

**`lol_get_summoner_game_detail` traz o placar completo.** Pedido real
(mesma partida, `focus_riot_id="Princee#adc"`):

```
data.game_detail.{id,created_at,game_length_second,game_type}
data.game_detail.average_tier_info.{tier,division}
data.game_detail.teams[].{key,banned_champions,banned_champions_names}
data.game_detail.teams[].game_stat.{is_win,champion_kill,tower_kill,dragon_kill,baron_kill,rift_herald_kill,gold_earned}
data.game_detail.teams[].participants[].{champion_id,champion_name,team_key,position,is_target,items[],items_names[],spells[]}
data.game_detail.teams[].participants[].rune.{primary_page_id,primary_rune_id,secondary_page_id}
data.game_detail.teams[].participants[].stats.{champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,total_damage_dealt_to_champions,result}
data.game_detail.teams[].participants[].summoner.{game_name,tagline}
```

Resposta real (truncada — confirma o esquema completo, 2 times × 5
jogadores, bans e objetivos):

```
class LolGetSummonerGameDetail: data
class Data: game_detail
class GameDetail: id,created_at,game_type,game_length_second,average_tier_info,teams
class AverageTierInfo: tier,division
class Team: key,game_stat,banned_champions,banned_champions_names,participants
class GameStat: is_win,champion_kill,rift_herald_kill,dragon_kill,baron_kill,tower_kill,gold_earned
class Participant: is_target,summoner,champion_id,champion_name,team_key,position,items,items_names,rune,spells,stats
class Summoner: game_name,tagline
class Rune: primary_page_id,primary_rune_id,secondary_page_id
class Stats: champion_level,total_damage_taken,total_damage_dealt_to_champions,vision_wards_bought_in_game,ward_place,kill,death,assist,largest_multi_kill,largest_killing_spree,minion_kill,neutral_minion_kill,gold_earned,result,op_score,op_score_rank

LolGetSummonerGameDetail(Data(GameDetail("wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=","2026-08-23T17:18:49+09:00","SOLORANKED",958,AverageTierInfo("EMERALD",2),[Team("BLUE",GameStat(false,8,0,0,0,0,24155),[25,55,141,412,910],["Morgana","Katarina","Kayn","Thresh","Hwei"],[Participant(false,Summoner("Blakien","br1"),200,"Bel'Veth","BLUE","JUNGLE",[1102,6672,1001,2152,1043],[...],Rune(8000,8008,8300),[4,11],Stats(8,15420,2682,0,4,1,9,0,1,0,2,74,4735,"LOSE",0,10)),Participant(true,Summoner("Princee","adc"),54,"Malphite","BLUE","TOP",[1056,3802,1001,1029,1026],[...],Rune(8200,8229,8400),[4,12],Stats(10,7764,4790,0,4,0,4,0,0,0,79,0,3901,"LOSE",1.14,9)), ... ]), Team("RED", GameStat(true,30,0,1,0,3,36881), [33,117,134,164,238], [...], [...5 participantes...])])))
```

Pontos confirmados:

- `is_target`/`is_win` chegam como token nu `true`/`false` (não string
  entre aspas) — `mcp_format` ainda não tem um `to_bool`; é preciso um.
- O esquema é sempre `Root(Data(GameDetail(... , [Team(..., [Participant(...), ...]), Team(..., [...])])))`
  — duas equipes, cada uma com a lista de participantes dela. O parser
  usa `mcp_format.entries()`/`unpack()` em cada nível, igual ao resto do
  módulo.
- `banned_champions`/`banned_champions_names` são listas paralelas de 5
  ids/nomes por equipe (`to_ints`/`to_strings`, já existentes).

**Ícones de item e feitiço vêm do próprio cliente**, mesmo endpoint-style
já usado para runas:

```
GET /lol-game-data/assets/v1/items.json            → lista de 868 dicts
GET /lol-game-data/assets/v1/summoner-spells.json  → lista de 39 dicts
```

Cada entrada tem `id` (int) e `iconPath` (str, formato
`/lol-game-data/assets/...`) — o mesmo formato que `PerkCatalog` já lê para
runas e que `AssetStore.path_for(url)` já sabe cachear. Exemplo real:
item 3153 → `iconPath: /lol-game-data/assets/ASSETS/Items/Icons2D/3153_Fighter_T3_BladeOfTheRuinedKing.png`;
feitiço 4 (Flash) → `iconPath: /lol-game-data/assets/DATA/Spells/Icons2D/Summoner_flash.png`.

## Objetivos

1. A lista de partidas de "Histórico" mostra, por linha: retrato do
   campeão com selo de nível, grade de itens (o que a partida realmente
   comprou, sem casas fixas), duas runas pequenas (chave + árvore
   secundária), resultado colorido (vitória/derrota), KDA, CS, gold,
   duração, modo e "há X min" — igual ao layout do cliente.
2. Clicar numa linha troca a lista pelo placar completo daquela partida,
   dentro da própria página (sem diálogo), com um botão de voltar:
   cabeçalho (resultado, modo, duração, data), duas equipes com
   KDA/gold total, uma linha por jogador (retrato+nível, runas, itens,
   KDA, CS, gold) e uma coluna de bans + objetivos (torres, dragões,
   barões, arauto) por equipe.
3. O histórico se atualiza sozinho quando uma partida termina, sem
   depender do clique em "Atualizar" (que continua existindo).
4. Ao final, o app é fechado, reconstruído e reaberto para verificação
   visual ao vivo, lado a lado com o cliente do LoL.

## Fora de escopo

- As abas "Visão Geral", "Estatísticas", "Gráficos" e "Runas" do placar
  nativo — só a aba "Placar" é replicada (decisão do usuário).
- Gráfico de dano/timeline (`op_score_timeline`) — não faz parte do
  placar, é conteúdo de "Gráficos".
- Qualquer polling novo por tempo (ex.: "checar a cada N minutos") — a
  atualização automática usa o sinal de fase que o watcher já emite.

## Arquitetura

### `core/mcp_format.py`

Novo helper, mesmo estilo de `to_int`/`to_float`:

```python
def to_bool(value: str) -> bool | None:
    text = value.strip()
    if text == "true":
        return True
    if text == "false":
        return False
    return None
```

### `core/summoner_history.py`

`MATCH_FIELDS` ganha os campos novos confirmados acima. `MatchSummary`
ganha:

```python
items: tuple[int, ...]
item_names: tuple[str, ...]
spells: tuple[int, int]
primary_style_id: int      # Rune.primary_page_id
primary_rune_id: int       # Rune.primary_rune_id
secondary_style_id: int    # Rune.secondary_page_id
champion_level: int
gold: int
```

`_match_summaries` passa a ler `items`/`items_names` (`to_ints`/
`to_strings`), `rune` (sub-`unpack` com o schema `Rune`), `spells`
(`to_ints`, exige exatamente 2), `champion_level`/`gold_earned`
(`to_int`). Uma linha sem qualquer um desses campos é descartada, mesma
regra de tolerância a falha do resto do parser.

Novas dataclasses e função para o placar:

```python
@dataclass(frozen=True)
class ParticipantDetail:
    is_target: bool
    game_name: str
    tag_line: str
    champion_id: int
    champion_name: str
    team_key: str        # "BLUE" | "RED"
    position: str
    items: tuple[int, ...]
    item_names: tuple[str, ...]
    spells: tuple[int, int]
    primary_style_id: int
    primary_rune_id: int
    secondary_style_id: int
    champion_level: int
    kills: int
    deaths: int
    assists: int
    cs: int
    gold: int
    damage_to_champions: int
    result: str           # "WIN" | "LOSE"

@dataclass(frozen=True)
class TeamDetail:
    key: str               # "BLUE" | "RED"
    win: bool
    kills: int
    towers: int
    dragons: int
    barons: int
    heralds: int
    gold: int
    banned_champion_ids: tuple[int, ...]
    banned_champion_names: tuple[str, ...]
    participants: tuple[ParticipantDetail, ...]

@dataclass(frozen=True)
class GameDetail:
    match_id: str
    duration_seconds: int
    queue_type: str
    played_at: datetime
    teams: tuple[TeamDetail, TeamDetail]
    average_tier: str | None
```

`SummonerHistorySource.fetch_game_detail`:

```python
def fetch_game_detail(
    self,
    match_id: str,
    played_at: datetime,
    region: str,
    game_name: str,
    tag_line: str,
    lang: str = DEFAULT_LANG,
) -> GameDetail | None:
```

Chama `lol_get_summoner_game_detail` com `region`, `game_id=match_id`,
`created_at=played_at.isoformat()`, `focus_riot_id=f"{game_name}#{tag_line}"`,
`game_name`, `tag_line`, `lang`, `desired_output_fields=GAME_DETAIL_FIELDS`.
Mesma regra de falha do resto do módulo: rede fora ou campo faltando vira
`None`, nunca exceção.

### `core/items.py` (novo) e `core/spells.py` (novo)

Cópias reduzidas de `PerkCatalog` — só o pedaço id→ícone, sem a lógica de
fileira/estilo que só runa precisa:

```python
class ItemCatalog:
    def __init__(self, client) -> None: ...
    def load(self) -> None: ...          # GET endpoints.ITEMS, tolera falha
    @property
    def loaded(self) -> bool: ...
    def icon_path(self, item_id: int) -> str: ...   # "" se desconhecido
    def icons(self) -> list[str]: ...                # para o fetch_missing
```

`SpellCatalog` é o mesmo desenho, sobre `endpoints.SUMMONER_SPELLS`.

### `lcu/endpoints.py`

```python
ITEMS = "/lol-game-data/assets/v1/items.json"
SUMMONER_SPELLS = "/lol-game-data/assets/v1/summoner-spells.json"
```

### `ui/icon_loader.py`

`IconLoader` passa a carregar também os dois catálogos novos, na mesma
viagem que já carrega `PerkCatalog` — mesmo motivo de hoje (dado estático,
lento, que a tela só precisa mais tarde; não vale outra thread). Sinal
novo, sem mexer no contrato de `perks_ready`:

```python
#: `(ItemCatalog, SpellCatalog)`, os dois já com os ícones no disco.
catalogs_ready = Signal(object, object)
```

`_load_perks` (renomeado mentalmente, mesmo método) carrega runas como
hoje e, na sequência, os dois catálogos novos, baixando os ícones deles
no mesmo `AssetStore` (é genérico por URL — nenhum cache novo). Emite
`catalogs_ready` depois de perks_ready, mesma regra de "só avisa se
carregou".

### `ui/game_detail_loader.py` (novo)

Mesmo molde de `history_loader.py`: descobre credenciais, resolve a
região da identidade atual e chama `fetch_game_detail`. Uma consulta por
vez, controlada pela janela do mesmo jeito que os loaders existentes.

```python
class GameDetailLoader(QThread):
    ready = Signal(object)  # GameDetail | None

    def __init__(self, source: SummonerHistorySource, match: MatchSummary, parent=None) -> None: ...
    def run(self) -> None: ...
```

### `ui/window.py`

- `self._items = ItemCatalog | None`, `self._spells = SpellCatalog | None`,
  populados em `_on_catalogs_ready` (conectado a `catalogs_ready`).
- `_item_icon(item_id)` e `_spell_icon(spell_id)`: mesmo padrão de
  `_rune_icon(url)` já existente — resolvem via catálogo + `self._assets`.
- `_open_game_detail(match)`: cria um `GameDetailLoader`, guarda a
  referência (mesmo padrão de `_history_loader`), no `ready` chama
  `self._history.set_game_detail(detail)`.
- `_on_phase_changed`: ao entrar em `GameflowPhase.END_OF_GAME`, chama
  `self._refresh_history()` — é o gatilho da atualização automática
  (pedido novo do usuário). Sem polling: o histórico muda quando uma
  partida termina, não em qualquer outro momento.
- `closeEvent`: espera também o `_game_detail_loader`, se houver um
  rodando, mesmo padrão dos outros loaders.

### `ui/pages/history.py`

- Linha da lista redesenhada: retrato com selo de nível sobreposto, grade
  de ícones de item (tamanho igual ao de `match.items`, sem casas vazias
  fixas), duas runas pequenas abaixo da grade, faixa de cor
  verde/vermelha no resultado, KDA, CS, gold, duração, modo, "há X min".
  A linha passa a ser um `_ClickableFrame(QFrame)` local ao módulo — um
  `QFrame` que sobrescreve `mousePressEvent` para emitir um sinal
  `clicked` próprio — em vez do `QFrame` comum usado hoje. A página ouve
  esse `clicked` de cada linha e emite `match_selected = Signal(object)`
  com o `MatchSummary` daquela linha.
- Nova visão de placar, num `QWidget` separado dentro da mesma página:
  cabeçalho (resultado, modo, duração, data) + botão "Voltar", dois
  blocos de equipe (nome da fila objetiva, KDA/gold somados dos 5,
  coluna de bans+ícones de objetivo), cada bloco com 5 linhas de jogador
  (retrato+nível, runas, itens, nome, KDA, CS, gold — o `is_target`
  destacado). A alternância entre lista e placar usa o mesmo mecanismo
  de mostrar/esconder que já separa `_content`/`_empty`: lista e placar
  vivem lado a lado no layout, e só um fica visível por vez.
- `set_game_detail(detail: GameDetail | None)`: desenha o placar;
  `None` volta para a lista (falha de rede ao abrir o detalhe).
- Resolução de ícone de item/feitiço chega por dois `set_*_resolver`
  novos, mesmo padrão de `set_icon_resolver`/`set_name_resolver` já
  existentes.

## Testes

- `core/mcp_format.py`: `to_bool` — três casos (`"true"`, `"false"`,
  lixo → `None`).
- `core/summoner_history.py`: `_match_summaries` com a resposta real
  capturada acima (nome/tag trocados por fictícios, como já é convenção
  no arquivo) cobrindo itens de tamanho variável, runas, feitiços,
  nível, gold; `fetch_game_detail` com a resposta real de
  `lol_get_summoner_game_detail` capturada acima, cobrindo as duas
  equipes, bans, objetivos e o participante marcado `is_target`; casos
  de falha (resposta vazia, campo faltando, exceção de rede) → `None`,
  como já é o padrão do arquivo.
- `core/items.py`/`core/spells.py`: `load()` com uma lista fake de
  dicts (`id`+`iconPath`), `icon_path()` de id conhecido e desconhecido,
  falha de rede tolerada (`LcuError` → catálogo vazio).
- `ui/pages/history.py`: linha de partida desenha a grade de itens do
  tamanho certo e as duas runas; clique emite `match_selected` com o
  `MatchSummary` certo; `set_game_detail` desenha as duas equipes e o
  volta-à-lista some o placar e reexibe a lista.
- `ui/window.py`: `_on_phase_changed` com fase `EndOfGame` dispara
  `_refresh_history()` (reaproveita o mesmo teste de "uma consulta por
  vez" que os loaders já têm); `_open_game_detail` sem loader corrente
  cria um; um já em andamento não dispara um segundo.
- `IconLoader`/`GameDetailLoader`: sem teste unitário próprio, mesmo
  padrão de `HistoryLoader` hoje — são wrappers finos de thread; a
  integração é verificada ao vivo no fim, com o cliente do LoL aberto.

Verificação final ao vivo: fechar a instância do app já aberta, gerar o
build novo, abrir, navegar até "Histórico", comparar a lista e o placar
com a tela equivalente do cliente do LoL (aberto ao lado), clicar em uma
partida e conferir que os dados batem com os já usados nos testes
(mesma conta Princee#adc).
