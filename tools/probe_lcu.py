"""Confirma as rotas da LCU contra o cliente real e grava fixtures.

Uso, com o cliente do LoL aberto:
    py tools/probe_lcu.py

Rodar uma segunda vez durante a seleção de campeões para capturar uma
sessão de champ select de verdade.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lolqueue.lcu import endpoints  # noqa: E402
from lolqueue.lcu.client import LcuClient, LcuError  # noqa: E402
from lolqueue.lcu.credentials import discover  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

PROBES = {
    "gameflow_phase": endpoints.GAMEFLOW_PHASE,
    "current_summoner": endpoints.CURRENT_SUMMONER,
    "lobby": endpoints.LOBBY,
    "champ_select_session": endpoints.CHAMP_SELECT_SESSION,
    "pickable_champions": endpoints.PICKABLE_CHAMPIONS,
    "bannable_champions": endpoints.BANNABLE_CHAMPIONS,
    "champion_summary": endpoints.CHAMPION_SUMMARY,
}


def main() -> int:
    credentials = discover()
    if credentials is None:
        print("Cliente do LoL não encontrado. Abra o jogo e rode de novo.")
        return 1

    print(f"Conectado em {credentials.base_url}\n")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    client = LcuClient(credentials)

    for name, path in PROBES.items():
        try:
            payload = client.get(path)
        except LcuError as exc:
            print(f"[FALHA] {name:24} {path}\n         {exc}")
            continue
        destination = FIXTURES / f"{name}.json"
        destination.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[  OK ] {name:24} {path}  ->  {destination.name}")

    lobby = FIXTURES / "lobby.json"
    if lobby.exists():
        data = json.loads(lobby.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            print("\nChaves da raiz de /lol-lobby/v2/lobby:")
            for key in sorted(data):
                print(f"  - {key}")
            print("\nProcure a chave que indica se você pode iniciar a fila.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
