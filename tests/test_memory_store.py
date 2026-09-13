"""Memory store tests — the critical property is user scoping: one user's
memory can never surface for another. Runs against the live Postgres + Chroma."""
import uuid

import pytest

from app.memory.models import MemoryItem, MemoryKind
from app.memory.store import PostgresChromaMemoryStore, PostgresShortTermMemory
from app.config import get_settings


@pytest.fixture(scope="module")
def store():
    s = get_settings()
    st = PostgresChromaMemoryStore(s.app_db_url, str(s.vector_db_path))
    yield st
    # cleanup test users' memory
    for uid in ("USR001", "USR002"):
        pass  # only test-created ids are removed in tests themselves


def _item(user_id: str, kind: MemoryKind, content: str) -> MemoryItem:
    return MemoryItem(user_id=user_id, kind=kind, content=content)


def test_add_list_delete_roundtrip(store):
    item = _item("USR001", MemoryKind.SEMANTIC, f"test-fact-{uuid.uuid4().hex[:6]}")
    store.add(item)
    assert any(m.memory_id == item.memory_id for m in store.list_for_user("USR001"))
    assert store.delete("USR001", item.memory_id) == 1
    assert not any(m.memory_id == item.memory_id for m in store.list_for_user("USR001"))


def test_episodic_similarity_is_user_scoped(store):
    marker = uuid.uuid4().hex[:8]
    mine = _item("USR001", MemoryKind.EPISODIC, f"Discussed claim CLM-TEST-{marker} delay and next steps")
    theirs = _item("USR002", MemoryKind.EPISODIC, f"Discussed claim CLM-TEST-{marker} delay and next steps")
    store.add(mine)
    store.add(theirs)
    try:
        hits_1 = store.similar_episodes("USR001", f"claim CLM-TEST-{marker}")
        assert any(h.memory_id == mine.memory_id for h in hits_1)
        assert all(h.user_id == "USR001" for h in hits_1)  # never the other user's
        hits_2 = store.similar_episodes("USR002", f"claim CLM-TEST-{marker}")
        assert all(h.user_id == "USR002" for h in hits_2)
    finally:
        store.delete("USR001", mine.memory_id)
        store.delete("USR002", theirs.memory_id)


def test_delete_all_clears_user_only(store):
    a = _item("USR001", MemoryKind.SEMANTIC, "erase-me-a")
    b = _item("USR002", MemoryKind.SEMANTIC, "keep-me-b")
    store.add(a)
    store.add(b)
    try:
        before_b = len(store.list_for_user("USR002"))
        assert store.delete("USR001") >= 1
        assert len(store.list_for_user("USR001")) == 0
        assert len(store.list_for_user("USR002")) == before_b  # untouched
    finally:
        store.delete("USR002", b.memory_id)


def test_scratch_roundtrip():
    stm = PostgresShortTermMemory(get_settings().app_db_url)
    cid = f"scratch-test-{uuid.uuid4().hex[:6]}"
    assert stm.get(cid) == {}
    stm.set(cid, {"pending_action": "pay-premium", "step": 2})
    assert stm.get(cid)["step"] == 2
    stm.set(cid, {}, ttl_s=0)  # immediate expiry
    assert stm.get(cid) == {}
