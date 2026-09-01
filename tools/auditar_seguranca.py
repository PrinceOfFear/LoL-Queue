"""Auditoria local repetivel do LoL Queue.

O script nao substitui uma revisao humana nem o plugin Codex Security. Ele
deixa verificaveis as garantias que podem rodar sem credenciais: compilacao,
padroes perigosos em Python, segredos acidentais, dependencias opcionais e a
suíte de testes. O modo ``--release`` tambem exige que a trava de licenca esteja
embutida antes de uma entrega.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVOS = (RAIZ / "lolqueue", RAIZ / "servidor", RAIZ / "main.py")
IGNORADOS = {"__pycache__", ".git", "build", "dist", "dist-standalone", "Distribuicao"}
SEGREDO = re.compile(
    r"(?:BEGIN (?:RSA|OPENSSH|EC|PRIVATE) KEY|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})"
)


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    file: str
    line: int
    message: str


def _py_files() -> list[Path]:
    files: list[Path] = []
    for root in ARQUIVOS:
        if root.is_file():
            files.append(root)
            continue
        if root.is_dir():
            files.extend(
                path
                for path in root.rglob("*.py")
                if not any(part in IGNORADOS for part in path.parts)
            )
    return sorted(set(files))


def _findings() -> list[Finding]:
    found: list[Finding] = []
    for path in _py_files():
        relative = path.relative_to(RAIZ).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text.removeprefix("\ufeff"), filename=relative)
        except (OSError, SyntaxError) as exc:
            found.append(Finding("PY-SYNTAX", "high", relative, 1, str(exc)))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                found.append(
                    Finding(
                        "PY-DYNAMIC-CODE",
                        "low" if relative.startswith("tools/") else "high",
                        relative,
                        node.lineno,
                        f"{node.func.id}() executa texto; confirme que a origem e um arquivo local confiavel",
                    )
                )
            if isinstance(node, ast.keyword) and node.arg == "shell" and isinstance(node.value, ast.Constant) and node.value.value is True:
                found.append(Finding("PY-SHELL-INJECTION", "critical", relative, node.lineno, "subprocess com shell=True"))
        for number, line in enumerate(text.splitlines(), 1):
            if SEGREDO.search(line):
                found.append(Finding("SECRET-IN-SOURCE", "critical", relative, number, "possivel segredo em codigo-fonte"))
    return found


def _run(command: list[str], *, timeout: int = 300) -> dict:
    try:
        result = subprocess.run(command, cwd=RAIZ, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "returncode": None, "detail": str(exc)}
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "detail": (result.stdout + result.stderr)[-4000:],
    }


def _run_optional_module(module: str, args: list[str], *, timeout: int = 300) -> dict:
    """Executa uma ferramenta via o mesmo Python, inclusive no Windows."""
    if importlib.util.find_spec(module) is None:
        return {
            "ok": None,
            "available": False,
            "returncode": None,
            "detail": f"{module} nao esta instalado; instale o extra [security] no CI",
        }
    result = _run([sys.executable, "-m", module, *args], timeout=timeout)
    result["available"] = True
    return result


def executar(*, tests: bool, release: bool) -> dict:
    findings = _findings()
    checks = {"compile": _run([sys.executable, "-m", "compileall", "-q", "lolqueue", "servidor", "tools", "main.py"])}
    if tests:
        checks["tests"] = _run([sys.executable, "-m", "pytest", "tests", "-q"])
    if release:
        checks["license_gate"] = _run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools/build.ps1"],
            timeout=30,
        )
        # A release build without embedded licensing must be rejected. The
        # expected non-zero result is therefore a passing gate in this source checkout.
        checks["license_gate"]["expected_rejection"] = True
        checks["bandit"] = _run_optional_module(
            "bandit", ["-q", "-r", "lolqueue", "servidor", "tools", "-ll"], timeout=300
        )
        checks["pip_audit"] = _run_optional_module(
            "pip_audit",
            ["--progress-spinner", "off", "--skip-editable", str(RAIZ)],
            timeout=300,
        )
    if any(item.severity in {"critical", "high"} for item in findings):
        outcome = "review_required"
    elif not checks["compile"]["ok"] or (tests and not checks["tests"]["ok"]):
        outcome = "failed"
    elif any(
        check.get("available") and not check.get("ok")
        for name, check in checks.items()
        if name in {"bandit", "pip_audit"}
    ):
        outcome = "review_required"
    else:
        outcome = "pass"
    return {"outcome": outcome, "findings": [asdict(item) for item in findings], "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests", action="store_true", help="rode toda a suíte pytest")
    parser.add_argument("--release", action="store_true", help="verifique tambem o gate de build pago")
    parser.add_argument("--json", dest="json_path", type=Path, help="grave o resultado em JSON")
    args = parser.parse_args(argv)
    result = executar(tests=args.tests, release=args.release)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.json_path:
        args.json_path.expanduser().resolve().write_text(text + "\n", encoding="utf-8")
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
