# LoL Queue 0.2.1

- Adiciona uma verificacao local de seguranca em **Ajustes**, sem enviar token,
  configuracoes ou dados da conta para a internet.
- Reforca a conexao autenticada com o cliente do LoL: somente loopback, sem
  proxy herdado e sem redirecionamentos.
- Exige HTTPS e bloqueia redirecionamentos na comunicacao com o servidor de
  licencas.
- Cada distribuicao oficial agora leva um manifesto de integridade Ed25519 com
  SHA-256 de todos os arquivos; qualquer alteracao ou arquivo extra e exibido
  pela verificacao.
- A verificacao de seguranca deixou de ocupar espaco na interface de Ajustes;
  ela continua rodando internamente e registrando falhas no log local.
- O atualizador ganhou um aviso destacado, acionavel em qualquer tela, e um
  botao de suporte que abre o WhatsApp no numero (64) 99296-1405.
- O arsenal do OP.GG passou a publicar caminhos separados quando ha dados
  suficientes: recomendacao principal, "Mais jogada", "Maior taxa" e uma
  alternativa validada. Cada aba usa somente itens medidos para o campeao,
  rota e elo consultados.
