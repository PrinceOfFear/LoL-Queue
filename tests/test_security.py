"""O selo de integridade e a tela de seguranca nunca confiam no proprio ZIP."""

from __future__ import annotations

from pathlib import Path

from lolqueue.seguranca import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    SecurityState,
    canonical_manifest,
    inspect,
    sign_manifest,
    verify_bundle,
    write_signed_manifest,
)


def _bundle(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "LoL Queue"
    (root / "lolqueue" / "assets").mkdir(parents=True)
    (root / "LoL Queue.exe").write_bytes(b"executavel de teste")
    (root / "lolqueue" / "assets" / "icon.png").write_bytes(b"icone")
    # Chaves curtas de teste so existem durante este teste.
    from lolqueue.atualizacao import generate_keypair

    private, public = generate_keypair()
    write_signed_manifest(root, "1.0.0", private)
    return root, private, public


def test_signed_bundle_passes_and_ignores_python_cache(tmp_path):
    root, _private, public = _bundle(tmp_path)
    cache = root / "lolqueue" / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-313.pyc").write_bytes(b"cache local")

    result = verify_bundle(root, public)

    assert result.state is SecurityState.PASSED


def test_changed_or_added_file_fails_integrity_check(tmp_path):
    root, _private, public = _bundle(tmp_path)
    (root / "LoL Queue.exe").write_bytes(b"arquivo alterado")

    changed = verify_bundle(root, public)
    assert changed.state is SecurityState.FAILED

    # Uma segunda distribuicao prova tambem que arquivo extra e detectado.
    other, _private, other_public = _bundle(tmp_path / "other")
    (other / "extra.exe").write_bytes(b"nao assinado")
    added = verify_bundle(other, other_public)
    assert added.state is SecurityState.FAILED


def test_manifest_with_escape_path_is_rejected_even_when_signed(tmp_path):
    root = tmp_path / "LoL Queue"
    root.mkdir()
    from lolqueue.atualizacao import generate_keypair

    private, public = generate_keypair()
    raw = canonical_manifest(
        {
            "schema": 1,
            "version": "1.0.0",
            "files": [{"path": "../outside.exe", "sha256": "0" * 64, "size": 0}],
        }
    )
    (root / MANIFEST_NAME).write_bytes(raw)
    (root / SIGNATURE_NAME).write_text(sign_manifest(raw, private), encoding="ascii")

    result = verify_bundle(root, public)

    assert result.state is SecurityState.FAILED
    assert "caminho" in result.detail


def test_development_inspection_does_not_require_a_distribution_manifest(tmp_path):
    report = inspect(tmp_path, development=True)

    integrity = next(check for check in report.checks if check.key == "integrity")
    assert integrity.state is SecurityState.INFO
