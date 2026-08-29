"""Ponto de entrada do executável.

`lolqueue/__main__.py` usa imports relativos e só roda como pacote —
`py -m lolqueue`. O PyInstaller executa o script solto, como `__main__`
sem pacote nenhum, e ali os imports relativos falham. Este arquivo
existe para entrar pelo pacote, do jeito que ele espera.

O `try` em volta do import não é zelo. O atalho abre o app pelo
`pythonw.exe`, que não tem console: numa máquina onde falta uma
dependência o traceback não vai para lugar nenhum e o duplo clique não
produz nada — nem janela, nem erro. A caixa do Windows é a única coisa
que ainda funciona quando o Qt é justamente o que está faltando, e por
isso ela é feita com `ctypes`, que é sempre da biblioteca padrão.
"""

import sys

#: `MB_ICONERROR | MB_SETFOREGROUND`. O segundo importa porque quem
#: clicou no atalho está olhando para o jogo, não para a área de
#: trabalho.
_CAIXA_DE_ERRO = 0x10 | 0x10000


def _reclamar(erro: BaseException) -> None:
    try:
        from lolqueue.ambiente import faltando, queixa

        texto = queixa(faltando())
    except Exception:
        texto = f"O LoL Queue não abriu: {erro}"
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, texto, "LoL Queue", _CAIXA_DE_ERRO)
    except Exception:
        pass
    print(texto, file=sys.stderr)


def main() -> int:
    try:
        from lolqueue.__main__ import main as abrir
    except ImportError as erro:
        _reclamar(erro)
        return 1
    return abrir()


if __name__ == "__main__":
    raise SystemExit(main())
