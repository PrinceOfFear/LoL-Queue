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
#: Rotas pedidas na fila. PUT, com `{"firstPreference": ..., "secondPreference": ...}`
#: em maiúsculas: TOP, JUNGLE, MIDDLE, BOTTOM, UTILITY, FILL ou
#: UNSELECTED. O que ficou guardado sai no próprio lobby, em
#: `localMember.firstPositionPreference` — confirmado na fixture. É
#: por ali que o motor confere antes de mandar, e é por ali que dá
#: para ver se esta rota parou de valer num patch novo: o pedido
#: falha ou não gruda, e o registro diz.
LOBBY_POSITION_PREFERENCES = (
    "/lol-lobby/v2/lobby/members/localMember/position-preferences"
)
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

#: As configurações do jogo em si, não do cliente: interface, minimapa,
#: câmera, volume, o que aparece na tela durante a partida. GET devolve
#: o bloco inteiro; PATCH mescla só o que for mandado — o resto fica
#: como estava (confirmado contra o cliente real, gravando de volta o
#: mesmo valor e comparando o antes e o depois byte a byte).
GAME_SETTINGS = "/lol-game-settings/v1/game-settings"
#: As teclas: habilidades, feitiços de invocador, itens, movimentação,
#: pings, câmera, loja. `GameEvents` tem as teclas propriamente ditas e
#: `Quickbinds` diz quais habilidades saem no toque (smartcast). PATCH
#: mescla, igual à rota de cima.
INPUT_SETTINGS = "/lol-game-settings/v1/input-settings"
#: Rota do Riot Client (não do LCU), servida pela mesma conexão. O
#: campo `region` vem em maiúsculas ("BR", "KR", "EUNE") — exatamente
#: o formato que o MCP do OP.GG pede para identificar o servidor.
RIOT_REGION_LOCALE = "/riotclient/region-locale"
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
#: As cinco árvores de runa, com os slots de cada uma na ordem em que o
#: jogo as desenha: a chave (`kKeyStone`), três fileiras comuns
#: (`kMixedRegularSplashable`) e três de fragmento (`kStatMod`). É o que
#: permite mostrar a página no formato da tela do jogo em vez de uma
#: lista solta de ids.
PERK_STYLES = "/lol-perks/v1/styles"
#: Cada runa individual: nome, descrição curta e `iconPath`. Os ícones
#: saem de `/lol-game-data/assets/...`, servidos pelo próprio cliente.
PERKS = "/lol-perks/v1/perks"
#: Recomendação da Riot para um campeão numa rota. Devolve três opções;
#: a primeira é a padrão. Traz as runas e também `summonerSpellIds`, o
#: que resolve feitiços e runas numa chamada só. `position` aceita
#: "NONE", e aí a Riot responde pela rota natural do campeão; vazio dá
#: 400.
PERK_RECOMMENDED = (
    "/lol-perks/v1/recommended-pages"
    "/champion/{champion_id}/position/{position}/map/{map_id}"
)

#: Catálogo de filas com disponibilidade por região e temporada. A Riot
#: liga e desliga fila sem avisar, e criar lobby numa fila desligada
#: responde 500 sem explicar o motivo.
GAME_QUEUES = "/lol-game-queues/v1/queues"

#: Conjuntos de itens do jogador — o arsenal que aparece na loja. GET
#: devolve a lista inteira e PUT a substitui por completo: não existe
#: acrescentar um só. Quem usa Porofessor ou Blitz tem dezenas guardadas
#: aqui, então toda gravação parte de uma leitura.
ITEM_SETS = "/lol-item-sets/v1/item-sets/{summoner_id}/sets"

#: Catálogo de itens do patch atual — nome (não usado aqui) e
#: `iconPath` de cada um. Serve para desenhar a grade de itens do
#: histórico de partidas, que só vem com o id.
ITEMS = "/lol-game-data/assets/v1/items.json"
#: Idem, para os feitiços de invocador (Fulgor, Barreira, ...).
SUMMONER_SPELLS = "/lol-game-data/assets/v1/summoner-spells.json"

#: Opções do jogo. O cliente aceita PATCH parcial: manda só a seção e as
#: chaves que mudam, e devolve o resto intacto.
GAME_SETTINGS = "/lol-game-settings/v1/game-settings"
