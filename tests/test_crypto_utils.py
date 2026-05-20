# tests/test_crypto_utils.py
"""
crypto_utils.py 단위 테스트 (v62.41 pre-production review)

커버리지:
- derive_fernet_key: PBKDF2 키 파생 일관성
- fernet_encrypt / fernet_decrypt: 라운드트립
- fernet_encrypt_bytes / fernet_decrypt_bytes: 바이트 라운드트립
- atomic_json_write / atomic_json_read: 원자적 쓰기 + 읽기
- encrypted_json_write / encrypted_json_read: 암호화된 JSON 라운드트립
- encrypted_json_read: 평문 JSON 자동 마이그레이션
- 엣지 케이스: 잘못된 키, 빈 파일, 존재하지 않는 파일
"""
import os
import json
import pytest

# conftest.py가 sys.path에 src/ 추가
from utils.crypto_utils import (
    derive_fernet_key,
    fernet_encrypt,
    fernet_decrypt,
    fernet_encrypt_bytes,
    fernet_decrypt_bytes,
    atomic_json_write,
    atomic_json_read,
    encrypted_json_write,
    encrypted_json_read,
    FERNET_AVAILABLE,
)

# ============================================================
# 키 파생
# ============================================================

class TestDeriveFernetKey:
    def test_deterministic(self):
        """같은 입력 → 같은 키"""
        k1 = derive_fernet_key("test_password", "salt1")
        k2 = derive_fernet_key("test_password", "salt1")
        assert k1 == k2

    def test_different_password(self):
        """다른 비밀번호 → 다른 키"""
        k1 = derive_fernet_key("pw_a", "salt")
        k2 = derive_fernet_key("pw_b", "salt")
        assert k1 != k2

    def test_different_salt(self):
        """다른 솔트 → 다른 키"""
        k1 = derive_fernet_key("pw", "salt_a")
        k2 = derive_fernet_key("pw", "salt_b")
        assert k1 != k2

    def test_key_length(self):
        """Fernet 키 = 44바이트 base64url"""
        key = derive_fernet_key("password")
        assert len(key) == 44  # 32 bytes base64url → 44 chars


# ============================================================
# Fernet 문자열 암호화/복호화
# ============================================================

@pytest.mark.skipif(not FERNET_AVAILABLE, reason="cryptography 미설치")
class TestFernetString:
    @pytest.fixture
    def key(self):
        return derive_fernet_key("test_key_123")

    def test_roundtrip(self, key):
        """암호화 → 복호화 = 원본"""
        plaintext = "Hello, 안녕하세요! 테스트 데이터"
        encrypted = fernet_encrypt(plaintext, key)
        decrypted = fernet_decrypt(encrypted, key)
        assert decrypted == plaintext

    def test_encrypted_differs(self, key):
        """암호화된 텍스트 ≠ 원본"""
        plaintext = "secret data"
        encrypted = fernet_encrypt(plaintext, key)
        assert encrypted != plaintext
        assert encrypted.startswith("gAAAAA")

    def test_wrong_key_fails(self, key):
        """잘못된 키 → InvalidToken"""
        from cryptography.fernet import InvalidToken
        encrypted = fernet_encrypt("data", key)
        wrong_key = derive_fernet_key("wrong_key")
        with pytest.raises(InvalidToken):
            fernet_decrypt(encrypted, wrong_key)

    def test_empty_string(self, key):
        """빈 문자열 라운드트립"""
        encrypted = fernet_encrypt("", key)
        assert fernet_decrypt(encrypted, key) == ""


# ============================================================
# Fernet 바이트 암호화/복호화
# ============================================================

@pytest.mark.skipif(not FERNET_AVAILABLE, reason="cryptography 미설치")
class TestFernetBytes:
    @pytest.fixture
    def key(self):
        return derive_fernet_key("byte_test_key")

    def test_roundtrip(self, key):
        data = b"\x00\x01\x02\xff binary data"
        encrypted = fernet_encrypt_bytes(data, key)
        decrypted = fernet_decrypt_bytes(encrypted, key)
        assert decrypted == data

    def test_empty_bytes(self, key):
        encrypted = fernet_encrypt_bytes(b"", key)
        assert fernet_decrypt_bytes(encrypted, key) == b""


# ============================================================
# Atomic JSON
# ============================================================

class TestAtomicJson:
    def test_write_and_read(self, tmp_path):
        path = str(tmp_path / "test.json")
        data = {"key": "value", "num": 42, "한글": "테스트"}
        atomic_json_write(path, data)
        result = atomic_json_read(path)
        assert result == data

    def test_read_nonexistent(self, tmp_path):
        path = str(tmp_path / "no_such_file.json")
        assert atomic_json_read(path) is None

    def test_read_invalid_json(self, tmp_path):
        path = str(tmp_path / "bad.json")
        with open(path, 'w') as f:
            f.write("not valid json{{{")
        assert atomic_json_read(path) is None

    def test_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "a" / "b" / "c" / "test.json")
        atomic_json_write(path, [1, 2, 3])
        assert atomic_json_read(path) == [1, 2, 3]

    def test_overwrite(self, tmp_path):
        path = str(tmp_path / "overwrite.json")
        atomic_json_write(path, {"v": 1})
        atomic_json_write(path, {"v": 2})
        assert atomic_json_read(path) == {"v": 2}


# ============================================================
# 암호화된 JSON
# ============================================================

@pytest.mark.skipif(not FERNET_AVAILABLE, reason="cryptography 미설치")
class TestEncryptedJson:
    @pytest.fixture
    def key(self):
        return derive_fernet_key("json_enc_key")

    def test_roundtrip(self, key, tmp_path):
        path = str(tmp_path / "enc.json")
        data = {"secret": "value", "list": [1, 2, 3]}
        encrypted_json_write(path, data, key)
        result = encrypted_json_read(path, key)
        assert result == data

    def test_file_encrypted_on_disk(self, key, tmp_path):
        """디스크에 평문이 없어야 함"""
        path = str(tmp_path / "enc2.json")
        encrypted_json_write(path, {"pw": "12345"}, key)
        with open(path, 'r') as f:
            raw = f.read()
        assert "12345" not in raw
        assert raw.startswith("gAAAAA")

    def test_wrong_key_returns_none(self, key, tmp_path):
        path = str(tmp_path / "enc3.json")
        encrypted_json_write(path, {"x": 1}, key)
        wrong_key = derive_fernet_key("wrong")
        assert encrypted_json_read(path, wrong_key) is None

    def test_plaintext_auto_migration(self, key, tmp_path):
        """평문 JSON → Fernet 자동 마이그레이션"""
        path = str(tmp_path / "plain.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({"migrated": True}, f)
        # 읽기 → 데이터 반환 + 파일 암호화
        result = encrypted_json_read(path, key)
        assert result == {"migrated": True}
        # 디스크가 암호화로 변환되었는지 확인
        with open(path, 'r') as f:
            raw = f.read()
        assert raw.startswith("gAAAAA")

    def test_nonexistent_returns_none(self, key, tmp_path):
        path = str(tmp_path / "nope.json")
        assert encrypted_json_read(path, key) is None

    def test_empty_file_returns_none(self, key, tmp_path):
        path = str(tmp_path / "empty.json")
        with open(path, 'w') as f:
            f.write("")
        assert encrypted_json_read(path, key) is None
