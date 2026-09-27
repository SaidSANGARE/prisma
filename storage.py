"""Encrypted local document storage for PRISMA."""
import os
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

import db

STORAGE_ROOT = Path(os.getenv("PRISMA_STORAGE_DIR", ".prisma/documents"))


def _fernet():
    key = os.getenv("PRISMA_STORAGE_KEY", "").strip()
    if not key:
        raise RuntimeError("PRISMA_STORAGE_KEY est absente : stockage chiffré indisponible.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("PRISMA_STORAGE_KEY doit être une clé Fernet valide.") from exc


def is_configured():
    return bool(os.getenv("PRISMA_STORAGE_KEY", "").strip())


def save_document(user_id, report_id, original_name, content):
    encrypted = _fernet().encrypt(content)
    folder = STORAGE_ROOT / user_id / report_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.bin"
    path.write_bytes(encrypted)
    db.save_document_metadata(user_id, report_id, original_name, path)
    return path


def read_document(path):
    try:
        return _fernet().decrypt(Path(path).read_bytes())
    except InvalidToken as exc:
        raise RuntimeError("Document chiffré invalide ou clé incorrecte.") from exc
