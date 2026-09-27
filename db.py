"""Persistence SQLite and password authentication for PRISMA."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("PRISMA_DB_PATH", ".prisma/prisma.db"))
PBKDF2_ITERATIONS = 310_000


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                report_id TEXT NOT NULL,
                original_name TEXT NOT NULL,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS reports_user_idx ON reports(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS documents_report_idx ON documents(report_id);
            """
        )


def _hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _check_password(password, encoded):
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


def create_user(email, password):
    email = email.strip().lower()
    if "@" not in email or len(email) > 254:
        raise ValueError("Adresse e-mail invalide.")
    if len(password) < 10:
        raise ValueError("Le mot de passe doit contenir au moins 10 caractères.")
    user_id = str(uuid.uuid4())
    try:
        with _connect() as connection:
            connection.execute(
                "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, email, _hash_password(password), str(int(time.time()))),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Cette adresse e-mail est déjà enregistrée.") from exc
    return {"id": user_id, "email": email}


def authenticate(email, password):
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    if not row or not _check_password(password, row["password_hash"]):
        return None
    return {"id": row["id"], "email": row["email"]}


def save_report(user_id, report_id, name, payload):
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO reports (id, user_id, name, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (report_id, user_id, name, json.dumps(payload, ensure_ascii=False, default=str), str(int(time.time()))),
        )


def list_reports(user_id):
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, name, created_at FROM reports WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def load_report(user_id, report_id):
    with _connect() as connection:
        row = connection.execute(
            "SELECT payload FROM reports WHERE id = ? AND user_id = ?", (report_id, user_id)
        ).fetchone()
    if not row:
        raise ValueError("Rapport introuvable.")
    return json.loads(row["payload"])


def save_document_metadata(user_id, report_id, original_name, path):
    with _connect() as connection:
        connection.execute(
            "INSERT INTO documents (id, user_id, report_id, original_name, path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, report_id, original_name, str(path), str(int(time.time()))),
        )
