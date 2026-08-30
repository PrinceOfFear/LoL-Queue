"""O que o app guarda no disco sobre a licença.

Fica ao lado da config, em `%APPDATA%\\LoLQueue\\licenca.json`, e não
dentro da config: apagar a config para resolver um problema de app é
uma coisa que a pessoa faz sozinha o tempo todo, e isso não pode
custar a licença dela.

Nada aqui é secreto — o bilhete é assinado, então adiantaria zero
editar este arquivo à mão. O único campo que serve de defesa é o
`visto_em`, e ele defende contra uma coisa só: atrasar o relógio do
Windows para esticar a validade sem pagar.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

#: Quanto o relógio pode andar para trás sem levantar suspeita, em
#: segundos. Fuso horário mal configurado e volta do horário de verão
#: cabem em um dia; uma semana de "desconto" não cabe.
TOLERANCIA_RELOGIO = 24 * 3600


def caminho() -> Path:
    """Mesmo endereço da config, mesmo redirecionamento por APPDATA."""
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LoLQueue" / "licenca.json"


@dataclass
class Estado:
    """O bilhete atual e o pouco de história que importa.

    `chave` fica guardada junto com o bilhete porque é ela que renova:
    sem ela, quem ficou um mês sem abrir o app teria que ir procurar o
    e-mail da compra em vez de simplesmente abrir e continuar.
    """

    bilhete: str = ""
    chave: str = ""
    validado_em: float = 0.0
    visto_em: float = 0.0
    mensagem: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "Estado":
        alvo = path or caminho()
        try:
            bruto = json.loads(alvo.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(bruto, dict):
            return cls()
        conhecidos = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in bruto.items() if k in conhecidos})

    def save(self, path: Path | None = None) -> None:
        """Grava inteiro ou não grava, pelo mesmo motivo da config.

        Um JSON pela metade aqui seria lido como "sem licença" e mandaria
        um cliente pagante para a tela de ativação sem motivo.
        """
        alvo = path or caminho()
        alvo.parent.mkdir(parents=True, exist_ok=True)
        temp = alvo.with_name(alvo.name + ".part")
        try:
            temp.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp.replace(alvo)
        except OSError:
            temp.unlink(missing_ok=True)
            raise

    def marcar_relogio(self, agora: float | None = None) -> bool:
        """Anota a hora atual e diz se o relógio andou para trás demais.

        Devolve True quando está tudo bem. False significa "não dá para
        confiar no relógio desta máquina agora" — quem chama exige uma
        confirmação online em vez de aceitar a validade offline.
        """
        momento = time.time() if agora is None else agora
        suspeito = self.visto_em > 0 and momento < self.visto_em - TOLERANCIA_RELOGIO
        # O maior horário já visto nunca diminui: se diminuísse, bastaria
        # atrasar o relógio uma vez para zerar a suspeita.
        self.visto_em = max(self.visto_em, momento)
        return not suspeito

    def limpar(self) -> None:
        self.bilhete = ""
        self.chave = ""
        self.validado_em = 0.0
