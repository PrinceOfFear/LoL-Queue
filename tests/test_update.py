"""Contrato do atualizador: release assinada, staging seguro e tela responsiva."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from lolqueue import atualizacao_embutida
from lolqueue.atualizacao import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    GithubReleaseClient,
    Installation,
    PreparedUpdate,
    UpdateArtifact,
    UpdateIntegrityError,
    UpdateOffer,
    canonical_manifest,
    generate_keypair,
    launch_prepared_update,
    prepare_update,
    sign_manifest,
)


class Response:
    """Resposta requests minima para testar sem falar com a internet."""

    def __init__(self, *, content: bytes = b"", payload=None, url: str) -> None:
        self.content = content
        self._payload = payload
        self.url = url
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]


def _zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def _offer(archive: bytes, *, root: str = "LoL Queue") -> UpdateOffer:
    artifact = UpdateArtifact(
        "standalone",
        "LoL Queue-1.0.1-win64.zip",
        hashlib.sha256(archive).hexdigest(),
        len(archive),
        root,
        "https://objects.githubusercontent.com/package.zip",
    )
    return UpdateOffer("1.0.0", "1.0.1", "Correcao", artifact)


def _signed_release(archive: bytes, private: str) -> tuple[dict, dict[str, bytes]]:
    offer = _offer(archive)
    manifest = {
        "schema": 1,
        "version": offer.version,
        "notes": offer.notes,
        "artifacts": {
            "standalone": {
                "file": offer.artifact.filename,
                "sha256": offer.artifact.sha256,
                "size": offer.artifact.size,
                "root": offer.artifact.root,
            },
            "python": {
                "file": "LoL Queue-1.0.1-instalacao-python.zip",
                "sha256": "0" * 64,
                "size": 1,
                "root": "LoL Queue Python",
            },
        },
    }
    raw = canonical_manifest(manifest)
    signature = sign_manifest(raw, private).encode("ascii")
    urls = {
        MANIFEST_NAME: "https://github.com/assets/manifest",
        SIGNATURE_NAME: "https://github.com/assets/signature",
        offer.artifact.filename: offer.artifact.url,
        "LoL Queue-1.0.1-instalacao-python.zip": "https://github.com/assets/python",
    }
    release = {
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": name, "browser_download_url": url}
            for name, url in urls.items()
        ],
    }
    return release, {
        urls[MANIFEST_NAME]: raw,
        urls[SIGNATURE_NAME]: signature,
        offer.artifact.url: archive,
        urls["LoL Queue-1.0.1-instalacao-python.zip"]: b"x",
    }


def test_signed_release_is_checked_downloaded_and_staged(tmp_path):
    archive = _zip({"LoL Queue/LoL Queue.exe": b"executable", "LoL Queue/readme.txt": b"ok"})
    private, public = generate_keypair()
    release, assets = _signed_release(archive, private)

    def get(url, **_kwargs):
        if url.endswith("/releases/latest"):
            return Response(payload=release, url=url)
        return Response(content=assets[url], url=url)

    client = GithubReleaseClient("owner/repository", public, version="1.0.0", get=get)
    offer = client.check("standalone")

    assert offer.version == "1.0.1"
    downloaded = client.download(offer, directory=tmp_path / "cache")
    prepared = prepare_update(offer, downloaded, directory=tmp_path / "cache")

    assert prepared.payload_dir == prepared.stage_dir / "LoL Queue"
    assert (prepared.payload_dir / "LoL Queue.exe").read_bytes() == b"executable"


def test_release_manifest_has_a_strict_small_size_limit():
    private, public = generate_keypair()
    archive = _zip({"LoL Queue/LoL Queue.exe": b"executable"})
    release, assets = _signed_release(archive, private)
    assets["https://github.com/assets/manifest"] = b"x" * (1024 * 1024 + 1)

    def get(url, **_kwargs):
        if url.endswith("/releases/latest"):
            return Response(payload=release, url=url)
        return Response(content=assets[url], url=url)

    with pytest.raises(UpdateIntegrityError, match="excede o limite"):
        GithubReleaseClient("owner/repository", public, version="1.0.0", get=get).check("standalone")


def test_staging_normalizes_windows_paths_and_rejects_escape_or_collisions(tmp_path):
    # `Compress-Archive` do Windows cria ZIPs oficiais com barra invertida.
    # Ela precisa ser normalizada antes de se procurar `..`; a colisao de caixa
    # também sobrescreveria um arquivo no destino Windows.
    valid_windows = _zip({"LoL Queue\\LoL Queue.exe": b"ok"})
    valid_path = tmp_path / "windows.zip"
    valid_path.write_bytes(valid_windows)
    prepared = prepare_update(_offer(valid_windows), valid_path, directory=tmp_path / "cache")
    assert (prepared.payload_dir / "LoL Queue.exe").is_file()

    unsafe = _zip({"LoL Queue\\..\\fora.txt": b"x", "LoL Queue/LoL Queue.exe": b"ok"})
    unsafe_path = tmp_path / "unsafe.zip"
    unsafe_path.write_bytes(unsafe)
    with pytest.raises(UpdateIntegrityError, match="caminho inseguro"):
        prepare_update(_offer(unsafe), unsafe_path, directory=tmp_path / "cache")

    collision = _zip({"LoL Queue/LoL Queue.exe": b"ok", "LoL Queue/README.txt": b"a", "LoL Queue/readme.txt": b"b"})
    collision_path = tmp_path / "collision.zip"
    collision_path.write_bytes(collision)
    with pytest.raises(UpdateIntegrityError, match="duplicados"):
        prepare_update(_offer(collision), collision_path, directory=tmp_path / "cache")


def test_embedded_trust_anchor_cannot_be_overridden_by_environment(monkeypatch):
    monkeypatch.setattr(atualizacao_embutida, "REPOSITORIO", "official/LoL-Queue")
    monkeypatch.setattr(atualizacao_embutida, "CHAVE_PUBLICA", "official-key")
    monkeypatch.setenv(atualizacao_embutida.VAR_REPOSITORIO, "attacker/update")
    monkeypatch.setenv(atualizacao_embutida.VAR_CHAVE, "attacker-key")

    assert atualizacao_embutida.repositorio() == "official/LoL-Queue"
    assert atualizacao_embutida.chave_publica() == "official-key"


def test_apply_helper_lives_outside_staging_and_keeps_python_path_quoted(tmp_path, monkeypatch):
    root = tmp_path / "LoL Queue Python"
    payload = tmp_path / "stage" / "LoL Queue Python"
    root.mkdir()
    payload.mkdir(parents=True)
    (payload / "main.py").write_text("# new", encoding="utf-8")
    offer = UpdateOffer(
        "1.0.0",
        "1.0.1",
        "",
        UpdateArtifact("python", "update.zip", "0" * 64, 1, "LoL Queue Python", "https://example.com/update.zip"),
    )
    prepared = PreparedUpdate(offer, payload.parent, payload)
    installation = Installation("python", root, tmp_path / "Python 3.13" / "pythonw.exe")
    started = []

    class Process:
        pass

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local app data"))
    monkeypatch.setattr("lolqueue.atualizacao.subprocess.Popen", lambda args, **kwargs: started.append((args, kwargs)) or Process())

    script = launch_prepared_update(prepared, installation, pid=123)
    text = script.read_text(encoding="utf-8")

    assert script.parent.name == "launchers"
    assert script.parent != prepared.stage_dir.parent
    assert "Set-Location -LiteralPath $root" in text
    assert "$mainArgument = '\"' + (Join-Path $root 'main.py') + '\"'" in text
    assert "-PassThru" in text
    assert started and started[0][0][0].endswith("powershell.exe")
