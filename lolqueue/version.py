"""Versao do aplicativo disponivel tambem no executavel standalone."""

# pyproject.toml e este modulo devem andar juntos. O arquivo TOML nao viaja
# com o Nuitka, por isso o atualizador nao pode depender dele em producao.
VERSION = "0.2.0"
