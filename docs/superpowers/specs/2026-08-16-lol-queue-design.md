# LoL Queue — Design

Reescrita do bot de fila do League of Legends. Substitui a automação por
visão computacional (`bot.py`) por integração direta com a API local do
cliente do jogo, e a interface Tkinter por um app PySide6.

## Contexto

A versão atual tira screenshots do monitor, procura quatro imagens de
botão por template matching, força foco na janela do LoL e clica com
movimentos de mouse humanizados. A abordagem é frágil por construção:
depende de resolução, escala do Windows e tema do cliente; exige o jogo
em primeiro plano; e sequestra o mouse do usuário.

O cliente do LoL expõe uma API REST local (LCU API) autenticada por um
`lockfile` gerado na inicialização. Ler a fase do jogo e aceitar uma
partida por essa via é determinístico, funciona com o jogo minimizado e
não toca no mouse.

## Objetivos

1. Aceitar a partida automaticamente ao entrar em ready-check.
2. Manter o ciclo de fila contínuo: entrar na fila, aceitar, jogar,
   voltar ao lobby, repetir.
3. Escolher e banir campeões na seleção conforme uma lista de
   prioridade do usuário.
4. Interface desktop que mostra estado de forma legível e bonita.

## Fora de escopo

Estatísticas de sessão, ícone na bandeja, notificações do Windows e
alertas sonoros. Foram considerados e descartados pelo usuário. Não
implementar por antecipação.

## Restrições

- Windows 11, Python 3.14.3 (`py`), PySide6 6.11.1 (já instalado).
- Instalação do LoL em `C:\Riot Games\League of Legends`, mas o caminho
  não pode ser fixo no código — deve ser descoberto.
- Automação do cliente contradiz os ToS da Riot. O usuário foi
  informado e aceitou o risco. O app não deve esconder o que faz.

## Arquitetura

```
lolqueue/
  __main__.py            ponto de entrada
  config.py              dataclass de config + persistência JSON
  lcu/
    credentials.py       descoberta de porta e token
    client.py            sessão HTTP autenticada, erros tipados
    endpoints.py         constantes de rota
  core/
    phases.py            enum GameflowPhase
    watcher.py           QThread de polling → sinais Qt
    engine.py            máquina de estados fase → ação
    champ_select.py      resolução de ban e pick
    champions.py         catálogo id↔nome, em cache
  ui/
    app.py               QApplication e janela principal
    theme.py             paleta e QSS
    widgets/             StatusRing, Sidebar, ChampionPicker, LogPane
tests/
```

Regra de dependência: `core/` e `lcu/` não importam nada de `ui/`. A
comunicação sobe por sinais Qt. É isso que permite testar o motor sem
abrir janela.

### lcu/credentials.py

Descobre como falar com o cliente. Duas estratégias, nessa ordem:

1. **Lockfile.** Arquivo `lockfile` na raiz da instalação, conteúdo
   `LeagueClient:<pid>:<porta>:<senha>:https`. O caminho da instalação
   vem do registro do Windows ou da linha de comando do processo; nunca
   fixo no código.
2. **Linha de comando do processo.** `LeagueClientUx.exe` recebe
   `--app-port=` e `--remoting-auth-token=`. Serve quando o lockfile
   está inacessível.

Autenticação é HTTP Basic com usuário `riot` e a senha descoberta,
contra `https://127.0.0.1:<porta>`. O certificado é autoassinado da
Riot; a verificação TLS fica desligada, aceitável por o destino ser
sempre loopback.

Expõe `discover() -> Credentials | None`. Retorna `None` quando o
cliente não está aberto — isso é estado normal, não erro.

### lcu/client.py

Envelopa `requests.Session` com as credenciais, timeout curto (2 s) e
tradução de falhas em exceções tipadas: `ClientClosed` (conexão
recusada — o LoL fechou), `LcuError` (resposta HTTP de erro). Métodos
`get`, `post`, `patch`, `delete` recebendo caminho relativo.

Erros nunca sobem crus para a UI. `ClientClosed` derruba o estado para
"desconectado" e o watcher recomeça a descoberta.

### core/watcher.py

`QThread` que a cada 250 ms consulta `/lol-gameflow/v1/gameflow-phase`.
Emite:

- `phase_changed(GameflowPhase)` — apenas em transição, não a cada tick
- `connection_changed(bool)`
- `error(str)`

Quando desconectado, tenta redescobrir credenciais a cada 2 s em vez de
1 s, para não gastar CPU com o cliente fechado.

### core/engine.py

Máquina de estados. Recebe transições de fase e decide a ação:

| Fase | Ação |
|---|---|
| `None` | nada. Sem lobby, sem ação. |
| `Lobby` | se auto-fila ligada e o usuário for líder, `POST /lol-lobby/v2/lobby/matchmaking/search` |
| `Matchmaking` | nada. Já está na fila. |
| `ReadyCheck` | `POST /lol-matchmaking/v1/ready-check/accept` |
| `ChampSelect` | delega a `champ_select` |
| `GameStart`, `InProgress`, `Reconnect` | nada. O usuário está jogando. |
| `WaitingForStats`, `PreEndOfGame`, `EndOfGame` | se auto-fila ligada, `POST /lol-lobby/v2/play-again` |
| `TerminatedInError`, `FailedToLaunch` | registra e volta para ocioso |

O motor nunca age quando desligado. Uma única flag `enabled` guarda a
entrada de todas as ações.

**Backoff.** Se uma ação falhar três vezes seguidas na mesma fase, o
motor para de tentar naquela fase e registra o motivo. Evita martelar a
API quando o usuário não é líder do lobby ou a fila está indisponível.

### core/champ_select.py

Ao entrar em `ChampSelect`, faz polling de
`/lol-champ-select/v1/session` a cada 500 ms enquanto a fase durar. Da
sessão extrai `localPlayerCellId` e a lista `actions`.

Esse polling roda na mesma thread do `watcher`, intercalado com o de
fase — nunca em uma segunda thread. Só existe um dono das chamadas
HTTP, o que elimina disputa sobre a `Session` e mantém a ordem dos
eventos previsível. O atraso antes de travar não pode bloquear a
thread: é contado entre ticks, não com `sleep`.

Age apenas na ação onde `actorCellId == localPlayerCellId`,
`isInProgress` é verdadeiro e `completed` é falso. Para essa ação:

1. Escolhe o campeão: desce a lista de prioridade do usuário (uma para
   ban, outra para pick) e pega o primeiro presente em
   `/lol-champ-select/v1/bannable-champion-ids` ou
   `/lol-champ-select/v1/pickable-champion-ids`.
2. Faz *hover*: `PATCH .../actions/{id}` com `{"championId": N}`.
3. Espera o atraso configurável (padrão 3 s) — janela para o usuário
   cancelar.
4. Trava: `PATCH .../actions/{id}` com `{"championId": N,
   "completed": true}`.

Se nenhum campeão da lista estiver disponível, **não trava nada** e
emite um aviso visível. Escolher algo aleatório seria pior que não
agir.

### core/champions.py

Busca `/lol-game-data/assets/v1/champion-summary.json` uma vez por
sessão e monta o mapa id↔nome usado pela UI e pela config. Em cache na
memória; se a busca falhar, a UI mostra IDs e segue funcionando.

### config.py

Dataclass serializada em `%APPDATA%\LoLQueue\config.json`:

```
auto_accept: bool = True
auto_queue: bool = False
auto_pick: bool = False
auto_ban: bool = False
queue_id: int = 420
pick_priority: list[int] = []
ban_priority: list[int] = []
lock_delay_seconds: float = 3.0
```

Config ausente ou corrompida cai nos padrões e regrava o arquivo, sem
travar a inicialização.

### Interface

Janela sem moldura nativa, 980×640, cantos arredondados, barra de
título própria com arrastar, minimizar e fechar.

Paleta:

| Papel | Cor |
|---|---|
| Fundo | `#0A1428` |
| Superfície | `#10203A` |
| Acento | `#C8AA6E` |
| Ativo | `#0AC8B9` |
| Perigo | `#E84057` |
| Texto | `#F0E6D2` / `#A09B8C` secundário |

O elemento central é o **StatusRing**: anel desenhado com `QPainter`
que muda de cor e de rótulo conforme a fase, com cronômetro de fila em
números tabulares no centro. Sidebar com quatro seções: Painel,
Campeões, Fila, Ajustes. O `LogPane` é recolhível e discreto — não é o
protagonista, ao contrário da versão atual.

A UI só desenha estado. Não conhece a API, não contém regra de decisão.

**Atalhos globais.** F5 liga o motor, F6 desliga. F6 tem prioridade
sobre qualquer ação em andamento.

## Erros

- Cliente do LoL fechado: estado "desconectado" na UI, sem popup de
  erro. É a situação normal quando o jogo não está aberto.
- Falha de rede na ação: registra no log, conta para o backoff, mantém
  o motor ligado.
- Campeão preferido indisponível: aviso visível, nenhuma ação.
- Config corrompida: cai nos padrões, avisa no log.

Nenhum caminho de erro deve derrubar a janela.

## Testes

`credentials`, `client`, `engine` e `champ_select` são lógica pura,
testados contra um cliente LCU falso. Testes escritos antes do código.

Casos que precisam de cobertura:

- Lockfile bem formado, malformado e ausente
- Fallback pela linha de comando do processo
- Cada transição de fase da tabela do `engine`
- Motor desligado não age em nenhuma fase
- Backoff dispara após três falhas seguidas
- Ready-check expira sem aceitar
- Cliente fecha no meio de um ciclo
- Campeão preferido banido por outro jogador → cai para o próximo
- Nenhum campeão da lista disponível → não trava nada
- Ação de outro jogador na sessão não dispara ação nossa

A UI é validada ao vivo com o cliente do LoL aberto, não por teste
automatizado.

## Verificação de endpoints

As rotas abaixo são a base do design e **devem ser confirmadas contra o
cliente real** no início da implementação, com o LoL aberto. A LCU API
não é documentada oficialmente e muda entre patches.

```
GET    /lol-gameflow/v1/gameflow-phase
POST   /lol-matchmaking/v1/ready-check/accept
GET    /lol-lobby/v2/lobby
POST   /lol-lobby/v2/lobby
POST   /lol-lobby/v2/lobby/matchmaking/search
DELETE /lol-lobby/v2/lobby/matchmaking/search
POST   /lol-lobby/v2/play-again
GET    /lol-champ-select/v1/session
PATCH  /lol-champ-select/v1/session/actions/{actionId}
GET    /lol-champ-select/v1/pickable-champion-ids
GET    /lol-champ-select/v1/bannable-champion-ids
GET    /lol-game-data/assets/v1/champion-summary.json
```

O campo que indica liderança do lobby (necessário para decidir se
podemos iniciar a fila) precisa ser identificado na resposta real de
`/lol-lobby/v2/lobby` — o design assume que existe, mas não fixa o
nome.

## Migração

`bot.py`, `bot.spec`, `setup.py`, `imagens/`, `build/`, `dist/` e os
PNGs de debug ficam intactos até a versão nova rodar de ponta a ponta
na máquina do usuário. A remoção é uma decisão separada, dele.

## Decisões registradas

**Polling em vez de WebSocket.** O cliente expõe eventos push via WAMP
sobre wss, o que daria latência zero. Rejeitado: a janela de
ready-check dura 10 s e a de pick, ~30 s — 250 ms de latência é
irrelevante, e o WAMP traria protocolo próprio, certificado
autoassinado sobre wss, ponte asyncio↔Qt e reconexão manual. Se algum
dia a latência importar, trocar o `watcher` é substituir um módulo.

**PySide6 em vez de UI web ou Flet.** Aplicativo desktop de verdade,
empacotável em `.exe`, com controle fino do visual via QSS e `QPainter`
para o anel de estado.

**Hover antes de travar, com atraso.** Dá ao usuário uma janela real
para cancelar e reduz a aparência de automação instantânea.
