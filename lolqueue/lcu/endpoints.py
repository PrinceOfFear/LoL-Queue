"""Rotas da LCU API.

A LCU API não é documentada oficialmente e muda entre patches. A sonda
em `tools/probe_lcu.py` confirma cada rota daqui contra o cliente real
antes do resto do app depender delas.
"""

GAMEFLOW_PHASE = "/lol-gameflow/v1/gameflow-phase"
READY_CHECK_ACCEPT = "/lol-matchmaking/v1/ready-check/accept"
LOBBY = "/lol-lobby/v2/lobby"
MATCHMAKING_SEARCH = "/lol-lobby/v2/lobby/matchmaking/search"
#: Estado da busca. É o único lugar que revela uma fila que morreu: o
#: cliente deixa `searchState` em "Error" sem trocar de fase, e assim
#: continua até alguém cancelar a busca estragada.
MATCHMAKING_SEARCH_STATE = "/lol-lobby/v2/lobby/matchmaking/search-state"
PLAY_AGAIN = "/lol-lobby/v2/play-again"
CHAMP_SELECT_SESSION = "/lol-champ-select/v1/session"
CHAMP_SELECT_ACTION = "/lol-champ-select/v1/session/actions/{action_id}"
PICKABLE_CHAMPIONS = "/lol-champ-select/v1/pickable-champion-ids"
#: NÃO use para decidir o que banir. Apesar do nome, o cliente responde
#: apenas `[-1]` — um sentinela, não a lista de campeões. Filtrar por ela
#: zerava o banimento automático numa ranqueada de verdade. Quem pode ser
#: banido sai da própria sessão, em `ChampSelectController._already_taken`.
BANNABLE_CHAMPIONS = "/lol-champ-select/v1/bannable-champion-ids"
CHAMPION_SUMMARY = "/lol-game-data/assets/v1/champion-summary.json"
CHAMPION_ICON = "/lol-game-data/assets/v1/champion-icons/{champion_id}.png"
CURRENT_SUMMONER = "/lol-summoner/v1/current-summoner"
#: Sessão do gameflow. Usada só para descobrir o mapa: a recomendação de
#: runas muda entre a Fenda (11) e o Abismo (12), e a sessão da seleção
#: de campeões não diz em qual dos dois se está.
GAMEFLOW_SESSION = "/lol-gameflow/v1/session"
CHAMP_SELECT_MY_SELECTION = "/lol-champ-select/v1/session/my-selection"

#: Páginas de runas do jogador. POST cria e devolve a página com id;
#: DELETE remove. Quantas cabem sai de PERK_INVENTORY, em
#: `canAddCustomPage` — a conta não é o número de páginas, porque parte
#: dos espaços vem de recompensa de nível.
PERK_PAGES = "/lol-perks/v1/pages"
PERK_PAGE = "/lol-perks/v1/pages/{page_id}"
PERK_INVENTORY = "/lol-perks/v1/inventory"
#: Ativa uma página. O corpo é o id cru, um inteiro solto — não um
#: objeto com o id dentro.
PERK_CURRENT_PAGE = "/lol-perks/v1/currentpage"
#: Recomendação da Riot para um campeão numa rota. Devolve três opções;
#: a primeira é a padrão. Traz as runas e também `summonerSpellIds`, o
#: que resolve feitiços e runas numa chamada só. `position` aceita
#: "NONE", e aí a Riot responde pela rota natural do campeão; vazio dá
#: 400.
PERK_RECOMMENDED = (
    "/lol-perks/v1/recommended-pages"
    "/champion/{champion_id}/position/{position}/map/{map_id}"
)
