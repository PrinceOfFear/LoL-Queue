"""Ponto de entrada do executável.

`lolqueue/__main__.py` usa imports relativos e só roda como pacote —
`py -m lolqueue`. O PyInstaller executa o script solto, como `__main__`
sem pacote nenhum, e ali os imports relativos falham. Este arquivo
existe para entrar pelo pacote, do jeito que ele espera.
"""

from lolqueue.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
