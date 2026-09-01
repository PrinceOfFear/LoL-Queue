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

### Como abrir no dia a dia

```powershell
powershell -ExecutionPolicy Bypass -File tools\atalho.ps1
```

Cria um atalho "LoL Queue" na Área de Trabalho que abre o app pelo
`pythonw.exe` — sem janela de console, com o ícone certo na barra de
tarefas. Rode uma vez; depois é só o atalho.

### Levar para outra máquina

Copie a pasta do projeto inteira e rode, dentro dela, uma vez:

```powershell
powershell -ExecutionPolicy Bypass -File tools\instalar.ps1
```

Ele confere o Python, instala as dependências lendo o `pyproject.toml`,
confirma que cada uma responde ao `import` e cria o atalho. Se faltar o
Python, ele diz onde baixar em vez de falhar no meio.

A conferência do import não é redundante com o `pip`: "instalou" e
"importa" são coisas diferentes, e a diferença aqui é cara. O app é
aberto pelo `pythonw.exe`, que não tem console — numa máquina sem as
dependências, o import morre, o erro não vai para lugar nenhum e o duplo
clique não produz nada, nem janela nem aviso. Foi assim que o app "não
funcionou" no outro PC. Por isso o `main.py` também pergunta antes de
abrir e, quando falta algo, põe uma caixa do Windows na tela dizendo o
nome do que falta e o comando acima.

O que o app procura sozinho na máquina nova: a instalação do League
(pelo processo em execução, depois nos lugares prováveis e por fim
varrendo os discos). Nada disso está preso a `C:`.

### E o executável?

```powershell
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

Gera `Distribuicao\LoL Queue\LoL Queue.exe` e também o arquivo
`Distribuicao\LoL Queue-<versão>-win64.zip`. O ZIP é o arquivo certo para
enviar: ele já leva a pasta inteira que precisa ser extraída antes de abrir o
app. Nunca copie somente o `.exe`, pois as DLLs, módulos e imagens ao lado dele
fazem parte do programa. A compilação fica separada em
`build\distribuicao-nuitka`, para não se confundir com a entrega.
Depois do build, `Distribuicao\ENVIAR PARA OUTRAS PESSOAS` contém somente os
dois ZIPs atuais e explica qual enviar em cada caso.

O build usa Nuitka em vez de PyInstaller: compila o Python para C e gera binário nativo, então
não dá pra extrair o `.exe` e decompilar de volta pra algo parecido com
o código-fonte — o que o PyInstaller sozinho não impede (`lolqueue.spec`
ainda existe no repositório por referência, mas não é mais o caminho
usado). Rebuilda sempre que o código ou os assets mudarem; o build é
lento porque está compilando C de verdade.

O build fixa a base do processador em `x86_64`, em vez de herdar AVX2 do PC
que compilou. Isso evita o fechamento imediato com `0xC000001D` em CPUs x64
mais antigas. A edição `instalação-python` continua disponível como alternativa
compatível caso um PC ainda não consiga abrir o executável.

### Atualização pelo aplicativo

A partir da versão 0.1.2, abra **Ajustes** e use **Verificar atualizações**.
O LoL Queue consulta a release oficial no GitHub, valida a assinatura e o
SHA-256 do pacote antes de baixar e reinicia com segurança. A instalação por
Python recebe somente o pacote compatível por Python; ela nunca é trocada pelo
executável compilado. A primeira instalação da 0.1.2 ainda precisa ser enviada
manualmente, pois versões anteriores não tinham o atualizador embutido.

### Verificação de segurança

Em **Ajustes**, use **Verificar segurança** para conferir localmente a âncora
das atualizações assinadas, a proteção da conexão com o cliente do LoL e a
integridade dos arquivos instalados. A distribuição oficial inclui um
manifesto Ed25519 com os hashes SHA-256 da pasta inteira: arquivos alterados,
ausentes ou adicionados são avisados na tela. A verificação não envia token,
configurações ou dados da conta para fora do computador.

O `tools\build.ps1` exige a chave privada local de atualização para assinar os
dois pacotes. `-AllowUnsignedIntegrity` existe apenas para testes locais; um
pacote criado nesse modo não deve ser enviado a outras pessoas.

**Numa máquina com o Smart App Control ligado, esse `.exe` não abre** —
e não há conserto pelo lado do código. O Smart App Control recusa
binário sem assinatura e sem reputação, e todo build novo nasce sem as
duas coisas: o executável recém-compilado foi bloqueado na primeira
tentativa (`Microsoft-Windows-CodeIntegrity/Operational`, evento 3118) e
continuou bloqueado nas seguintes, tanto pelo PowerShell quanto pelo
Explorer. O que passaria é um certificado de code signing comprado de
uma autoridade reconhecida, e mesmo assim só depois de ganhar
reputação. Foi por isso que o atalho acima virou o jeito de abrir: o
`pythonw.exe` da Python Software Foundation já vem assinado, então o
mesmo código roda sem esbarrar na política.

Duas coisas que o build já aprendeu e vale não desaprender: `--standalone`
em vez de `--onefile`, porque no modo onefile o programa vive numa
`main.dll` extraída pro `%TEMP%` e o Smart App Control derruba DLL sem
assinatura (o app abria e morria com "Imagem Incorreta", status
`0xc0e90002`); e desligar o Smart App Control resolveria tudo isso, mas
é permanente — uma vez desligado, só volta reinstalando o Windows.

### Licenciamento mensal

O código do servidor fica em `servidor/` e não é copiado para a instalação do
jogador. Ele mantém a chave de ativação presa ao resumo do computador, emite
bilhetes Ed25519 com validade curta e renova o acesso somente enquanto a
assinatura mensal estiver ativa. O webhook autenticado do PicPay atualiza o
vencimento; o aplicativo nunca recebe cartão ou segredo do provedor.

Antes de gerar uma versão para venda, configure o servidor HTTPS, o plano do
PicPay e a chave pública no build com `tools/preparar_build.py`. O
`tools/build.ps1` recusa, por padrão, qualquer build sem licença embutida.
`-AllowUnlicensed` existe apenas para teste local e a pasta resultante não deve
ser distribuída.

O checkout externo fica em `GET /checkout`. Ele usa o SDK oficial do PicPay no
navegador e envia ao servidor apenas o `temporaryCardToken`; a ativação só
ocorre quando o webhook autenticado confirma os R$ 20,00. Em produção, defina
`CHECKOUT_API_BASE_URL` e uma lista exata em `CHECKOUT_ALLOWED_ORIGINS`.

Para repetir a checagem local (compilação, padrões perigosos, segredos e
testes), use `py -3.14 tools/auditar_seguranca.py --tests --release`. A revisão
profunda do plugin `codex-security` deve ser executada no Codex após recarregar
o plugin; ela não é substituída por este script local.

## O que ele faz

- **Aceita a partida** assim que o convite aparece.
- **Fila contínua**: entra na fila, volta para ela quando a partida
  acaba e reabre o lobby quando o cliente larga o jogador na tela
  inicial. Também percebe a busca que morre sozinha — o cliente erra ao
  procurar partida de vez em quando e fica parado sem avisar.
- **Escolhe e bane campeão** por lista de prioridade, com lista separada
  por rota quando você quiser.
- **Mostra o campeão no cliente do LoL antes da sua vez**: o retrato de
  quem a lista vai travar aparece sobre o seu quadro na tela de
  seleção, para você e para o time, enquanto os banimentos correm — o
  mesmo efeito de clicar num campeão sem confirmar. Só declara a
  intenção: quem trava continua sendo a sua vez, no atraso configurado.
  Espera alguns segundos antes de aparecer (oito, por padrão), porque a
  sessão existe na API antes de a tela de seleção terminar de carregar —
  sem essa espera o time inteiro via o seu pick antes de você mesmo ver
  a tela, e sobrava tempo pra encher o saco. Dá para desligar nos
  Ajustes.
- **Silencia chat e emotes durante a seleção**: desliga o chat do time,
  o chat geral (o `/all`, por onde vem o inimigo) e os emotes dos
  inimigos assim que a seleção começa, e devolve tudo como estava
  quando a partida acaba, quando você desliga o motor, quando desmarca
  a opção ou quando fecha o app. Emote de aliado o jogo não deixa
  desligar — não existe opção pra isso — e a sua própria roda de emotes
  fica intacta de propósito.
- **Reordena a prioridade sem sair da Central**: a lista que está
  valendo naquela partida — a geral ou a da rota que o cliente
  atribuiu, dito ali mesmo — pode ser arrastada, ou movida pelas setas,
  no painel ao lado das runas. O primeiro da lista é o que vai ser
  escolhido, e a prévia muda junto. A página Campeões continua sendo o
  lugar de montar as listas; as duas telas mostram sempre a mesma
  ordem.
- **Aplica runas e feitiços** para o campeão e a rota, se você ligar.
  A recomendação sai do OP.GG — o que mais venceu no elo escolhido nos
  Ajustes, de Ferro a Desafiante, com Diamante+ como padrão — e a do
  próprio cliente entra no lugar quando o OP.GG não responde, não
  cobre o modo ou demora demais. O Flash fica na tecla que você já
  usa. A página criada se chama "LoL Queue" e é a única que o app
  mexe; as suas ficam intactas. Ligando as opções de runa, ele
  pergunta também por Diamante+, Mestre e Desafiante e mostra na
  Central o que voltou de verdade — até três builds, uma por elo, com
  elos que devolvem a mesma página virando um botão só e elo sem
  resposta simplesmente não aparecendo. Um clique troca a página
  aplicada durante a seleção; sem clique nenhum, a do elo escolhido
  nos Ajustes já entrou sozinha. Ao consultar um adversário na Análise,
  o mesmo painel oferece as páginas de runa medidas para aquele confronto
  — incluindo a de maior taxa quando ela passa os pisos de amostra — sem
  trocar a runa ativa automaticamente.
- **Monta o arsenal na loja**, se você ligar. Vira um ou mais
  conjuntos de itens do campeão — uma aba por caminho — com iniciais,
  botas, núcleo e compras situacionais na ordem correta. A aba principal
  mantém as alternativas medidas lado a lado; quando há amostra suficiente,
  o app também publica os caminhos "Mais jogada", "Maior taxa" e
  "Alternativa validada", no mesmo estilo de um overlay de pré-jogo. Sem
  dados do OP.GG nenhum conjunto é criado: não há itens inventados nem
  reserva da Riot. Os conjuntos se chamam "LoL Queue" e são os únicos que
  o app mexe; os do Porofessor, do U.GG e os seus ficam onde estão.
- **Respeita a sala de quem convidou**: com "só mexer na fila quando eu
  for o dono da sala" ligado, na sala de um amigo ele não inicia a busca
  nem abre sala própria, mas continua aceitando, banindo e escolhendo.
- **Guarda um perfil por conta**: lista de campeões, rotas pedidas,
  tecla do Flash e tempos são de quem está logado, não do computador.
  Uma conta é marcada como principal, e quem nunca entrou aqui começa
  com o app dela — é o que se quer ao jogar na conta de outra pessoa.
- **Leva as configurações de dentro do LoL entre as contas**: com a
  conta principal logada, "Guardar config do jogo" tira uma cópia das
  teclas das habilidades, dos feitiços de invocador e dos itens, da
  movimentação, da interface, da câmera e do minimapa. Toda conta que
  entrar depois recebe essas configurações sozinha, alguns segundos
  após o login — o cliente ainda está baixando os ajustes da conta
  nova quando anuncia quem entrou, então a cópia espera e é refeita
  uma segunda vez. Qualidade gráfica e modo de vídeo ficam de fora de
  propósito: são do computador.
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
py tools\preview_pages.py     # desenha as 6 páginas + o laboratório de build
```

As prévias usam as fontes Spiegel e Beaufort empacotadas e desviam a config
para uma pasta temporária. Os ícones de Flash/Barreira, brasões de elo, mapas e
rotas também viajam com o app, então a interface mantém a mesma aparência sem
depender da internet ou das fontes instaladas no computador. A origem de cada
asset está registrada em `lolqueue/assets/SOURCES.md`.

Os testes não tocam a config real: cada um escreve num diretório
temporário.

O código separa quem fala com a Riot (`lolqueue/lcu/`), quem decide
(`lolqueue/core/`) e quem desenha (`lolqueue/ui/`). As duas primeiras
camadas não importam nada de Qt, e é por isso que a suíte roda sem
janela e sem cliente do LoL.
