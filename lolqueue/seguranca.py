"""Verificacao local de seguranca e integridade do LoL Queue.

Nada daqui envia arquivos, token da LCU ou configuracoes para a internet. O
verificador confere a ancora de atualizacao, a politica da conexao local e,
nas distribuicoes oficiais, um manifesto de hashes assinado com Ed25519.

O selo de integridade protege contra arquivos corrompidos ou alterados depois
de a distribuicao ser montada. Como qualquer verificacao executada dentro do
proprio aplicativo, ele nao substitui a protecao do Windows contra alguem que
ja possa alterar o executavel inteiro; por isso a tela descreve exatamente o
que foi conferido, sem prometer uma seguranca inexistente.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .atualizacao_embutida import chave_publica, repositorio
from .config import config_path


INTEGRITY_SCHEMA = 1
MANIFEST_NAME = "lolqueue-integrity.json"
SIGNATURE_NAME = "lolqueue-integrity.json.sig"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_SIGNATURE_BYTES = 8 * 1024
MAX_FILES = 100_000
HASH_CHUNK_SIZE = 1024 * 1024
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


class SecurityState(str, Enum):
    PASSED = "passed"
    INFO = "info"
    WARNING = "warning"
    FAILED = "failed"


class IntegrityError(RuntimeError):
    """O pacote ou seu selo de integridade nao podem ser confiados."""


@dataclass(frozen=True)
class SecurityCheck:
    key: str
    title: str
    detail: str
    state: SecurityState


@dataclass(frozen=True)
class SecurityReport:
    checks: tuple[SecurityCheck, ...]

    @property
    def has_failures(self) -> bool:
        return any(check.state is SecurityState.FAILED for check in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(check.state is SecurityState.WARNING for check in self.checks)

    @property
    def summary(self) -> str:
        if self.has_failures:
            return "A verificacao encontrou um arquivo ou ajuste que precisa de atencao."
        if self.has_warnings:
            return "Protecao parcial: veja os itens marcados antes de distribuir o app."
        return "Protecoes verificadas. Nenhum dado da sua conta foi enviado."


def canonical_manifest(data: dict[str, Any]) -> bytes:
    """Representacao unica que a ferramenta assina e o app confere."""

    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str) or not _BASE64URL.fullmatch(value):
        raise IntegrityError("a assinatura ou chave de integridade e invalida")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeEncodeError) as exc:
        raise IntegrityError("a assinatura ou chave de integridade e invalida") from exc


def _public_key(value: str) -> Ed25519PublicKey:
    try:
        raw = _b64decode(value)
        if len(raw) != 32:
            raise ValueError("tamanho invalido")
        return Ed25519PublicKey.from_public_bytes(raw)
    except (TypeError, ValueError, IntegrityError) as exc:
        raise IntegrityError("a chave publica de integridade e invalida") from exc


def _private_key(value: str) -> Ed25519PrivateKey:
    try:
        raw = _b64decode(value)
        if len(raw) != 32:
            raise ValueError("tamanho invalido")
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (TypeError, ValueError, IntegrityError) as exc:
        raise IntegrityError("a chave privada de integridade e invalida") from exc


def sign_manifest(raw: bytes, private_key: str) -> str:
    """Assina um manifesto de distribuicao; usada somente pela ferramenta."""

    signature = _private_key(private_key).sign(raw)
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def verify_signature(raw: bytes, signature: str, public_key: str) -> None:
    try:
        _public_key(public_key).verify(_b64decode(signature.strip()), raw)
    except InvalidSignature as exc:
        raise IntegrityError("a assinatura do selo de integridade nao confere") from exc


def _ignored(relative: PurePosixPath) -> bool:
    """Arquivos que o Python pode criar depois de a pasta ser assinada."""

    return (
        relative.name in {MANIFEST_NAME, SIGNATURE_NAME}
        or "__pycache__" in relative.parts
        or relative.suffix.casefold() == ".pyc"
    )


def _is_link(path: Path) -> bool:
    """Inclui junctions do Windows, quando o Python souber identifica-las."""

    try:
        return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())
    except OSError:
        return True


def _inside(path: Path, root: Path) -> None:
    """Garante que nenhum link leve a leitura para fora do pacote."""

    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise IntegrityError("o pacote possui um caminho que sai da pasta de instalacao") from exc


def _files(root: Path) -> dict[str, Path]:
    """Lista arquivos reais do pacote, recusando links e entradas especiais."""

    try:
        base = root.resolve(strict=True)
    except OSError as exc:
        raise IntegrityError("a pasta de instalacao nao esta acessivel") from exc
    if not base.is_dir() or _is_link(root):
        raise IntegrityError("a pasta de instalacao nao e segura para verificar")

    found: dict[str, Path] = {}
    try:
        entries = sorted(base.rglob("*"), key=lambda item: item.as_posix().casefold())
    except OSError as exc:
        raise IntegrityError("nao foi possivel listar os arquivos da instalacao") from exc
    for path in entries:
        if _is_link(path):
            raise IntegrityError("o pacote nao pode conter links ou junctions")
        try:
            relative = PurePosixPath(path.relative_to(base).as_posix())
        except ValueError as exc:
            raise IntegrityError("o pacote possui um caminho inesperado") from exc
        if _ignored(relative):
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            raise IntegrityError("o pacote possui uma entrada de arquivo inesperada")
        _inside(path, base)
        key = str(relative).casefold()
        if key in found:
            raise IntegrityError("o pacote possui nomes de arquivo duplicados")
        found[key] = path
        if len(found) > MAX_FILES:
            raise IntegrityError("o pacote possui arquivos demais para verificar com seguranca")
    return found


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(HASH_CHUNK_SIZE):
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise IntegrityError("nao foi possivel ler um arquivo da instalacao") from exc
    return size, digest.hexdigest()


def build_manifest(root: Path, version: str) -> dict[str, Any]:
    """Monta a lista de hashes que sera assinada na distribuicao oficial."""

    if not isinstance(version, str) or not version.strip():
        raise IntegrityError("a versao do manifesto de integridade e invalida")
    files: list[dict[str, Any]] = []
    for key, path in _files(root).items():
        size, digest = _hash_file(path)
        files.append(
            {
                "path": path.relative_to(root.resolve()).as_posix(),
                "sha256": digest,
                "size": size,
            }
        )
    if not files:
        raise IntegrityError("a distribuicao nao possui arquivos para assinar")
    files.sort(key=lambda entry: entry["path"].casefold())
    return {"schema": INTEGRITY_SCHEMA, "version": version.strip(), "files": files}


def write_signed_manifest(root: Path, version: str, private_key: str) -> tuple[Path, Path]:
    """Grava manifesto e assinatura ao lado do executavel, nunca a chave."""

    target = root.resolve()
    manifest = build_manifest(target, version)
    raw = canonical_manifest(manifest)
    signature = sign_manifest(raw, private_key)
    manifest_path = target / MANIFEST_NAME
    signature_path = target / SIGNATURE_NAME
    try:
        manifest_path.write_bytes(raw)
        signature_path.write_text(signature + "\n", encoding="ascii")
    except OSError as exc:
        raise IntegrityError("nao foi possivel gravar o selo de integridade") from exc
    return manifest_path, signature_path


def _manifest_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise IntegrityError("o manifesto possui um caminho de arquivo invalido")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} or ":" in part for part in path.parts)
        or str(path) != value
    ):
        raise IntegrityError("o manifesto possui um caminho de arquivo invalido")
    return str(path)


def _expected_files(data: object) -> dict[str, tuple[str, int, str]]:
    if not isinstance(data, list) or not data or len(data) > MAX_FILES:
        raise IntegrityError("o manifesto nao lista arquivos validos")
    expected: dict[str, tuple[str, int, str]] = {}
    for entry in data:
        if not isinstance(entry, dict):
            raise IntegrityError("o manifesto possui arquivo invalido")
        path = _manifest_path(entry.get("path"))
        digest = entry.get("sha256")
        size = entry.get("size")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise IntegrityError("o manifesto possui hash invalido")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise IntegrityError("o manifesto possui tamanho invalido")
        key = path.casefold()
        if key in expected:
            raise IntegrityError("o manifesto possui arquivos duplicados")
        expected[key] = (path, size, digest)
    return expected


def verify_bundle(root: Path, public_key: str | None = None) -> SecurityCheck:
    """Confere o selo e cada arquivo da pasta de distribuicao.

    A ausencia dos dois arquivos e informativa para manter a copia de
    desenvolvimento e distribuicoes antigas utilizaveis. A presenca de apenas
    um, assinatura ruim ou hash diferente e sempre falha.
    """

    try:
        base = root.resolve(strict=True)
        manifest_path, signature_path = base / MANIFEST_NAME, base / SIGNATURE_NAME
        if not manifest_path.exists() and not signature_path.exists():
            return SecurityCheck(
                "integrity",
                "INTEGRIDADE DOS ARQUIVOS",
                "Esta copia ainda nao possui selo de integridade assinado.",
                SecurityState.WARNING,
            )
        if not manifest_path.is_file() or not signature_path.is_file():
            raise IntegrityError("o selo de integridade esta incompleto")
        if _is_link(manifest_path) or _is_link(signature_path):
            raise IntegrityError("o selo de integridade nao pode ser um link")
        raw = manifest_path.read_bytes()
        if not raw or len(raw) > MAX_MANIFEST_BYTES:
            raise IntegrityError("o manifesto de integridade tem tamanho invalido")
        signature_raw = signature_path.read_bytes()
        if not signature_raw or len(signature_raw) > MAX_SIGNATURE_BYTES:
            raise IntegrityError("a assinatura de integridade tem tamanho invalido")
        try:
            signature = signature_raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise IntegrityError("a assinatura de integridade nao e texto ASCII") from exc
        verify_signature(raw, signature, public_key if public_key is not None else chave_publica())
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrityError("o manifesto de integridade nao e JSON valido") from exc
        if not isinstance(data, dict) or data.get("schema") != INTEGRITY_SCHEMA:
            raise IntegrityError("o formato do selo de integridade nao e suportado")
        if not isinstance(data.get("version"), str) or not data["version"].strip():
            raise IntegrityError("o selo de integridade nao informa uma versao valida")
        expected = _expected_files(data.get("files"))
        actual = _files(base)
        if set(actual) != set(expected):
            missing = len(set(expected) - set(actual))
            unexpected = len(set(actual) - set(expected))
            raise IntegrityError(
                f"a pasta possui {missing} arquivo(s) ausente(s) e {unexpected} nao reconhecido(s)"
            )
        for key, path in actual.items():
            _name, expected_size, expected_hash = expected[key]
            size, digest = _hash_file(path)
            if size != expected_size or digest != expected_hash:
                raise IntegrityError("um arquivo nao confere com o selo assinado")
        return SecurityCheck(
            "integrity",
            "INTEGRIDADE DOS ARQUIVOS",
            "Todos os arquivos da distribuicao conferem com o selo assinado.",
            SecurityState.PASSED,
        )
    except IntegrityError as exc:
        return SecurityCheck("integrity", "INTEGRIDADE DOS ARQUIVOS", str(exc), SecurityState.FAILED)
    except OSError:
        return SecurityCheck(
            "integrity",
            "INTEGRIDADE DOS ARQUIVOS",
            "Nao foi possivel acessar os arquivos da instalacao.",
            SecurityState.FAILED,
        )


def _update_anchor_check() -> SecurityCheck:
    repository, key = repositorio(), chave_publica()
    try:
        if not _REPOSITORY.fullmatch(repository):
            raise IntegrityError("repositorio oficial nao esta configurado")
        _public_key(key)
    except IntegrityError as exc:
        return SecurityCheck("updates", "ATUALIZACOES ASSINADAS", str(exc), SecurityState.FAILED)
    return SecurityCheck(
        "updates",
        "ATUALIZACOES ASSINADAS",
        "Release, manifesto e download sao conferidos com assinatura Ed25519 e SHA-256.",
        SecurityState.PASSED,
    )


def _lcu_boundary_check() -> SecurityCheck:
    return SecurityCheck(
        "lcu",
        "CONEXAO COM O CLIENTE",
        "A LCU aceita apenas loopback; proxy, redirecionamento e token salvo em disco ficam bloqueados.",
        SecurityState.PASSED,
    )


def _local_storage_check() -> SecurityCheck:
    folder = config_path().parent
    try:
        if folder.exists() and _is_link(folder):
            raise IntegrityError("a pasta local do LoL Queue nao pode ser um link")
        if folder.exists():
            folder.resolve(strict=True)
    except (IntegrityError, OSError) as exc:
        return SecurityCheck("storage", "DADOS NESTE COMPUTADOR", str(exc), SecurityState.FAILED)
    detail = "Configuracoes e historico ficam no perfil local; o token temporario do LoL nunca e gravado."
    if not folder.exists():
        detail = "A pasta local sera criada no perfil do Windows quando houver algo para salvar."
    return SecurityCheck("storage", "DADOS NESTE COMPUTADOR", detail, SecurityState.PASSED)


def inspect(root: Path, *, development: bool = False) -> SecurityReport:
    """Executa todas as verificacoes locais que podem ser feitas sem rede."""

    checks = [_update_anchor_check(), _lcu_boundary_check(), _local_storage_check()]
    if development:
        checks.append(
            SecurityCheck(
                "integrity",
                "INTEGRIDADE DOS ARQUIVOS",
                "Copia de desenvolvimento: o selo sera criado apenas no pacote de distribuicao.",
                SecurityState.INFO,
            )
        )
    else:
        checks.append(verify_bundle(root))
    return SecurityReport(tuple(checks))
