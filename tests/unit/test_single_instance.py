import uuid

from opendm.ipc.single_instance import InstanceLock


def test_only_one_holder_at_a_time() -> None:
    name = f"opendm-test-{uuid.uuid4().hex[:8]}"
    first, second = InstanceLock(name), InstanceLock(name)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_release_is_idempotent() -> None:
    lock = InstanceLock(f"opendm-test-{uuid.uuid4().hex[:8]}")
    lock.release()
    assert lock.acquire()
    lock.release()
    lock.release()


def test_different_names_do_not_conflict() -> None:
    a = InstanceLock(f"opendm-a-{uuid.uuid4().hex[:8]}")
    b = InstanceLock(f"opendm-b-{uuid.uuid4().hex[:8]}")
    assert a.acquire() and b.acquire()
    a.release()
    b.release()
