# LoL Queue

Aceita a partida, mantém a fila andando e cuida da escolha e do
banimento de campeão. Conversa com o cliente do League pela LCU API — a
mesma interface que o próprio cliente usa — em vez de olhar a tela e
apertar teclas, então não depende de resolução, tema nem de a janela
estar na frente.

## Como abrir

Crie o atalho uma vez:

```powershell
powershell -ExecutionPolicy Bypass -File tools\criar-atalho.ps1
```

Aparece um `LoL Queue.lnk` na pasta do projeto. Duplo clique nele abre o
app sem janela preta de console. Para deixar o atalho na área de
trabalho, acrescente `-AreaDeTrabalho` ao comando.

Pela linha de comando, o equivalente é `pythonw main.py` — o `w` no fim
do nome é justamente a versão do Python que não abre console. Rodar
`python main.py` funciona igual, mas deixa a janela preta aberta junto.

### E o executável?

`py -m PyInstaller lolqueue.spec` gera um `dist\LoL Queue.exe` que roda
sozinho, sem Python instalado. Só que o **Smart App Control** do Windows
11 bloqueia executável sem assinatura reconhecida, e foi o que aconteceu
aqui — desligá-lo é permanente, então o atalho acima é o caminho mais
sensato nesta máquina. Em um Windows sem Smart App Control o `.exe`
funciona normalmente.

## O que ele faz

- **Aceita a partida** assim que o convite aparece.
- **Fila contínua**: entra na fila, volta para ela quando a partida
  acaba e reabre o lobby quando o cliente larga o jogador na tela
  inicial. Também percebe a busca que morre sozinha — o cliente erra ao
  procurar partida de vez em quando e fica parado sem avisar.
- **Escolhe e bane campeão** por lista de prioridade, com lista separada
  por rota quando você quiser.
- **Aplica runas e feitiços** para o campeão e a rota, se você ligar.
  A recomendação sai do OP.GG — o que mais venceu em Diamante+ — e a
  do próprio cliente entra no lugar quando o OP.GG não responde, não
  cobre o modo ou demora demais. O Flash fica na tecla que você já
  usa. A página criada se chama "LoL Queue" e é a única que o app
  mexe; as suas ficam intactas.
- **Monta o arsenal na loja**, se você ligar. Vira um conjunto de
  itens do campeão com seis blocos — iniciais, botas, principais e
  as três opções mais jogadas de quarto, quinto e sexto item —, cada
  um com a taxa de vitória no título. Sem dados do OP.GG nenhum
  conjunto é criado: aqui não há reserva da Riot, porque a
  recomendação do cliente não traz itens. O conjunto se chama
  "LoL Queue" e é o único que o app mexe; os do Porofessor, do
  U.GG e os seus ficam onde estão.
- **Respeita a sala de quem convidou**: com "só mexer na fila quando eu
  for o dono da sala" ligado, na sala de um amigo ele não inicia a busca
  nem abre sala própria, mas continua aceitando, banindo e escolhendo.
- **Marca fila desligada**: a Riot liga e desliga fila por região e
  temporada, e a lista mostra quais o cliente não aceita agora.

## Configuração e registro

A config fica em `%APPDATA%\LoLQueue\config.json` e o registro em
`%APPDATA%\LoLQueue\registro\`. O botão "abrir pasta", no painel, leva
direto ao registro — útil depois da partida para conferir qual lista foi
usada e se o banimento entrou.

## Desenvolvimento

```powershell
py -m pytest          # a suíte inteira, sem precisar do cliente aberto
py tools\preview_pages.py     # desenha as páginas em PNG, sem abrir janela
```

Os testes não tocam a config real: cada um escreve num diretório
temporário.

O código separa quem fala com a Riot (`lolqueue/lcu/`), quem decide
(`lolqueue/core/`) e quem desenha (`lolqueue/ui/`). As duas primeiras
camadas não importam nada de Qt, e é por isso que a suíte roda sem
janela e sem cliente do LoL.
