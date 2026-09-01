"""Persistencia SQLite pequena e transacional para licencas."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


CHAVE_RE = re.compile(r"^LQ-[A-Z2-9]{4}(?:-[A-Z2-9]{4}){2}$")
MAQUINA_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def normalizar_chave(value: str) -> str:
    key = (value or "").strip().upper()
    if not CHAVE_RE.fullmatch(key):
        raise ValueError("chave de ativacao invalida")
    return key


def validar_maquina(value: str) -> str:
    machine = (value or "").strip()
    if not MAQUINA_RE.fullmatch(machine):
        raise ValueError("impressao do computador invalida")
    return machine


def hash_chave(key: str) -> str:
    return hashlib.sha256(normalizar_chave(key).encode("ascii")).hexdigest()


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LicenseStore:
    """Banco com conexoes curtas; nenhum estado de request fica global."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS licenses (
                    key_hash TEXT PRIMARY KEY,
                    machine TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    plan TEXT NOT NULL DEFAULT 'mensal',
                    paid_until INTEGER NOT NULL DEFAULT 0,
                    email TEXT NOT NULL DEFAULT '',
                    picpay_subscription_id TEXT UNIQUE,
                    picpay_charge_id TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_licenses_subscription
                    ON licenses(picpay_subscription_id);
                """
            )

    def find(self, key: str) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM licenses WHERE key_hash = ?", (hash_chave(key),)
            ).fetchone()

    def find_by_provider_id(self, provider_id: str) -> sqlite3.Row | None:
        if not provider_id:
            return None
        with self.connection() as conn:
            return conn.execute(
                """SELECT * FROM licenses
                   WHERE picpay_subscription_id = ? OR picpay_charge_id = ?""",
                (provider_id, provider_id),
            ).fetchone()

    def bind_and_touch(self, key: str, machine: str, *, now: str) -> sqlite3.Row:
        key_hash = hash_chave(key)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM licenses WHERE key_hash = ?", (key_hash,)
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError("chave nao encontrada")
            if row["machine"] and row["machine"] != machine:
                conn.rollback()
                raise PermissionError("essa chave ja esta vinculada a outro computador")
            conn.execute(
                """UPDATE licenses SET machine = COALESCE(machine, ?),
                   updated_at = ?, last_seen = ? WHERE key_hash = ?""",
                (machine, now, now, key_hash),
            )
            conn.commit()
            return conn.execute(
                "SELECT * FROM licenses WHERE key_hash = ?", (key_hash,)
            ).fetchone()

    def touch(self, key: str, *, now: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE licenses SET last_seen = ?, updated_at = ? WHERE key_hash = ?",
                (now, now, hash_chave(key)),
            )

    def release(self, key: str, machine: str, *, now: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """UPDATE licenses SET machine = NULL, updated_at = ?
                   WHERE key_hash = ? AND machine = ?""",
                (now, hash_chave(key), machine),
            )
            return cursor.rowcount == 1

    def apply_payment_event(
        self,
        event_id: str,
        provider_id: str,
        *,
        status: str,
        paid_until: int,
        charge_id: str = "",
        now: str,
    ) -> str:
        """Registra o webhook e atualiza a licença na mesma transação.

        Assim uma falha entre o INSERT do evento e o UPDATE da licença não
        consome o evento: o PicPay pode reenviá-lo com segurança.
        """
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO webhook_events(event_id, received_at) VALUES (?, ?)",
                    (event_id, now),
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return "duplicate"
            cursor = conn.execute(
                """UPDATE licenses SET status = ?, paid_until = ?,
                   picpay_charge_id = COALESCE(NULLIF(?, ''), picpay_charge_id),
                   updated_at = ?
                   WHERE picpay_subscription_id = ? OR picpay_charge_id = ?""",
                (status, paid_until, charge_id, now, provider_id, provider_id),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return "not_applied"
            conn.commit()
            return "applied"

    def update_payment(
        self,
        provider_id: str,
        *,
        status: str,
        paid_until: int,
        charge_id: str = "",
        now: str,
    ) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """UPDATE licenses SET status = ?, paid_until = ?,
                   picpay_charge_id = COALESCE(NULLIF(?, ''), picpay_charge_id),
                   updated_at = ?
                   WHERE picpay_subscription_id = ? OR picpay_charge_id = ?""",
                (status, paid_until, charge_id, now, provider_id, provider_id),
            )
            return cursor.rowcount == 1

    def provision(
        self,
        key: str,
        *,
        paid_until: int,
        email: str = "",
        provider_subscription_id: str = "",
        provider_charge_id: str = "",
        now: str,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO licenses(
                    key_hash, paid_until, email, picpay_subscription_id,
                    picpay_charge_id, created_at, updated_at
                ) VALUES (?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), ?, ?)
                ON CONFLICT(key_hash) DO UPDATE SET
                    paid_until = excluded.paid_until,
                    email = excluded.email,
                    picpay_subscription_id = COALESCE(excluded.picpay_subscription_id, picpay_subscription_id),
                    picpay_charge_id = COALESCE(excluded.picpay_charge_id, picpay_charge_id),
                    status = 'active', updated_at = excluded.updated_at""",
                (
                    hash_chave(key),
                    paid_until,
                    email,
                    provider_subscription_id,
                    provider_charge_id,
                    now,
                    now,
                ),
            )

    def attach_charge(self, provider_subscription_id: str, charge_id: str, *, now: str) -> None:
        if not charge_id:
            return
        with self.connection() as conn:
            conn.execute(
                """UPDATE licenses SET picpay_charge_id = ?, updated_at = ?
                   WHERE picpay_subscription_id = ?""",
                (charge_id, now, provider_subscription_id),
            )
