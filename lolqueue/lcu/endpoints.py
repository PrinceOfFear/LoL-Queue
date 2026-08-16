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
