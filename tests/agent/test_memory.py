from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from computer_use_agent.memory import MemoryKind, MemoryStore, MemoryStoreError


NOW = datetime(2030, 1, 1, tzinfo=UTC)
FUTURE = "2030-02-01T00:00:00Z"


def test_explicit_memory_add_list_expiry_scope_and_delete(tmp_path: Path) -> None:
    store = MemoryStore((tmp_path / "memory.sqlite3").resolve())
    record = store.add(
        kind=MemoryKind.PREFERENCE,
        content="Prefer concise status summaries.",
        source="user_confirmed",
        scope="global",
        expires_at=FUTURE,
        confirmed=True,
        now=NOW,
    )
    expired = store.add(
        kind=MemoryKind.VERIFIED_PROCEDURE,
        content="Open the test application before inspection.",
        source="user_confirmed",
        scope="app:notepad",
        expires_at="2030-01-02T00:00:00Z",
        confirmed=True,
        now=NOW,
    )

    assert store.list(scope="global", now=NOW) == (record,)
    assert store.list(now=datetime(2030, 1, 3, tzinfo=UTC)) == (record,)
    assert {item.id for item in store.list(
        include_expired=True, now=datetime(2030, 1, 3, tzinfo=UTC)
    )} == {expired.id, record.id}
    assert store.delete(record.id) is True
    assert store.delete(record.id) is False


@pytest.mark.parametrize(
    "content",
    [
        "password: hunter2",
        "API key is abc",
        "Bearer abcdef",
        "click ref_123",
        "use window_9",
        "save this screenshot",
        "data:image/png;base64,AAAA",
        "iVBORw0KGgoAAAA",
        "contains\nnewline",
    ],
)
def test_memory_rejects_secrets_ui_references_images_and_control_text(
    tmp_path: Path, content: str
) -> None:
    store = MemoryStore((tmp_path / "memory.sqlite3").resolve())

    with pytest.raises(MemoryStoreError, match="MEMORY_CONTENT_REJECTED"):
        store.add(
            kind=MemoryKind.PREFERENCE,
            content=content,
            source="user_confirmed",
            scope="global",
            expires_at=FUTURE,
            confirmed=True,
            now=NOW,
        )

    assert not store.path.exists()


def test_memory_requires_confirmation_trusted_source_future_expiry_and_safe_scope(
    tmp_path: Path,
) -> None:
    store = MemoryStore((tmp_path / "memory.sqlite3").resolve())
    base = {
        "kind": MemoryKind.PREFERENCE,
        "content": "Prefer short summaries.",
        "source": "user_confirmed",
        "scope": "global",
        "expires_at": FUTURE,
        "confirmed": True,
        "now": NOW,
    }

    for changes in (
        {"confirmed": False},
        {"source": "model_inferred"},
        {"expires_at": "2029-01-01T00:00:00Z"},
        {"scope": "../escape"},
    ):
        with pytest.raises(MemoryStoreError):
            store.add(**(base | changes))

    assert not store.path.exists()
