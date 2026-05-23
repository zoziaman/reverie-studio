import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_LICENSE_KEY = "TEST-1234-5678-ABCD"


class _FakeDocument:
    exists = True

    def set(self, data):
        self.data = data

    def get(self):
        return self

    def to_dict(self):
        return {
            "license_key": TEST_LICENSE_KEY,
            "license_type": "T",
            "is_active": True,
            "owned_packs": ["horror_pack", "romance_pack"],
            "memo": "test license",
        }


class _FakeCollection:
    def __init__(self):
        self.document_id = None
        self.document_ref = _FakeDocument()

    def document(self, document_id):
        self.document_id = document_id
        return self.document_ref


class _FakeDb:
    def __init__(self):
        self.collection_ref = _FakeCollection()

    def collection(self, name):
        assert name == "licenses"
        return self.collection_ref


def _load_create_test_license(monkeypatch):
    fake_db = _FakeDb()
    fake_firebase_admin = types.ModuleType("firebase_admin")
    fake_firebase_admin._apps = ["already initialized"]
    fake_credentials = types.ModuleType("firebase_admin.credentials")
    fake_credentials.Certificate = lambda path: object()
    fake_firestore = types.ModuleType("firebase_admin.firestore")
    fake_firestore.SERVER_TIMESTAMP = object()
    fake_firestore.client = lambda: fake_db
    fake_firebase_admin.credentials = fake_credentials
    fake_firebase_admin.firestore = fake_firestore

    monkeypatch.setitem(sys.modules, "firebase_admin", fake_firebase_admin)
    monkeypatch.setitem(sys.modules, "firebase_admin.credentials", fake_credentials)
    monkeypatch.setitem(sys.modules, "firebase_admin.firestore", fake_firestore)

    spec = importlib.util.spec_from_file_location(
        "create_test_license_under_test",
        ROOT / "scripts" / "create_test_license.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake_db


def test_create_test_license_output_hides_license_key(monkeypatch, capsys):
    module, fake_db = _load_create_test_license(monkeypatch)

    assert module.create_test_license() is True

    output = capsys.readouterr().out
    assert fake_db.collection_ref.document_id == TEST_LICENSE_KEY
    assert TEST_LICENSE_KEY not in output
    assert "TEST-****-****-ABCD" in output


def test_verify_license_output_hides_license_key(monkeypatch, capsys):
    module, _fake_db = _load_create_test_license(monkeypatch)

    assert module.verify_license() is True

    output = capsys.readouterr().out
    assert TEST_LICENSE_KEY not in output
    assert "TEST-****-****-ABCD" in output
