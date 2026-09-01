"""O que o OP.GG sabe sobre o campeão travado, para ler.

Nada nesta página é aplicado no cliente, e essa é a diferença que
justifica ela existir separada do painel. Runas, feitiços e arsenal o
app monta sozinho; ordem de habilidade não tem endpoint no LCU, e
confronto e boletim são informação de decisão, não de configuração.

Tudo aqui vem de carona: são campos da mesma resposta que o equipamento
já pede para montar runas e itens, então a página não custa uma consulta
a mais. Se a resposta não veio — rede fora, campeão sem dados — a seção
correspondente simplesmente não aparece, em vez de mostrar um número
inventado.

A página não se limpa quando a seleção acaba, de propósito. A ordem de
habilidade é justamente o que se consulta **durante** a partida, com o
jogo já rodando; apagá-la ao entrar em jogo tiraria o dado na hora exata
em que ele serve.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...config import OPGG_TIERS, POSITION_NAMES
from ..widgets.illustrated_empty import IllustratedEmptyState
from ..widgets.loadout_studio import rank_pixmap

PORTRAIT = QSize(56, 56)
COUNTER_ICON = QSize(28, 28)
ANALYSIS_RANK = QSize(54, 54)
RANK_LABEL_TO_KEY = {label.casefold(): tier for tier, label in OPGG_TIERS.items()}

#: Como o OP.GG chama as rotas nas duplas, e como se diz aqui.
LANES = {
    "TOP": "Topo",
    "JUNGLE": "Selva",
    "MID": "Meio",
    "ADC": "Atirador",
    "SUPPORT": "Suporte",
}

#: A nota do OP.GG. Tier 1 é o topo; o resto desce daí.
TIERS = {1: "OP", 2: "Forte", 3: "Bom", 4: "Fraco", 5: "Ruim"}

#: Quantos confrontos cabem em cada coluna sem virar lista de rolagem.
COUNTER_LIMIT = 3


#: A tela não pode chamar de "vazia" situações que têm conserto.  A
#: análise depende de um campeão confirmado, da rota que o cliente realmente
#: publicou e da consulta externa; cada etapa ganha uma explicação própria.
#: Isso é especialmente importante numa instalação nova, onde automação e
#: build começam desligadas por segurança.
EMPTY_STATES = {
    "client_disconnected": (
        "ANÁLISE CONTEXTUAL",
        "Conecte o cliente do League",
        "A análise usa o campeão e a rota que o próprio cliente do LoL "
        "confirmar.",
        "Abra o cliente do League of Legends e entre em uma conta.",
    ),
    "automation_paused": (
        "ANÁLISE CONTEXTUAL",
        "A automação está pausada",
        "O LoL Queue busca a build durante a seleção somente enquanto a "
        "automação estiver ligada.",
        "Na Central, clique em INICIAR AUTOMAÇÃO.",
    ),
    "build_disabled": (
        "ANÁLISE CONTEXTUAL",
        "A consulta de build está desligada",
        "Runas, feitiços e arsenal estão todos desativados, por isso não há "
        "uma build para a Análise acompanhar.",
        "Em Ajustes, ative runas, feitiços ou Montar o arsenal na loja.",
    ),
    "awaiting_route": (
        "ANÁLISE CONTEXTUAL",
        "Aguardando a rota confirmada",
        "O cliente ainda não informou a sua rota. O LoL Queue não inventa "
        "uma posição para consultar uma build errada.",
        "Aguarde a seleção terminar de carregar ou confirme o campeão.",
    ),
    "timed_out": (
        "ANÁLISE CONTEXTUAL",
        "O OP.GG demorou para responder",
        "A automação seguiu sem esperar para não atrapalhar a seleção. "
        "Se a resposta chegar, esta tela e o arsenal serão atualizados nesta "
        "mesma seleção.",
        "Confira a conexão com a internet e mantenha o LoL Queue aberto.",
    ),
    "no_data": (
        "ANÁLISE CONTEXTUAL",
        "O OP.GG não trouxe uma build agora",
        "Não há dados suficientes para este campeão, rota e elo, ou a "
        "consulta externa está indisponível no momento.",
        "Tente outra seleção ou escolha outro elo nos Ajustes.",
    ),
    "awaiting_champion": (
        "ANÁLISE CONTEXTUAL",
        "A leitura começa na seleção",
        "Assim que um campeão for confirmado, você verá ordem de "
        "habilidades, confrontos, sinergias e o desempenho da build.",
        "Abra o cliente e entre em uma seleção de campeões.",
    ),
}


class SkillRow(QWidget):
    """A sequência de subida, uma casinha por nível.

    As casas de ultimato ganham marca própria: nos níveis 6, 11 e 16 a
    escolha não existe, e destacá-las evita que a fileira seja lida como
    se as quinze fossem decisões iguais.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(4)

    def set_order(self, order: tuple[str, ...]) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Sair do layout não tira da tela: sem soltar o pai, a
                # ordem anterior ficaria desenhada por baixo da nova.
                widget.setParent(None)
                widget.deleteLater()
        for level, skill in enumerate(order, start=1):
            cell = QLabel(skill)
            cell.setObjectName("skillCell")
            cell.setProperty("ultimate", "true" if skill == "R" else "false")
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setFixedSize(26, 30)
            cell.setToolTip(f"Nível {level}")
            self._row.addWidget(cell)
        self._row.addStretch(1)


class AnalysisPage(QWidget):
    """Leitura do campeão travado: subida, confrontos e duplas."""

    #: O usuário escolheu contra quem está na rota. Vai o alias, que é
    #: como o OP.GG conhece o campeão, e a rota. Quem busca é a janela:
    #: esta página não faz rede.
    matchup_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._resolve_icon = None
        # De quem é a análise na tela agora. O confronto precisa dos
        # dois lados, e este é o lado que não vem do seletor.
        self._alias = ""
        self._position = ""
        self._has_analysis = False
        self._empty_state = "awaiting_champion"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(14)

        wording = QVBoxLayout()
        wording.setSpacing(1)
        title = QLabel("ANÁLISE DO CAMPEÃO")
        title.setObjectName("pageTitle")
        wording.addWidget(title)
        subtitle = QLabel(
            "O que o OP.GG mediu sobre quem você vai jogar — para ler, "
            "não para aplicar."
        )
        subtitle.setObjectName("pageSubtitle")
        wording.addWidget(subtitle)
        layout.addLayout(wording)

        # O aviso de vazio e o conteúdo se revezam: um dos dois está
        # sempre escondido, e nunca os dois ao mesmo tempo.
        self._empty = IllustratedEmptyState(
            asset="maps/summoners-rift.png",
            mini_assets=(
                "positions/top.png",
                "positions/middle.png",
                "positions/bottom.png",
            ),
            eyebrow=EMPTY_STATES["awaiting_champion"][0],
            title=EMPTY_STATES["awaiting_champion"][1],
            detail=EMPTY_STATES["awaiting_champion"][2],
            footnote=EMPTY_STATES["awaiting_champion"][3],
        )
        layout.addWidget(self._empty)

        self._content = QWidget()
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)
        layout.addWidget(self._content)
        self._content.hide()

        content.addWidget(self._build_hero())
        content.addWidget(self._build_skills())
        content.addWidget(self._build_matchup())
        content.addWidget(self._build_counters())
        content.addWidget(self._build_synergies())
        content.addStretch(1)

    @property
    def has_analysis(self) -> bool:
        """Se a página ainda guarda uma leitura válida para a partida."""
        return self._has_analysis

    def set_empty_state(self, state: str, *, force: bool = False) -> None:
        """Explica precisamente por que não há dados para mostrar.

        Uma análise pronta continua útil dentro da partida e não deve
        desaparecer só porque o cliente saiu da seleção.  Quem sabe que uma
        nova consulta falhou usa ``force=True`` para trocar a leitura antiga
        pelo diagnóstico atual.
        """
        if self._has_analysis and not force:
            return
        copy = EMPTY_STATES.get(state, EMPTY_STATES["no_data"])
        self._empty_state = state if state in EMPTY_STATES else "no_data"
        self._empty.set_copy(
            eyebrow=copy[0], title=copy[1], detail=copy[2], footnote=copy[3]
        )
        self._has_analysis = False
        self._content.hide()
        self._empty.show()

    # ---------- montagem ----------

    def _build_hero(self) -> QFrame:
        card = QFrame()
        card.setObjectName("heroCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(24, 16, 24, 16)
        row.setSpacing(18)

        self._portrait = QLabel()
        self._portrait.setObjectName("miniPortrait")
        self._portrait.setFixedSize(PORTRAIT)
        self._portrait.setScaledContents(True)
        row.addWidget(self._portrait, 0, Qt.AlignmentFlag.AlignVCenter)

        naming = QVBoxLayout()
        naming.setSpacing(2)
        self._name = QLabel()
        self._name.setObjectName("heroHeadline")
        naming.addWidget(self._name)
        self._where = QLabel()
        self._where.setObjectName("heroDetail")
        naming.addWidget(self._where)
        row.addLayout(naming)
        row.addStretch(1)

        self._tier_crest = QLabel()
        self._tier_crest.setObjectName("analysisRankCrest")
        self._tier_crest.setFixedSize(ANALYSIS_RANK)
        self._tier_crest.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._tier_crest, 0, Qt.AlignmentFlag.AlignVCenter)

        # O boletim. Cada número mora numa caixinha própria para poder
        # sumir sozinho quando o campo não vier.
        self._stats = QHBoxLayout()
        self._stats.setSpacing(22)
        row.addLayout(self._stats)
        return card

    def _build_skills(self) -> QFrame:
        self._skills_card = QFrame()
        self._skills_card.setObjectName("optionCard")
        box = QVBoxLayout(self._skills_card)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(12)
        label = QLabel("ORDEM DE HABILIDADES")
        label.setObjectName("predictionEyebrow")
        header.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._max_order = QLabel()
        self._max_order.setObjectName("cardValue")
        header.addWidget(self._max_order, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        # O cliente não sabe montar isto sozinho, e dizer o porquê evita
        # a leitura de que a automação deixou de funcionar.
        note = QLabel("o cliente não aplica ordem de habilidade")
        note.setObjectName("hint")
        header.addWidget(note, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(header)

        self._skills = SkillRow()
        box.addWidget(self._skills)
        return self._skills_card

    def _build_matchup(self) -> QFrame:
        """O confronto, que só existe quando alguém diz contra quem é.

        O cliente do LoL não revela a rota dos adversários, então não há
        como saber com certeza quem é o seu oponente de faixa — inferir
        pelo campeão daria palpite, e palpite aqui vira conselho errado.
        Perguntar custa um clique e acerta sempre.
        """
        self._matchup_card = QFrame()
        card = self._matchup_card
        card.setObjectName("optionCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(12)
        label = QLabel("CONFRONTO NA ROTA")
        label.setObjectName("predictionEyebrow")
        header.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._opponent = QComboBox()
        self._opponent.setObjectName("opponentPicker")
        self._opponent.setMinimumWidth(190)
        self._opponent.setToolTip("Contra quem você está na rota.")
        self._opponent.currentIndexChanged.connect(self._on_opponent_chosen)
        header.addWidget(self._opponent, 0, Qt.AlignmentFlag.AlignVCenter)
        self._matchup_state = QLabel()
        self._matchup_state.setObjectName("hint")
        header.addWidget(self._matchup_state, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        box.addLayout(header)

        self._verdict = QLabel()
        self._verdict.setObjectName("cardValue")
        self._verdict.setWordWrap(True)
        box.addWidget(self._verdict)
        self._verdict.hide()

        self._tip = QLabel()
        self._tip.setObjectName("heroDetail")
        self._tip.setWordWrap(True)
        box.addWidget(self._tip)
        self._tip.hide()

        # A dica vem do OP.GG só em inglês — em português o servidor
        # devolve resposta vazia. Dizer isso é melhor do que deixar o
        # usuário achar que o app deixou de traduzir alguma coisa.
        self._tip_note = QLabel("o OP.GG publica estas dicas apenas em inglês")
        self._tip_note.setObjectName("hint")
        box.addWidget(self._tip_note)
        self._tip_note.hide()
        return card

    def _build_counters(self) -> QWidget:
        self._counters_card = QWidget()
        row = QHBoxLayout(self._counters_card)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        self._strong, strong_card = self._counter_column("VOCÊ COSTUMA VENCER")
        self._weak, weak_card = self._counter_column("VOCÊ COSTUMA APANHAR")
        row.addWidget(strong_card, 1)
        row.addWidget(weak_card, 1)
        return self._counters_card

    @staticmethod
    def _counter_column(title: str) -> tuple[QVBoxLayout, QFrame]:
        card = QFrame()
        card.setObjectName("optionCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("predictionEyebrow")
        box.addWidget(label)
        rows = QVBoxLayout()
        rows.setSpacing(6)
        box.addLayout(rows)
        return rows, card

    def _build_synergies(self) -> QFrame:
        self._synergies_card = QFrame()
        self._synergies_card.setObjectName("optionCard")
        box = QVBoxLayout(self._synergies_card)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(9)
        label = QLabel("DUPLAS QUE VENCEM JUNTO")
        label.setObjectName("predictionEyebrow")
        box.addWidget(label)
        self._synergies = QGridLayout()
        self._synergies.setHorizontalSpacing(20)
        self._synergies.setVerticalSpacing(6)
        box.addLayout(self._synergies)
        return self._synergies_card

    # ---------- preenchimento ----------

    def set_icon_resolver(self, resolve) -> None:
        """Entrega o tradutor de id de campeão em caminho de retrato.

        Chega tarde, junto com os retratos: enquanto não chega, os
        confrontos aparecem só com o nome, que já basta para ler.
        """
        self._resolve_icon = resolve

    def set_champions(self, champions) -> None:
        """A lista para o seletor de adversário: pares (nome, alias).

        O nome é o que se lê; o alias é o que o OP.GG entende — são
        diferentes em vários campeões, e Wukong, que lá se chama
        `MonkeyKing`, é o exemplo que quebra quem usar o nome.
        """
        atual = self._opponent.currentData()
        self._opponent.blockSignals(True)
        self._opponent.clear()
        self._opponent.addItem("escolha o adversário…", "")
        for name, alias in champions:
            self._opponent.addItem(name, alias)
        if atual:
            # Recarregar o catálogo não pode desfazer a escolha de quem
            # já estava lendo um confronto.
            index = self._opponent.findData(atual)
            if index >= 0:
                self._opponent.setCurrentIndex(index)
        self._opponent.blockSignals(False)

    @property
    def opponent_name(self) -> str:
        """O adversário escolhido, como o jogador o lê.

        O sinal carrega o alias, que é o que o OP.GG entende; para
        escrever “vs Wukong” na aba do arsenal é preciso o nome, e é
        o combo quem o tem.
        """
        return self._opponent.currentText() if self._opponent.currentData() else ""

    def _on_opponent_chosen(self, _index: int) -> None:
        alias = self._opponent.currentData()
        self._verdict.hide()
        self._tip.hide()
        self._tip_note.hide()
        if not alias or not self._alias or not self._position:
            self._matchup_state.setText("")
            return
        self._matchup_state.setText("consultando…")
        self.matchup_requested.emit(alias, self._position)

    def set_matchup(self, opponent_alias: str, matchup) -> None:
        """Mostra o guia que voltou, se ainda for o pedido na tela.

        Trocar de adversário duas vezes seguidas deixa a primeira
        resposta chegando atrasada; sem esta conferência ela sobrescreve
        a segunda, e a tela passa a falar de um confronto que já não é o
        escolhido.
        """
        if opponent_alias != self._opponent.currentData():
            return
        if matchup is None:
            self._matchup_state.setText("o OP.GG não tem dados deste confronto")
            return

        self._matchup_state.setText("")
        partes = []
        if matchup.lane_advantage:
            partes.append(f"Vantagem na rota: {matchup.lane_advantage}")
        else:
            partes.append("Rota parelha")
        if matchup.solo_kill_advantage:
            partes.append(f"Duelo isolado: {matchup.solo_kill_advantage}")
        if matchup.play_style:
            partes.append(f"Ritmo: {matchup.play_style}")
        self._verdict.setText("   ·   ".join(partes))
        self._tip.setText(matchup.tip)
        self._verdict.show()
        self._tip.show()
        self._tip_note.show()

    def set_analysis(
        self, name, alias, icon_path, position, tier_label, build, status: str = "no_data"
    ) -> None:
        """Mostra a análise do campeão, ou some se não há o que mostrar.

        `build` vindo `None` precisa vir com o estado que levou até ele:
        rota ainda ausente, servidor lento ou dados indisponíveis. A página
        inteira volta ao aviso certo em vez de parecer quebrada.
        """
        if not name or build is None:
            self.set_empty_state("awaiting_champion" if not name else status, force=True)
            return

        # Campeão novo zera o confronto: a dica que estava na tela é do
        # boneco anterior e não vale mais para este.
        if alias != self._alias:
            self._opponent.blockSignals(True)
            self._opponent.setCurrentIndex(0)
            self._opponent.blockSignals(False)
            self._verdict.hide()
            self._tip.hide()
            self._tip_note.hide()
            self._matchup_state.setText("")
        self._alias = alias or ""
        self._position = position or ""

        self._name.setText(name)
        lane = POSITION_NAMES.get((position or "").lower(), "")
        onde = " · ".join(part for part in (lane, tier_label) if part)
        damage = {"AD": "Dano físico", "AP": "Dano mágico"}.get(
            build.damage_type, build.damage_type
        )
        self._where.setText(" · ".join(part for part in (onde, damage) if part))
        tier_key = RANK_LABEL_TO_KEY.get((tier_label or "").casefold(), tier_label)
        crest = rank_pixmap(tier_key, ANALYSIS_RANK)
        self._tier_crest.setPixmap(crest)
        self._tier_crest.setVisible(not crest.isNull())
        self._tier_crest.setToolTip(tier_label or "")
        if icon_path:
            self._portrait.setPixmap(QIcon(icon_path).pixmap(PORTRAIT))
        else:
            self._portrait.setPixmap(QIcon().pixmap(PORTRAIT))

        self._fill_stats(build.stats)
        self._fill_skills(build)
        self._fill_counters(build)
        self._fill_synergies(build)
        # Sem rota não há confronto de rota: no Abismo todo mundo divide
        # a mesma faixa, e o guia do OP.GG não tem o que responder.
        self._matchup_card.setVisible(bool(self._position))

        self._has_analysis = True
        self._empty.hide()
        self._content.show()

    def _fill_stats(self, stats) -> None:
        while self._stats.count():
            item = self._stats.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if stats is None:
            return
        nota = TIERS.get(stats.tier)
        medidas = [
            ("VITÓRIA", f"{stats.win_rate:.0%}"),
            ("KDA", f"{stats.kda:.2f}"),
            ("ESCOLHA", f"{stats.pick_rate:.0%}"),
            ("BANIMENTO", f"{stats.ban_rate:.0%}"),
        ]
        if nota:
            medidas.append(("NOTA", f"{nota} · #{stats.rank}"))
        for label, value in medidas:
            self._stats.addWidget(self._measure(label, value))

    @staticmethod
    def _measure(label: str, value: str) -> QWidget:
        block = QWidget()
        box = QVBoxLayout(block)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        top = QLabel(label)
        top.setObjectName("cardLabel")
        box.addWidget(top, 0, Qt.AlignmentFlag.AlignHCenter)
        bottom = QLabel(value)
        bottom.setObjectName("cardValue")
        box.addWidget(bottom, 0, Qt.AlignmentFlag.AlignHCenter)
        return block

    def _fill_skills(self, build) -> None:
        self._skills.set_order(build.skill_order)
        if build.skill_max:
            self._max_order.setText("  >  ".join(build.skill_max))
        else:
            self._max_order.setText("")
        # Sem ordem nem prioridade o cartão não tem conteúdo nenhum.
        self._skills_card.setVisible(
            bool(build.skill_order) or bool(build.skill_max)
        )

    def _fill_counters(self, build) -> None:
        self._fill_counter_column(self._strong, build.strong_against, "up")
        self._fill_counter_column(self._weak, build.weak_against, "down")
        self._counters_card.setVisible(
            bool(build.strong_against) or bool(build.weak_against)
        )

    def _fill_counter_column(
        self, rows: QVBoxLayout, counters, trend: str
    ) -> None:
        while rows.count():
            item = rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for counter in counters[:COUNTER_LIMIT]:
            rows.addWidget(
                self._champion_rate_row(
                    counter.champion_id,
                    counter.champion,
                    counter.win_rate,
                    counter.games,
                    trend,
                )
            )

    def _champion_rate_row(
        self, champion_id: int, name: str, win_rate: float, games: int, trend: str
    ) -> QWidget:
        """Uma linha de campeão + retrato + taxa, para confronto e dupla.

        `trend` pinta a taxa de verde ou vermelho — "vencer" e "apanhar"
        já dizem isso em palavras no título da coluna, mas a cor é o que
        se lê num piscar de olho, sem precisar voltar ao cabeçalho.
        """
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)

        portrait = QLabel()
        portrait.setObjectName("miniPortrait")
        portrait.setFixedSize(COUNTER_ICON)
        portrait.setScaledContents(True)
        path = self._resolve_icon(champion_id) if self._resolve_icon else None
        icon = QIcon(path) if path else QIcon()
        portrait.setPixmap(icon.pixmap(COUNTER_ICON))
        box.addWidget(portrait)

        label = QLabel(name)
        label.setObjectName("predictionName")
        box.addWidget(label)
        box.addStretch(1)

        rate = QLabel(f"{win_rate:.0%}")
        rate.setObjectName("cardValue")
        rate.setProperty("trend", trend)
        box.addWidget(rate)
        # A amostra fica no balão: sem ela um 60% de doze partidas se
        # lê igual a um de mil, e não é a mesma coisa.
        row.setToolTip(f"{games} partidas medidas")
        return row

    def _fill_synergies(self, build) -> None:
        while self._synergies.count():
            item = self._synergies.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        # Agrupa por rota preservando a ordem em que vieram, que é a do
        # ranking do OP.GG — a primeira de cada rota é a melhor dupla.
        lanes: dict[str, list] = {}
        for synergy in build.synergies:
            lanes.setdefault(synergy.position, []).append(synergy)
        for column, (lane, found) in enumerate(lanes.items()):
            header = QLabel(LANES.get(lane, lane).upper())
            header.setObjectName("cardLabel")
            self._synergies.addWidget(header, 0, column)
            for line, synergy in enumerate(found[:3], start=1):
                # Dupla é sempre a favor — não há coluna "apanha junto" —
                # por isso a taxa aqui nunca pinta de vermelho.
                row = self._champion_rate_row(
                    synergy.champion_id,
                    synergy.champion,
                    synergy.win_rate,
                    synergy.games,
                    "up",
                )
                self._synergies.addWidget(row, line, column)
        self._synergies_card.setVisible(bool(build.synergies))
