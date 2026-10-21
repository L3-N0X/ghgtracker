import pytest

from ghgtracker.storage import LocalStore


def test_local_store_roundtrip(tmp_path) -> None:
    store = LocalStore(tmp_path / "snapshots")
    store.prepare()
    store.put("alice/1/a.jpg", b"one")
    store.put("alice/2/b.jpg", b"two")
    store.put("bob/1/c.jpg", b"three")

    assert store.get("alice/1/a.jpg") == b"one"
    assert store.get("alice/1/missing.jpg") is None

    store.delete("alice/1/a.jpg")
    assert store.get("alice/1/a.jpg") is None
    store.delete("alice/1/a.jpg")  # deleting twice is fine

    store.delete_prefix("alice")
    assert store.get("alice/2/b.jpg") is None
    assert store.get("bob/1/c.jpg") == b"three"


def test_local_store_rejects_path_traversal(tmp_path) -> None:
    store = LocalStore(tmp_path / "snapshots")
    store.prepare()
    (tmp_path / "secret.txt").write_text("secret")
    with pytest.raises(ValueError):
        store.get("../secret.txt")


@pytest.mark.parametrize("key", ["", "../x", "a/../../x", "/abs", "a//b", "a\\b"])
def test_check_key_rejects_unsafe_keys(key: str) -> None:
    from ghgtracker.storage import check_key

    with pytest.raises(ValueError):
        check_key(key)
