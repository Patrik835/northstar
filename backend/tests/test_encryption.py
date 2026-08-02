from app.core.encryption import CredentialCipher, mask_secret

TEST_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def test_credentials_round_trip_without_plaintext_storage() -> None:
    credentials = {"api_key": "public-part", "secret_key": "never-store-plain"}
    encrypted = CredentialCipher(TEST_KEY).encrypt(credentials)
    assert b"never-store-plain" not in encrypted
    assert CredentialCipher(TEST_KEY).decrypt(encrypted) == credentials


def test_mask_only_reveals_last_four_characters() -> None:
    assert mask_secret("abcdefgh") == "••••efgh"
