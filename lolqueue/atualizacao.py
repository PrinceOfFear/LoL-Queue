"""Atualizacao remota segura por GitHub Releases.

O GitHub hospeda os arquivos, mas nao e a autoridade de confianca: cada
release leva um manifesto JSON assinado com Ed25519. Antes de trocar qualquer
arquivo, o app confere a assinatura com a chave publica gravada no build e o
SHA-256 do ZIP. Ha dois pacotes propositalmente distintos: ``standalone``
para o .exe e ``python`` para a instalacao compativel por pythonw.exe.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal
from urllib.parse import urlparse

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .atualizacao_embutida import chave_publica, configurado, repositorio
from .version import VERSION


UPDATE_SCHEMA = 1
MANIFEST_NAME = "lolqueue-update.json"
SIGNATURE_NAME = "lolqueue-update.json.sig"
INSTALL_KINDS = ("standalone", "python")
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 3 * 1024 * 1024 * 1024
# Manifesto e assinatura sao metadados pequenos. Limita-los separadamente
# evita colocar um arquivo arbitrariamente grande na memoria antes mesmo da
# checagem de assinatura.
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_SIGNATURE_BYTES = 8 * 1024
MAX_ARCHIVE_ENTRIES = 50_000
NETWORK_TIMEOUT = 20
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_VERSION = re.compile(
    r"^v?(?P<release>\d+(?:\.\d+){0,3})(?P<pre>-[0-9A-Za-z][0-9A-Za-z.-]*)?(?:\+[0-9A-Za-z.-]+)?$"
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")

InstallKind = Literal["standalone", "python"]


class UpdateError(RuntimeError):
    """Falha apresentavel ao jogador, sem traceback tecnico."""


class UpdateNotConfigured(UpdateError):
    """O build ainda nao recebeu repositorio/chave publica oficiais."""


class UpdateNotAvailable(UpdateError):
    """A instalacao ja esta atualizada ou a release nao a cobre."""


class UpdateIntegrityError(UpdateError):
    """Assinatura, hash, manifesto ou estrutura do pacote nao conferem."""


@dataclass(frozen=True)
class UpdateArtifact:
    kind: InstallKind
    filename: str
    sha256: str
    size: int
    root: str
    url: str

    @property
    def entrypoint(self) -> str:
        return "LoL Queue.exe" if self.kind == "standalone" else "main.py"


@dataclass(frozen=True)
class UpdateOffer:
    current_version: str
    version: str
    notes: str
    artifact: UpdateArtifact


@dataclass(frozen=True)
class Installation:
    kind: InstallKind
    root: Path
    python_executable: Path | None = None

    @property
    def is_development_checkout(self) -> bool:
        """Nunca sobrescreve um clone Git de desenvolvimento."""

        return (self.root / ".git").exists()


@dataclass(frozen=True)
class PreparedUpdate:
    offer: UpdateOffer
    stage_dir: Path
    payload_dir: Path


def current_version() -> str:
    return VERSION


def current_installation() -> Installation:
    """Distingue executable standalone de instalacao Python real."""

    main = sys.modules.get("__main__")
    compiled = bool(getattr(main, "__compiled__", None) or getattr(sys, "frozen", False))
    if compiled:
        return Installation("standalone", Path(sys.executable).resolve().parent)
    return Installation("python", Path(__file__).resolve().parent.parent, Path(sys.executable).resolve())


def updates_configured() -> bool:
    return configurado()


def _b64decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeEncodeError) as exc:
        raise UpdateIntegrityError("a assinatura de atualizacao esta malformada") from exc


def _public_key(value: str) -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(_b64decode(value))
    except (TypeError, ValueError) as exc:
        raise UpdateIntegrityError("a chave publica de atualizacao e invalida") from exc


def _private_key(value: str) -> Ed25519PrivateKey:
    try:
        return Ed25519PrivateKey.from_private_bytes(_b64decode(value))
    except (TypeError, ValueError) as exc:
        raise UpdateIntegrityError("a chave privada de atualizacao e invalida") from exc


def generate_keypair() -> tuple[str, str]:
    """Gera ``(privada, publica)`` Ed25519 em base64url."""

    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return encode(private_raw), encode(public_raw)


def canonical_manifest(data: dict[str, Any]) -> bytes:
    """A representacao unica que a ferramenta assina e o app confere."""

    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(raw: bytes, private_key: str) -> str:
    """Assina bytes exatos do JSON; usada somente pela ferramenta de release."""

    signature = _private_key(private_key).sign(raw)
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def verify_manifest_signature(raw: bytes, signature: str, public_key: str) -> None:
    try:
        _public_key(public_key).verify(_b64decode(signature.strip()), raw)
    except InvalidSignature as exc:
        raise UpdateIntegrityError("a assinatura da atualizacao nao confere") from exc


def _version_key(value: str) -> tuple[tuple[int, ...], int, tuple[str, ...]]:
    """Compara ``X.Y.Z`` sem depender do pacote packaging no usuario."""

    match = _VERSION.fullmatch(value.strip())
    if match is None:
        raise UpdateIntegrityError(f"versao de atualizacao invalida: {value!r}")
    release = tuple(int(part) for part in match.group("release").split("."))
    release += (0,) * (4 - len(release))
    pre = match.group("pre")
    return release, 1 if pre is None else 0, tuple((pre or "").casefold().split("."))


def is_newer(candidate: str, current: str) -> bool:
    return _version_key(candidate) > _version_key(current)


def _safe_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise UpdateIntegrityError(f"{label} da atualizacao e invalido")
    if value in {".", ".."} or Path(value).name != value:
        raise UpdateIntegrityError(f"{label} da atualizacao e invalido")
    return value


def _artifact_from_manifest(kind: InstallKind, data: object, urls: dict[str, str]) -> UpdateArtifact:
    if not isinstance(data, dict):
        raise UpdateIntegrityError(f"o pacote {kind!r} nao esta descrito corretamente")
    filename = _safe_name(data.get("file"), "nome do arquivo")
    if not filename.casefold().endswith(".zip"):
        raise UpdateIntegrityError("a atualizacao precisa ser um arquivo ZIP")
    sha256 = data.get("sha256")
    if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
        raise UpdateIntegrityError("o SHA-256 da atualizacao e invalido")
    size = data.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_ARCHIVE_BYTES:
        raise UpdateIntegrityError("o tamanho da atualizacao e invalido")
    root = _safe_name(data.get("root"), "pasta do pacote")
    url = urls.get(filename)
    if not url:
        raise UpdateIntegrityError(f"a release nao contem o arquivo assinado {filename!r}")
    return UpdateArtifact(kind, filename, sha256.casefold(), size, root, url)


def _manifest_from_bytes(
    raw: bytes, signature: str, public_key: str, kind: InstallKind, urls: dict[str, str]
) -> tuple[str, str, UpdateArtifact]:
    verify_manifest_signature(raw, signature, public_key)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateIntegrityError("o manifesto de atualizacao nao e JSON valido") from exc
    if not isinstance(data, dict) or data.get("schema") != UPDATE_SCHEMA:
        raise UpdateIntegrityError("o formato do manifesto de atualizacao nao e suportado")
    version = data.get("version")
    if not isinstance(version, str):
        raise UpdateIntegrityError("o manifesto nao informa uma versao valida")
    _version_key(version)
    notes = data.get("notes", "")
    if not isinstance(notes, str):
        raise UpdateIntegrityError("as notas da atualizacao sao invalidas")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        raise UpdateIntegrityError("o manifesto nao lista os pacotes de instalacao")
    return version, notes, _artifact_from_manifest(kind, artifacts.get(kind), urls)


def _https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise UpdateIntegrityError("a atualizacao nao usa uma conexao HTTPS segura")


class GithubReleaseClient:
    """Consulta e baixa somente assets confirmados do GitHub Releases."""

    def __init__(
        self,
        repository: str | None = None,
        public_key: str | None = None,
        *,
        version: str | None = None,
        get: Callable[..., Any] | None = None,
    ) -> None:
        self.repository = (repository if repository is not None else repositorio()).strip()
        self.public_key = (public_key if public_key is not None else chave_publica()).strip()
        self.version = version or current_version()
        self._get = get or requests.get

    @property
    def configured(self) -> bool:
        return bool(_REPOSITORY.fullmatch(self.repository) and self.public_key)

    def _request(self, url: str, *, stream: bool = False):
        _https(url)
        try:
            response = self._get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"LoL-Queue/{self.version}",
                },
                timeout=NETWORK_TIMEOUT,
                stream=stream,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise UpdateError("nao foi possivel consultar a atualizacao agora") from exc
        except AttributeError as exc:
            raise UpdateError("a resposta do servidor de atualizacao e invalida") from exc
        _https(getattr(response, "url", url) or url)
        return response

    def _latest_release(self) -> tuple[dict[str, Any], dict[str, str]]:
        if not self.configured:
            raise UpdateNotConfigured(
                "Atualizacao remota ainda nao foi configurada nesta versao do LoL Queue."
            )
        response = self._request(
            f"https://api.github.com/repos/{self.repository}/releases/latest"
        )
        try:
            release = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise UpdateError("o GitHub devolveu uma release invalida") from exc
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            raise UpdateError("nao ha uma release publica estavel para atualizar")
        listed = release.get("assets")
        if not isinstance(listed, list):
            raise UpdateIntegrityError("a release nao lista os arquivos de atualizacao")
        urls: dict[str, str] = {}
        for asset in listed:
            if not isinstance(asset, dict):
                continue
            name, url = asset.get("name"), asset.get("browser_download_url")
            if isinstance(name, str) and isinstance(url, str) and name not in urls:
                urls[name] = url
        return release, urls

    def _asset_bytes(self, name: str, url: str, *, maximum: int) -> bytes:
        # Usa streaming tambem para os metadados. Conferir `len(content)`
        # depois de o requests carregar tudo ainda deixaria uma release
        # malformada ocupar memoria sem limite antes da recusa.
        response = self._request(url, stream=True)
        announced = getattr(response, "headers", {}).get("Content-Length")
        if announced:
            try:
                if int(announced) > maximum:
                    raise UpdateIntegrityError(f"o asset {name!r} excede o limite seguro")
            except ValueError as exc:
                raise UpdateIntegrityError(f"o tamanho do asset {name!r} e invalido") from exc
        chunks: list[bytes] = []
        total = 0
        try:
            iterator = response.iter_content(chunk_size=64 * 1024)
        except AttributeError as exc:
            raise UpdateIntegrityError(f"o asset {name!r} nao trouxe bytes validos") from exc
        for chunk in iterator:
            if not chunk:
                continue
            if not isinstance(chunk, bytes):
                raise UpdateIntegrityError(f"o asset {name!r} nao trouxe bytes validos")
            total += len(chunk)
            if total > maximum:
                raise UpdateIntegrityError(f"o asset {name!r} excede o limite seguro")
            chunks.append(chunk)
        return b"".join(chunks)

    def check(self, kind: InstallKind) -> UpdateOffer:
        if kind not in INSTALL_KINDS:
            raise UpdateError("tipo de instalacao desconhecido")
        _release, urls = self._latest_release()
        manifest_url, signature_url = urls.get(MANIFEST_NAME), urls.get(SIGNATURE_NAME)
        if not manifest_url or not signature_url:
            raise UpdateIntegrityError(
                "a release oficial nao tem o manifesto assinado de atualizacao"
            )
        raw = self._asset_bytes(MANIFEST_NAME, manifest_url, maximum=MAX_MANIFEST_BYTES)
        try:
            signature = self._asset_bytes(
                SIGNATURE_NAME, signature_url, maximum=MAX_SIGNATURE_BYTES
            ).decode("ascii")
        except UnicodeDecodeError as exc:
            raise UpdateIntegrityError("a assinatura da atualizacao nao e texto ASCII") from exc
        version, notes, artifact = _manifest_from_bytes(
            raw, signature, self.public_key, kind, urls
        )
        if not is_newer(version, self.version):
            raise UpdateNotAvailable("Voce ja esta usando a versao mais recente.")
        return UpdateOffer(self.version, version, notes, artifact)

    def download(
        self,
        offer: UpdateOffer,
        directory: Path | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Baixa o asset conferido para uma pasta temporaria privada."""

        folder = directory or update_cache_dir()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"download-{uuid.uuid4().hex}.zip"
        partial = target.with_suffix(".part")
        total = 0
        digest = hashlib.sha256()
        try:
            response = self._request(offer.artifact.url, stream=True)
            expected_header = getattr(response, "headers", {}).get("Content-Length")
            if expected_header:
                try:
                    if int(expected_header) != offer.artifact.size:
                        raise UpdateIntegrityError(
                            "o tamanho anunciado pelo servidor nao confere com a release assinada"
                        )
                except ValueError as exc:
                    raise UpdateIntegrityError("o tamanho anunciado pelo servidor e invalido") from exc
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    if not isinstance(chunk, bytes):
                        raise UpdateIntegrityError("o download trouxe dados invalidos")
                    total += len(chunk)
                    if total > offer.artifact.size or total > MAX_ARCHIVE_BYTES:
                        raise UpdateIntegrityError("o download excedeu o tamanho assinado")
                    output.write(chunk)
                    digest.update(chunk)
                    if on_progress is not None:
                        on_progress(total, offer.artifact.size)
            if total != offer.artifact.size:
                raise UpdateIntegrityError("o download terminou com tamanho diferente do assinado")
            if digest.hexdigest().casefold() != offer.artifact.sha256:
                raise UpdateIntegrityError("o SHA-256 do download nao confere; nada foi instalado")
            partial.replace(target)
            return target
        except Exception:
            partial.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise


def update_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "LoLQueue" / "updates"


def _safe_member(info: zipfile.ZipInfo, expected_root: str) -> PurePosixPath:
    # O ZIP canônico usa `/`, mas `Compress-Archive` do próprio Windows grava
    # `\\` nos dois pacotes oficiais. Normalizamos *antes* de validar, para
    # que `LoL Queue\\..\\fora.txt` continue sendo recusado e que a mesma
    # representação seja usada para detectar colisões. Também recusamos ADS
    # (`:`) e NUL.
    raw = info.filename
    if not raw or "\x00" in raw:
        raise UpdateIntegrityError("o ZIP possui um caminho inseguro")
    path = PurePosixPath(raw.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise UpdateIntegrityError("o ZIP possui um caminho inseguro")
    if any(":" in part for part in path.parts):
        raise UpdateIntegrityError("o ZIP possui um caminho inseguro")
    if path.parts[0] != expected_root:
        raise UpdateIntegrityError("o ZIP nao possui a estrutura assinada da atualizacao")
    # Recusar symlink deixa explicita a protecao, mesmo que zipfile hoje nao
    # o recrie automaticamente no Windows.
    file_type = (info.external_attr >> 16) & 0o170000
    if file_type == 0o120000:
        raise UpdateIntegrityError("o ZIP nao pode conter links simbolicos")
    return path


def prepare_update(offer: UpdateOffer, archive: Path, directory: Path | None = None) -> PreparedUpdate:
    """Confere a estrutura do ZIP e o extrai em staging antes de fechar."""

    cache = directory or update_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    stage = cache / f"prepared-{uuid.uuid4().hex}"
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if not infos or len(infos) > MAX_ARCHIVE_ENTRIES:
                raise UpdateIntegrityError("o ZIP possui quantidade invalida de arquivos")
            total = sum(info.file_size for info in infos)
            if total <= 0 or total > MAX_UNCOMPRESSED_BYTES:
                raise UpdateIntegrityError("o ZIP possui tamanho descompactado invalido")
            seen: set[str] = set()
            for info in infos:
                path = _safe_member(info, offer.artifact.root)
                # O destino e Windows, onde nomes nao distinguem maiusculas.
                # Recusar colisao evita que uma entrada posterior sobrescreva
                # outra durante a extracao.
                key = str(path).casefold()
                if key in seen:
                    raise UpdateIntegrityError("o ZIP possui arquivos duplicados")
                seen.add(key)
            stage.mkdir(parents=True, exist_ok=False)
            for info in infos:
                bundle.extract(info, stage)
        payload = stage / offer.artifact.root
        if not payload.is_dir() or not (payload / offer.artifact.entrypoint).is_file():
            raise UpdateIntegrityError("o ZIP nao contem os arquivos necessarios para abrir o LoL Queue")
        return PreparedUpdate(offer, stage, payload)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _apply_script(*, installation: Installation, prepared: PreparedUpdate, pid: int) -> str:
    """PowerShell que troca somente uma instalacao ja identificada.

    A troca e feita por um processo separado porque o Windows nao permite
    substituir o executavel que esta aberto. A versao antiga vira backup ate
    que a nova esteja no lugar e, no modo Python, ate as dependencias exatas
    da nova versao responderem ao pip.
    """

    root = installation.root.resolve()
    python = installation.python_executable or Path(".")
    return f"""param()
$ErrorActionPreference = 'Stop'
$processId = {pid}
$installRoot = {_ps_quote(root)}
$payloadRoot = {_ps_quote(prepared.payload_dir.resolve())}
$stageRoot = {_ps_quote(prepared.stage_dir.resolve())}
$mode = {_ps_quote(installation.kind)}
$pythonExecutable = {_ps_quote(python)}

function Show-UpdateFailure([string]$message) {{
    try {{
        Add-Type -AssemblyName PresentationFramework -ErrorAction Stop
        [System.Windows.MessageBox]::Show($message, 'LoL Queue - atualizacao', 'OK', 'Error') | Out-Null
    }} catch {{
        try {{ (New-Object -ComObject WScript.Shell).Popup($message, 0, 'LoL Queue - atualizacao', 16) | Out-Null }} catch {{ }}
    }}
}}

function Remove-OnlyInside([string]$target, [string]$allowedRoot) {{
    if (-not (Test-Path -LiteralPath $target)) {{ return }}
    $allowed = [System.IO.Path]::GetFullPath($allowedRoot).TrimEnd([char[]]@('\\', '/'))
    $actual = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $target).Path)
    if (-not $actual.StartsWith($allowed + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {{
        throw "Recusei remover fora da area de atualizacao: $actual"
    }}
    Remove-Item -LiteralPath $actual -Recurse -Force
}}

try {{
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ((Get-Process -Id $processId -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline) {{
        Start-Sleep -Milliseconds 250
    }}
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {{
        throw 'O LoL Queue nao fechou a tempo. Feche-o completamente e tente atualizar de novo.'
    }}

    $root = [System.IO.Path]::GetFullPath($installRoot)
    $payload = [System.IO.Path]::GetFullPath($payloadRoot)
    $stage = [System.IO.Path]::GetFullPath($stageRoot)
    $parent = [System.IO.Path]::GetDirectoryName($root)
    if (-not $parent -or $root.TrimEnd([char[]]@('\\', '/')) -eq [System.IO.Path]::GetPathRoot($root).TrimEnd([char[]]@('\\', '/'))) {{
        throw 'A pasta de instalacao informada e insegura para atualizar.'
    }}
    if (-not $payload.StartsWith($stage.TrimEnd([char[]]@('\\', '/')) + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {{
        throw 'A preparacao da atualizacao esta fora da area segura.'
    }}
    if (-not (Test-Path -LiteralPath $root) -or -not (Test-Path -LiteralPath $payload)) {{
        throw 'A instalacao atual ou o pacote preparado nao foi encontrado.'
    }}
    if ($mode -eq 'standalone' -and -not (Test-Path -LiteralPath (Join-Path $payload 'LoL Queue.exe'))) {{
        throw 'O pacote standalone nao contem LoL Queue.exe.'
    }}
    if ($mode -eq 'python' -and -not (Test-Path -LiteralPath (Join-Path $payload 'main.py'))) {{
        throw 'O pacote compativel nao contem main.py.'
    }}

    $backup = Join-Path $parent ('.' + [System.IO.Path]::GetFileName($root) + '.backup-' + [Guid]::NewGuid().ToString('N'))
    Move-Item -LiteralPath $root -Destination $backup
    $moved = $false
    try {{
        Move-Item -LiteralPath $payload -Destination $root
        $moved = $true
        if ($mode -eq 'python') {{
            $pythonDir = [System.IO.Path]::GetDirectoryName($pythonExecutable)
            $pythonConsole = Join-Path $pythonDir 'python.exe'
            if (-not (Test-Path -LiteralPath $pythonConsole)) {{ $pythonConsole = $pythonExecutable }}
            if (-not (Test-Path -LiteralPath $pythonConsole)) {{ throw 'O Python desta instalacao nao foi encontrado.' }}
            Set-Location -LiteralPath $root
            $requirements = @(& $pythonConsole -c "from lolqueue.ambiente import pacotes_instalacao; print('\\n'.join(pacotes_instalacao()))") | ForEach-Object {{ $_.Trim() }} | Where-Object {{ $_ }}
            if ($requirements.Count -gt 0) {{
                & $pythonConsole -m pip install --disable-pip-version-check --upgrade @requirements
                if ($LASTEXITCODE -ne 0) {{ throw 'Nao consegui atualizar as bibliotecas exigidas pela versao nova.' }}
            }}
            $launcher = Join-Path $pythonDir 'pythonw.exe'
            if (-not (Test-Path -LiteralPath $launcher)) {{ $launcher = $pythonConsole }}
            $mainArgument = '"' + (Join-Path $root 'main.py') + '"'
            $newProcess = Start-Process -FilePath $launcher -ArgumentList $mainArgument -WorkingDirectory $root -PassThru
        }} else {{
            $newProcess = Start-Process -FilePath (Join-Path $root 'LoL Queue.exe') -WorkingDirectory $root -PassThru
        }}
        Start-Sleep -Milliseconds 1200
        if ($newProcess.HasExited) {{ throw 'A versao nova fechou logo ao abrir; a versao anterior sera restaurada.' }}
    }} catch {{
        if ($moved -and (Test-Path -LiteralPath $root)) {{ Remove-Item -LiteralPath $root -Recurse -Force }}
        if (Test-Path -LiteralPath $backup) {{ Move-Item -LiteralPath $backup -Destination $root }}
        throw
    }}
    if (Test-Path -LiteralPath $backup) {{
        try {{ Remove-Item -LiteralPath $backup -Recurse -Force }} catch {{ }}
    }}
    # Limpeza nao pode transformar uma atualizacao ja aplicada em erro na tela.
    try {{ Remove-OnlyInside $stage ([System.IO.Path]::GetDirectoryName($stage)) }} catch {{ }}
}} catch {{
    Show-UpdateFailure ("A atualizacao nao foi aplicada. A versao anterior foi preservada quando possivel.\\n\\n" + $_.Exception.Message)
}}
"""


def launch_prepared_update(
    prepared: PreparedUpdate,
    installation: Installation | None = None,
    *,
    pid: int | None = None,
) -> Path:
    """Agenda a troca apos fechar; nao toca na instalacao antes disso."""

    install = installation or current_installation()
    if install.is_development_checkout:
        raise UpdateError(
            "Atualizacao automatica e desativada no repositorio de desenvolvimento para nao sobrescrever seu trabalho."
        )
    if install.kind != prepared.offer.artifact.kind:
        raise UpdateIntegrityError("o pacote baixado nao corresponde a esta instalacao")
    if not install.root.is_dir() or not prepared.payload_dir.is_dir():
        raise UpdateError("a instalacao ou a atualizacao preparada desapareceu")
    # O helper nao pode morar no stage: ele precisa apagar o stage depois de
    # mover o payload, e o Windows nao deixa um script em execucao apagar a
    # propria pasta. Os helpers antigos sao pequenos e ficam fora do payload.
    launcher_dir = update_cache_dir() / "launchers"
    try:
        launcher_dir.mkdir(parents=True, exist_ok=True)
        script = launcher_dir / f"aplicar-atualizacao-{uuid.uuid4().hex}.ps1"
        script.write_text(
            _apply_script(installation=install, prepared=prepared, pid=pid or os.getpid()),
            encoding="utf-8",
        )
    except OSError as exc:
        raise UpdateError("nao consegui preparar o instalador da atualizacao") from exc
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            creationflags=creation_flags,
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError("nao consegui iniciar o instalador da atualizacao") from exc
    return script
