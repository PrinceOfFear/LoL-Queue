from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# A lista de vozes mora com quem sintetiza; a config só guarda a
# escolha. Importar de lá evita duas listas que saem de sincronia na
# primeira voz nova.
from .vision.voice import DEFAULT_VOICE as DEFAULT_JUNGLE_VOICE
from .vision.voice import VOICE_LABELS as JUNGLE_VOICE_LABELS
from .vision.voice import VOICES as JUNGLE_VOICES

QUEUES: dict[int, str] = {
    400: "Normal Draft",
    420: "Ranqueada Solo/Duo",
    430: "Normal Blind",
    440: "Ranqueada Flex",
    450: "ARAM",
    490: "Partida Rápida",
    1700: "Arena",
}


#: Rotas como o cliente as nomeia em `assignedPosition`, na ordem em que
#: aparecem no mapa. É esse campo que revela autofill e rota secundária:
#: seja qual for o motivo, ele diz onde o jogador caiu de verdade.
POSITIONS: tuple[str, ...] = ("top", "jungle", "middle", "bottom", "utility")

POSITION_NAMES: dict[str, str] = {
    "top": "Topo",
    "jungle": "Selva",
    "middle": "Meio",
    "bottom": "Atirador",
    "utility": "Suporte",
}


#: Teto do atraso antes de aceitar. A janela que o cliente dá para
#: responder ao "Partida encontrada" dura cerca de 12 segundos, e
#: estourá-la custa a partida — mais a punição de fila por recusa. Oito
#: deixa margem para o cliente demorar a processar o POST.
ACCEPT_DELAY_CEILING = 8.0


#: Faixas de elo que o OP.GG aceita no pedido de build. A chave é o que
#: viaja para a rede — confirmado direto contra o servidor, porque a
#: documentação pública do MCP só dá "all, challenger, grandmaster" como
#: exemplo e não lista o resto — e o valor é o rótulo que aparece na
#: tela, na ordem em que deve aparecer nela.
OPGG_TIERS: dict[str, str] = {
    "all": "Todos os elos",
    "iron": "Ferro",
    "bronze": "Bronze",
    "silver": "Prata",
    "gold": "Ouro",
    "gold_plus": "Ouro+",
    "platinum": "Platina",
    "platinum_plus": "Platina+",
    "emerald": "Esmeralda",
    "emerald_plus": "Esmeralda+",
    "diamond": "Diamante",
    "diamond_plus": "Diamante+",
    "master": "Mestre",
    "master_plus": "Mestre+",
    "grandmaster": "Grão-Mestre",
    "challenger": "Desafiante",
}

#: Diamante+ é o corte onde a amostra ainda é grande e as escolhas já
#: são deliberadas — o padrão de sempre, agora só o ponto de partida.
DEFAULT_OPGG_TIER = "diamond_plus"


def position_name(position: str) -> str:
    return POSITION_NAMES.get(position.casefold(), position)


def queue_name(queue_id: int) -> str:
    """Nome da fila para o registro. Id desconhecido aparece como número."""
    return QUEUES.get(queue_id, f"fila {queue_id}")


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LoLQueue" / "config.json"


def log_dir() -> Path:
    """Onde fica o registro em arquivo, ao lado da config."""
    return config_path().parent / "registro"


def champion_ids(value) -> list[int]:
    """Filtra uma lista de prioridade, deixando só ids plausíveis.

    Aplicado na leitura e na gravação: um id malformado não casa com
    campeão nenhum, então só ocuparia uma posição da prioridade sem
    nunca ser escolhido. Quem sabe quais ids existem de verdade é o
    catálogo, que poda o resto quando carrega.

    `bool` é subclasse de `int` em Python — daí a checagem explícita,
    senão um `true` no arquivo viraria o campeão de id 1.
    """
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    ]


#: Teto do atraso da intenção de pick. Trinta segundos já passa da
#: metade da seleção; mais que isso não é discrição, é nunca mostrar.
PICK_INTENT_CEILING = 30.0


@dataclass
class Config:
    auto_accept: bool = True
    auto_queue: bool = False
    auto_pick: bool = False
    auto_ban: bool = False
    auto_spells: bool = False
    auto_runes: bool = False
    # Só faz sentido junto com `auto_runes`: acrescenta à aplicação
    # automática um leque de builds de elos diferentes para o usuário
    # trocar na tela, sem mudar o que é aplicado sozinho.
    auto_runes_options: bool = False
    auto_items: bool = False
    # Mostra no cliente do LoL, antes da sua vez, o campeão que a lista
    # vai travar — o mesmo retrato que aparece sobre o seu quadro quando
    # você clica num campeão durante a fase de banimento. Só declara a
    # intenção: quem trava continua sendo a vez de escolher.
    show_pick_intent: bool = True
    # Quanto esperar, contado de quando a seleção abre, antes de mostrar
    # o retrato. Sem espera a intenção sai enquanto os outros nove ainda
    # carregam a tela: o time vê o pick antes de o jogador ver qualquer
    # coisa, e sobra tempo para alguém pegar o campeão de birra.
    pick_intent_delay: float = 8.0
    # Desliga, durante a seleção, o chat dos aliados, o chat de todos e
    # os emotes dos inimigos. Reversível: o que havia antes volta assim
    # que a partida termina.
    mute_before_game: bool = True
    # Vigia o minimapa durante a partida e fala em voz alta quando o
    # jungler inimigo aparece. Nasce ligado porque é o aviso que o
    # jogador não consegue se dar sozinho: quem está olhando a rota
    # não está olhando o canto da tela.
    jungle_callouts: bool = True
    jungle_voice: str = DEFAULT_JUNGLE_VOICE
    queue_id: int = 420
    queue_only_as_host: bool = True
    opgg_tier: str = DEFAULT_OPGG_TIER
    pick_priority: list[int] = field(default_factory=list)
    ban_priority: list[int] = field(default_factory=list)
    pick_priority_by_position: dict[str, list[int]] = field(default_factory=dict)
    # Faixas de atraso, sorteadas a cada ação. O mínimo é o que dá ao
    # usuário tempo de intervir; a largura só evita que toda partida
    # tenha o mesmo compasso.
    lock_delay_min: float = 2.0
    lock_delay_max: float = 6.0
    accept_delay_min: float = 1.0
    accept_delay_max: float = 4.0
    # Quanto esperar depois da partida antes de buscar a próxima. O
    # cliente leva alguns segundos para soltar a partida anterior e
    # recusa a fila até lá; tentar antes disso só rende erro.
    postgame_delay_min: float = 6.0
    postgame_delay_max: float = 10.0

    def __post_init__(self) -> None:
        self.sanitize()

    def sanitize(self) -> None:
        """Descarta ids malformados das listas de prioridade.

        Roda na construção (cobre a leitura do disco) e de novo antes de
        gravar, porque a UI escreve nos campos direto por `setattr`.
        """
        self.pick_priority = champion_ids(self.pick_priority)
        self.ban_priority = champion_ids(self.ban_priority)
        self.pick_priority_by_position = self._clean_positions()
        if self.opgg_tier not in OPGG_TIERS:
            # Editar o arquivo à mão e errar o elo não pode travar o
            # app nem quebrar o pedido ao OP.GG em silêncio — volta ao
            # padrão, do mesmo jeito que um id de campeão torto é
            # descartado em vez de propagado.
            self.opgg_tier = DEFAULT_OPGG_TIER
        if self.jungle_voice not in JUNGLE_VOICES:
            # Mesma regra do elo: voz que o sintetizador não conhece
            # deixaria o aviso mudo justamente na hora do gank.
            self.jungle_voice = DEFAULT_JUNGLE_VOICE
        self.lock_delay_min, self.lock_delay_max = self._clean_delay(
            self.lock_delay_min, self.lock_delay_max
        )
        self.accept_delay_min, self.accept_delay_max = self._clean_delay(
            self.accept_delay_min, self.accept_delay_max, ceiling=ACCEPT_DELAY_CEILING
        )
        self.postgame_delay_min, self.postgame_delay_max = self._clean_delay(
            self.postgame_delay_min, self.postgame_delay_max
        )
        self.pick_intent_delay = self._clean_seconds(
            self.pick_intent_delay, PICK_INTENT_CEILING
        )


    @staticmethod
    def _clean_seconds(value: float, ceiling: float) -> float:
        """Endireita um atraso solto, do mesmo jeito que uma faixa.

        Vale a mesma regra: o arquivo é editável à mão, e número torto
        vira o limite mais próximo em vez de derrubar o app.
        """
        try:
            return min(max(0.0, float(value)), ceiling)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clean_delay(
        low: float, high: float, ceiling: float | None = None
    ) -> tuple[float, float]:
        """Endireita uma faixa de atraso vinda do disco ou da UI.

        Número torto não levanta erro: o arquivo é editável à mão e uma
        faixa invertida não pode impedir o app de subir. Fora da faixa
        vira o limite mais próximo, e máximo abaixo do mínimo colapsa
        num atraso fixo.
        """
        try:
            low = max(0.0, float(low))
            high = max(0.0, float(high))
        except (TypeError, ValueError):
            return (0.0, 0.0)
        if ceiling is not None:
            low = min(low, ceiling)
            high = min(high, ceiling)
        return (low, max(low, high))

    def _clean_positions(self) -> dict[str, list[int]]:
        """Só rotas que o cliente conhece, e só com lista de verdade.

        Lista vazia é descartada em vez de guardada: guardá-la faria
        `pick_list` decidir entre vazio e ausente duas vezes, e as duas
        querem dizer a mesma coisa — usar a lista geral.
        """
        source = self.pick_priority_by_position
        if not isinstance(source, dict):
            return {}
        cleaned: dict[str, list[int]] = {}
        for position, value in source.items():
            if not isinstance(position, str):
                continue
            key = position.casefold()
            if key not in POSITIONS:
                continue
            ids = champion_ids(value)
            if ids:
                cleaned[key] = ids
        return cleaned

    def pick_list(self, position: str | None) -> list[int]:
        """Prioridade de escolha para a rota que o cliente atribuiu.

        Cai na lista geral quando a rota não tem lista própria. Isso
        cobre de uma vez o modo cego (que não atribui rota), o autofill
        numa rota que o usuário não configurou e quem prefere uma lista
        só para tudo.
        """
        if position:
            specific = self.pick_priority_by_position.get(position.casefold())
            if specific:
                return specific
        return self.pick_priority

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Lê a config do disco. Ausente ou corrompida cai nos padrões."""
        target = path or config_path()
        try:
            # utf-8-sig aceita com e sem BOM: o Notepad do Windows grava
            # com, e um BOM inesperado descartaria tudo em silêncio.
            raw = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        """Grava a config no disco, inteira ou não grava.

        Escrever por cima é o jeito de perder tudo: disco cheio ou queda
        de energia no meio deixam um JSON pela metade, e `load` engole a
        falha e volta aos padrões — o usuário reabre o app com listas de
        pick, bans e atrasos zerados, sem nunca saber por quê. Gravando
        num temporário ao lado e renomeando por cima, o que vale é ou a
        config nova ou a antiga, nunca um meio-termo ilegível: no
        Windows como no Linux, `replace` é atômico dentro do mesmo
        volume, e o temporário nasce na mesma pasta justamente para
        garantir isso.
        """
        self.sanitize()
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".part")
        try:
            temp.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp.replace(target)
        except OSError:
            # O pedaço gravado não serve para nada e não vai virar lixo
            # permanente ao lado da config.
            temp.unlink(missing_ok=True)
            raise
