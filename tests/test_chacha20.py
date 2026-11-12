"""ChaCha20 without the cryptography package, pinned to the output cryptography gave.

The digests below were produced on 2026-11-12 by ``cryptography`` 50.0.0
(``Cipher(algorithms.ChaCha20(key, nonce), mode=None).encryptor().update``),
the path the archive reader used until then, over payloads made by
``_payload``. Both new paths must reproduce them exactly.
"""

from __future__ import annotations

import hashlib
import random

import pytest

from cdmw.core import chacha20 as chacha20_module
from cdmw.core.archive_format import (
    CHACHA20_HASH_INITVAL,
    crypt_chacha20_filename,
    derive_chacha20_key_iv,
    hashlittle,
)
from cdmw.core.chacha20 import COUNTER_OVERFLOW_MESSAGE, chacha20_backend, chacha20_xor

BACKENDS = ("openssl", "numpy")


def _payload(name: str, size: int) -> bytes:
    return random.Random(f"{name}:{size}").randbytes(size)


PINNED = {
    ('storeinfo.pabgb', 0): 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    ('storeinfo.pabgb', 1): '4c94485e0c21ae6c41ce1dfe7b6bfaceea5ab68e40a2476f50208e526f506080',
    ('storeinfo.pabgb', 63): '8994121f0a0b808846368af30a56520fcdc04cb71c994edbf4355a0282740e06',
    ('storeinfo.pabgb', 64): '1b017fdcb8aa51a85a92b96b13ee5595a0d30e3ea80d2bc72ca99d2bb1320bdd',
    ('storeinfo.pabgb', 65): 'de67382607b3ac9fb2ccb2a4d715379c6d5f5c62fc3ba001b1cf6a5943143864',
    ('storeinfo.pabgb', 1000): '0f401e1697edff5810a9fc6608a007a2b4887f8b04e6950092d3a609f99dc02a',
    ('storeinfo.pabgb', 4096): '77398c6081bcf42afaac276125400f9248033c1b5af3db333b6c6126bc7880f6',
    ('storeinfo.pabgb', 70001): '6668a91d1d7d467219803bf16a4b59ce12220bf8d857d655249e4bb1f0f07a3e',
    ('CD_Item_Icon.XML', 1): 'ca41841c5c98e34f4a3ae83d9220940395301a9616f69d6672b04ea322f28eb0',
    ('CD_Item_Icon.XML', 63): '6b122d628f9d15ced370a995cfa6fa359725793729d235b453964e49ec95a777',
    ('CD_Item_Icon.XML', 64): '0f1a361880cfe5aade82fc6a0a5569ea6244458a22cd0d39c85d491411c4b34e',
    ('CD_Item_Icon.XML', 65): '4818ca42d77f7684d60457f548b5dec4669ff8c623d1672bf9e86e15193b3be4',
    ('CD_Item_Icon.XML', 1000): '90a809a8be7fa0880c14122e5499f6793534b500ca5dc96ae72f3d88097ef7f0',
    ('CD_Item_Icon.XML', 4096): '9d6848519f34217b7c5723a0533cfb5cff7a82ddf00b11310c99b51ad30eb2c1',
    ('CD_Item_Icon.XML', 70001): 'b118fc1594c3bd19d67af08cb0274f025722c689329c2915f5e7da402f107bc6',
    ('localizationstring_eng.paloc', 1): 'cbe5cfdf7c2118a9c3d78ef1d684f3afa089201352886449a06a6511cfef74a7',
    ('localizationstring_eng.paloc', 63): '36359bf7b34f2607dabe8fb9f5c66e71239df9b244615a3350be4db2b9b935ad',
    ('localizationstring_eng.paloc', 64): '904f5f658ca7a47d36f7dc409c3d64f9415ab67f66338a6ad52551b4984bb01d',
    ('localizationstring_eng.paloc', 65): 'a64aa80a5e18f3e52deb72b4eedf442fef48b7bd5e318731ecc3076fe6fbab7f',
    ('localizationstring_eng.paloc', 1000): '954eab38eb854c2104f2bc166d389db4757e89e94fad81b66cf85b1535e15c96',
    ('localizationstring_eng.paloc', 4096): '307def1daa6404797aa2070fa164bdbfe59a2f30152ccbede0d770503ac2944a',
    ('localizationstring_eng.paloc', 70001): 'b02fde527fdc217c1ed25c28d044be503171255f854a9cb94361083fcb691d0f',
    ('ui/xml/texture/main.xml', 1): '41b805ea7ac014e23556e98bb374702a08344268f92489a02f0880849394a1e4',
    ('ui/xml/texture/main.xml', 63): '3001ce2f8509692a1af192b5f92a17fea30e12e622b256154a65f2d5a0fc4ad8',
    ('ui/xml/texture/main.xml', 64): '0568a8daa395a09eea582685b7ee75212e232476d110f0b8b6e1eed54c3e0aa9',
    ('ui/xml/texture/main.xml', 65): 'e38be9080ced7299abb76e866cfb7a56c0f9ed14dd2dfd2a5fdbc277c9129c9c',
    ('ui/xml/texture/main.xml', 1000): '360f174b916e74e0c5deb9ff65b1f0b82ba2f3662d0ca08655a700ca6f4bbecd',
    ('ui/xml/texture/main.xml', 4096): '9042ed3d9f84ea0a2a20a85e92178c5e1490b849d42ea4c66dccc2e245b684eb',
    ('ui/xml/texture/main.xml', 70001): 'a9f51b4e26b1a034359c3579cfa4ba87686f1e454174678120640df93d3b9175',
    ('é_ü.css', 1): '1b16b1df538ba12dc3f97edbb85caa7050d46c148134290feba80f8236c83db9',
    ('é_ü.css', 63): '0db315d8cb532c0a5381b6d232ecb6cd8cf119538a4765f4860e3a1770fbaf23',
    ('é_ü.css', 64): 'd9485f3477d0cd6261120627c85c5e0af3ffb688be74aba0b92665b997576824',
    ('é_ü.css', 65): 'bc74b775f98196efc9b0afdc7f6aa97bab53e5fd621e254620eac51d4b0c291d',
    ('é_ü.css', 1000): '9431789809f69ed7c09f928d30176979ebeed44215452a8990e32d292418bfae',
    ('é_ü.css', 4096): 'e0ea6c42382eee2c482dc65c7e5b89087513698f4692189f3240a7dddc1ed87d',
    ('é_ü.css', 70001): 'eea5ad7cefce58f0de17e364c8b54bc7b3fdcb2e31a07555fa585505cb2a166d',
    ('a', 1): '22adaf058a2cb668b15cb4c1f30e7cc720bbe38c146544169db35fbf630389c4',
    ('a', 63): '40f6fbd043a46332b4b8a7f63b666e7b5570b36c83aac096bdc4f91e3a7bd263',
    ('a', 64): 'c904179aff5f4c96ba64122036b07e2002ed0a666f496773a690c86ce95e2d0d',
    ('a', 65): '50b501e04ef9c41f8776c73cd1575db01d3b0260f3eff722e1a3e62beb9acdb9',
    ('a', 1000): 'bd370dab5a61dc48232a46d545a9d6d25932cf199effdda2f69941a8055e2f9b',
    ('a', 4096): '4b6753f2f7c472ef03c9dec422e44cc781e4f0d71685d260a208569e2911689a',
    ('a', 70001): '3969dcf420f11efd49d9a2de66af41366e9030dc5843901e38b051f0420921f5',
}

RFC7539_PLAINTEXT = (
    b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, "
    b"sunscreen would be it."
)
RFC7539_CIPHERTEXT = bytes.fromhex(
    "6e2e359a2568f98041ba0728dd0d6981e97e7aec1d4360c20a27afccfd9fae0bf91b65c5524733ab8f593dabcd62b357"
    "1639d624e65152ab8f530c359f0861d807ca0dbf500d6a6156a38e088a22b65e52bc514d16ccf806818ce91ab7793736"
    "5af90bbf74a35be6b40b8eedf2785e42874d"
)


def test_the_openssl_path_loads_in_this_interpreter():
    assert chacha20_backend() == "openssl"


@pytest.mark.parametrize("backend", BACKENDS)
def test_rfc7539_section_2_4_2_vector(backend):
    key = bytes(range(32))
    nonce = (1).to_bytes(4, "little") + bytes.fromhex("000000000000004a00000000")
    assert chacha20_xor(RFC7539_PLAINTEXT, key, nonce, backend=backend) == RFC7539_CIPHERTEXT
    assert chacha20_xor(RFC7539_CIPHERTEXT, key, nonce, backend=backend) == RFC7539_PLAINTEXT


@pytest.mark.parametrize("backend", BACKENDS)
def test_archive_keystreams_match_the_pinned_cryptography_output(backend):
    for (name, size), digest in PINNED.items():
        key, nonce = derive_chacha20_key_iv(name)
        output = chacha20_xor(_payload(name, size), key, nonce, backend=backend)
        assert len(output) == size
        assert hashlib.sha256(output).hexdigest() == digest, (name, size)


def test_archive_helper_uses_the_new_path_and_round_trips():
    for (name, size), digest in PINNED.items():
        encrypted = crypt_chacha20_filename(_payload(name, size), name)
        assert hashlib.sha256(encrypted).hexdigest() == digest
        assert crypt_chacha20_filename(encrypted, name) == _payload(name, size)


def test_both_paths_agree_on_random_keys_nonces_and_sizes():
    rng = random.Random(7539)
    for _ in range(120):
        key, nonce = rng.randbytes(32), rng.randbytes(12) + rng.randbytes(4)
        nonce = rng.randbytes(4) + nonce[4:]
        size = rng.choice((0, 1, 31, 63, 64, 65, 129, 1023, 4097, 65_537, 300_001))
        data = rng.randbytes(size)
        try:
            expected = chacha20_xor(data, key, nonce, backend="numpy")
        except ValueError as error:
            with pytest.raises(ValueError, match="32-bit counter"):
                chacha20_xor(data, key, nonce, backend="openssl")
            assert str(error) == COUNTER_OVERFLOW_MESSAGE
            continue
        assert chacha20_xor(data, key, nonce, backend="openssl") == expected


def test_a_multi_pass_numpy_payload_matches_openssl():
    # Longer than one numpy pass (16 Ki blocks), starting near the counter's top.
    key = bytes(range(32, 64))
    nonce = (0xFFFF0000).to_bytes(4, "little") + bytes(range(12))
    data = random.Random(3).randbytes(16 * 1024 * 64 * 2 + 17)
    assert chacha20_xor(data, key, nonce, backend="numpy") == chacha20_xor(data, key, nonce, backend="openssl")


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize(("counter", "size", "accepted"), [
    (0xFFFFFFFF, 0, True),
    (0xFFFFFFFF, 64, True),
    (0xFFFFFFFF, 65, False),
    (0xFFFFFFFE, 128, True),
    (0xFFFFFFFE, 129, False),
    (0, 64 * 4, True),
])
def test_the_counter_never_wraps(backend, counter, size, accepted):
    # cryptography refuses a payload whose blocks would carry the 32-bit counter;
    # the archive's native reader refuses it too (test_native_archive_reader).
    key = bytes(32)
    nonce = counter.to_bytes(4, "little") + bytes(12)
    if accepted:
        assert len(chacha20_xor(bytes(size), key, nonce, backend=backend)) == size
    else:
        with pytest.raises(ValueError) as caught:
            chacha20_xor(bytes(size), key, nonce, backend=backend)
        assert str(caught.value) == COUNTER_OVERFLOW_MESSAGE


def test_archive_names_near_the_counter_top_are_refused_past_their_room():
    name, seed = next(
        (n, s) for n in (f"x{i}.xml" for i in range(2_000_000))
        for s in (hashlittle(n.encode(), CHACHA20_HASH_INITVAL),) if s > 0xFFFF0000
    )
    room = 64 * (2 ** 32 - seed)
    assert len(crypt_chacha20_filename(bytes(room), name)) == room
    with pytest.raises(ValueError, match="32-bit counter"):
        crypt_chacha20_filename(bytes(room + 1), name)


def test_wrong_key_or_nonce_sizes_are_refused():
    with pytest.raises(ValueError, match="key must be 32"):
        chacha20_xor(b"x", bytes(31), bytes(16))
    with pytest.raises(ValueError, match="nonce must be 16"):
        chacha20_xor(b"x", bytes(32), bytes(12))
    with pytest.raises(ValueError, match="Unknown ChaCha20 backend"):
        chacha20_xor(b"x", bytes(32), bytes(16), backend="other")


def test_without_libcrypto_the_numpy_path_answers(monkeypatch):
    monkeypatch.setattr(chacha20_module, "_openssl_tried", True)
    monkeypatch.setattr(chacha20_module, "_openssl", None)
    monkeypatch.setattr(chacha20_module, "_openssl_failure", "test")
    assert chacha20_backend() == "numpy"
    name, size = "CD_Item_Icon.XML", 4096
    key, nonce = derive_chacha20_key_iv(name)
    output = chacha20_xor(_payload(name, size), key, nonce)
    assert hashlib.sha256(output).hexdigest() == PINNED[(name, size)]
    with pytest.raises(OSError, match="unavailable"):
        chacha20_xor(b"x", key, nonce, backend="openssl")


def test_shipped_source_does_not_import_cryptography():
    import ast
    from pathlib import Path

    offenders = []
    roots = (Path("cdmw_app.py"), Path("cdmw"), Path("tools/placement_studio"), Path("tools/translation_studio"))
    for root in roots:
        for path in [root] if root.suffix == ".py" else sorted(root.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                if any(name.split(".", 1)[0] in {"cryptography", "cffi", "pycparser"} for name in names):
                    offenders.append(f"{path}:{node.lineno}")
    assert offenders == []
    requirements = Path("requirements.txt").read_text(encoding="utf-8").casefold()
    assert "cryptography" not in requirements


def test_matches_cryptography_while_it_is_installed():
    ciphers = pytest.importorskip("cryptography.hazmat.primitives.ciphers")
    rng = random.Random(50)
    for _ in range(60):
        key, nonce = rng.randbytes(32), rng.randbytes(16)
        data = rng.randbytes(rng.choice((0, 1, 64, 65, 1000, 70_000)))
        try:
            expected = ciphers.Cipher(ciphers.algorithms.ChaCha20(key, nonce), mode=None).encryptor().update(data)
        except ValueError as error:
            with pytest.raises(ValueError) as caught:
                chacha20_xor(data, key, nonce)
            assert str(caught.value) == str(error)
            continue
        assert chacha20_xor(data, key, nonce) == expected
