from app.core.encryption import CredentialCipher, mask_secret

TEST_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def test_credentials_round_trip_without_plaintext_storage() -> None:
    credentials = {"api_key": "public-part", "secret_key": "never-store-plain"}
    encrypted = CredentialCipher(TEST_KEY).encrypt(credentials)
    assert b"never-store-plain" not in encrypted
    assert CredentialCipher(TEST_KEY).decrypt(encrypted) == credentials


def test_mask_only_reveals_last_four_characters() -> None:
    assert mask_secret("abcdefgh") == "••••efgh"


def test_decrypt_credentials_written_by_cryptography_45():
    # Generated using the preceding deployment and its unchanged v1 wire format.
    payload = bytes.fromhex(
        "ddc3a1ebb6c4f49bcf9e58f1f339d37ac769d58c15249025f975fc950be40a079"
        "588dc69ff92c9ec213703c8f529762ea11befe6085627d9f2b4c18b5558e7"
    )
    assert CredentialCipher(TEST_KEY).decrypt(payload) == {"api_key": "compatibility-fixture"}
