"""Identidade do computador, para a licença valer num PC só.

O que se quer é um número que seja o mesmo toda vez neste PC e
diferente no PC do vizinho — nada além disso. Não é identificação de
pessoa: o que sai daqui é um resumo (sha256) de identificadores de
hardware/instalação, e é só o resumo que viaja até o servidor.

Estabilidade é o requisito difícil. Um identificador que muda sozinho
(IP, nome de usuário, placa de rede que some quando o Wi-Fi desliga)
faz a licença "quebrar" sem ninguém ter mexido em nada, e o suporte
vira um inferno. Por isso a fonte principal é o `MachineGuid`, que o
Windows grava na instalação e não muda com troca de hardware, com o
número de série do volume do sistema como segunda pista.

Cada fonte que falha é simplesmente omitida, nunca substituída por um
valor inventado: duas máquinas onde tudo falhou cairiam no mesmo
resumo e uma licença de uma valeria na outra.
"""

from __future__ import annotations

import hashlib
import os
import platform
import uuid

#: Tamanho do resumo em caracteres hex. 32 são 128 bits — de sobra para
#: não colidir e curto o bastante para caber num log sem quebrar linha.
TAMANHO = 32


def _machine_guid() -> str:
    """O identificador que o Windows cria na instalação do sistema."""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        # KEY_WOW64_64KEY porque num Python 32 bits o Windows redireciona
        # a leitura para a árvore Wow6432Node, onde o valor não existe —
        # a impressão digital mudaria só por trocar de interpretador.
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as chave:
            valor, _ = winreg.QueryValueEx(chave, "MachineGuid")
        return str(valor).strip()
    except OSError:
        return ""


def _serie_do_volume() -> str:
    """Número de série do volume onde o Windows está instalado.

    Muda se o disco for formatado, por isso é a segunda pista e não a
    primeira: formatar o C: é raro, mas acontece, e sozinho isso não
    pode invalidar a licença de quem não fez nada errado.
    """
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        raiz = (os.environ.get("SystemDrive") or "C:") + "\\"
        serie = wintypes.DWORD()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(raiz),
            None,
            0,
            ctypes.byref(serie),
            None,
            None,
            None,
            0,
        )
        if not ok:
            return ""
        return f"{serie.value:08X}"
    except Exception:
        return ""


def _fallback() -> str:
    """Última pista, para quando não se está no Windows (testes, CI).

    `getnode()` inventa um número aleatório quando não acha placa de
    rede — e um valor que muda a cada execução daria uma máquina nova a
    cada abertura do app. O bit 41 do valor é justamente a marca de
    "isto foi sorteado"; quando ele está ligado, o valor é descartado.
    """
    partes = [platform.node().strip()]
    no = uuid.getnode()
    if not (no >> 40) & 0x1:
        partes.append(f"{no:012x}")
    return "|".join(p for p in partes if p)


def pistas() -> list[str]:
    """As fontes que responderam, na ordem de confiança. Só para depurar."""
    achadas = []
    for rotulo, valor in (
        ("guid", _machine_guid()),
        ("volume", _serie_do_volume()),
        ("host", _fallback()),
    ):
        if valor:
            achadas.append(f"{rotulo}={valor}")
    return achadas


def impressao() -> str:
    """O resumo do computador. Sempre responde algo, nunca levanta.

    Travar o app na abertura porque uma leitura de registro falhou seria
    trocar um problema pequeno por um total.
    """
    fontes = pistas()
    if not fontes:
        # Nada identificou a máquina. Melhor uma licença que vale em
        # qualquer lugar do que um app que não abre.
        fontes = ["desconhecida"]
    bruto = "\n".join(fontes).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest()[:TAMANHO]


def apelido() -> str:
    """Nome amigável do PC, para o dono reconhecer o slot na lista."""
    nome = platform.node().strip()
    return nome or "computador sem nome"
