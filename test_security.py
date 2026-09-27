"""Local tests for authentication, encrypted storage and PDF reports."""
import os
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

import db
import report
import storage


class SecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "test.db"
        storage.STORAGE_ROOT = Path(self.temp_dir.name) / "documents"
        os.environ["PRISMA_STORAGE_KEY"] = Fernet.generate_key().decode()
        db.init_db()

    def tearDown(self):
        os.environ.pop("PRISMA_STORAGE_KEY", None)
        self.temp_dir.cleanup()

    def test_password_is_hashed_and_authentication_works(self):
        user = db.create_user("test@example.com", "mot-de-passe-solide")

        self.assertEqual(db.authenticate("test@example.com", "mot-de-passe-solide")["id"], user["id"])
        self.assertIsNone(db.authenticate("test@example.com", "mauvais-mot-de-passe"))
        with db._connect() as connection:
            raw = connection.execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertNotIn("mot-de-passe-solide", raw)

    def test_document_is_encrypted_on_disk(self):
        user = db.create_user("storage@example.com", "mot-de-passe-solide")
        path = storage.save_document(user["id"], "report-1", "piece.txt", b"contenu confidentiel")

        self.assertNotEqual(path.read_bytes(), b"contenu confidentiel")
        self.assertEqual(storage.read_document(path), b"contenu confidentiel")

    def test_pdf_is_generated(self):
        data = report.build_pdf(
            [{"id": "E1", "texte": "Fournir une pièce", "verdict": "conforme", "document": "piece.pdf", "page": 1}],
            {"titre": "GO", "message": "Les pièces obligatoires sont conformes."}, 100,
        )

        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 500)


if __name__ == "__main__":
    unittest.main()
