"""The export store's bound, driven over a real directory the way builds, downloads and the sweep use it."""

import os
import random
import time
from pathlib import Path

import pytest

from yapit.gateway.audio_export import ExportFormat, ExportStore, NoRoom

MAX_BYTES = 100_000


def on_disk(directory: Path) -> dict[str, int]:
    return {p.name: p.stat().st_size for p in directory.iterdir()}


@pytest.mark.parametrize("seed", range(30))
def test_builds_downloads_and_sweeps_in_any_order_keep_the_files_within_the_bound_oldest_going_first(tmp_path, seed):
    rng = random.Random(seed)
    store = ExportStore.open(tmp_path, MAX_BYTES)
    rooms: dict[str, int] = {}
    shelved: list[str] = []
    holds: list[tuple[str, object]] = []

    for step in range(400):
        before = on_disk(tmp_path)
        held = {name for name, _ in holds}
        op = rng.choice(["reserve", "reserve", "reserve", "finish", "hold", "let go", "sweep"])
        if op == "reserve":
            stored_keys = [name.split(".")[0] for name in before if not name.startswith(".")]
            key = rng.choice([*rooms, *stored_keys, f"k{step}"])  # a running build, a rebuild, or a new one
            total = rooms.get(key, 0) + rng.randint(1, 30_000)
            scratch = tmp_path / f".{key}.m4b.scratch"
            try:
                store.reserve(key, total)
            except NoRoom:
                assert on_disk(tmp_path) == before, "a refused build deleted files"
                scratch.unlink(missing_ok=True)
                store.release(key)
                rooms.pop(key, None)
                continue
            rooms[key] = total
            scratch.write_bytes(b"\0" * rng.randint(total // 2, total))
        elif op == "finish" and rooms:
            key = rng.choice(list(rooms))
            scratch, path = tmp_path / f".{key}.m4b.scratch", store.path(key, ExportFormat.m4b)
            os.replace(scratch, path)
            store.shelve(key, path)
            store.release(key)
            del rooms[key]
            shelved.append(path.name)
        elif op == "hold":
            stored = [name for name in before if not name.startswith(".")]
            if stored:
                name = rng.choice(stored)
                holds.append((name, store.hold(tmp_path / name)))
        elif op == "let go" and holds:
            _, release = holds.pop(rng.randrange(len(holds)))
            release()
        elif op == "sweep":
            store.sweep()

        after = on_disk(tmp_path)
        assert sum(after.values()) <= store.taken <= MAX_BYTES
        assert store.taken == sum(size for n, size in after.items() if not n.startswith(".")) + sum(rooms.values())
        assert all(name in after for name, _ in holds), "a file being downloaded was deleted"
        deleted = [n for n in before if n not in after and not n.startswith(".")]
        kept = [n for n in after if not n.startswith(".") and n not in held]
        if deleted and kept:
            order = {name: i for i, name in enumerate(shelved)}  # the last shelving of each name
            assert max(order[n] for n in deleted) < min(order[n] for n in kept), "a newer file went first"


def test_a_build_larger_than_the_bound_is_refused_saying_so(tmp_path):
    store = ExportStore.open(tmp_path, 3 * 2**20)

    with pytest.raises(NoRoom, match="too large for the 3 MB"):
        store.reserve("big", 3 * 2**20 + 1)


def test_a_restart_counts_what_the_directory_holds_and_deletes_scratch_no_build_writes(tmp_path):
    now = time.time()
    for name, size, age in [
        ("a.m4b", 30_000, 3 * 3600),
        ("b.m4b", 30_000, 2 * 3600),
        ("c.mp3", 30_000, 3600),
        (".d.m4b.1.encoded", 20_000, 2 * 3600),  # a build that died with the gateway before
        (".e.m4b.2.encoded", 20_000, 0),  # a build the other gateway runs during a deploy
    ]:
        (tmp_path / name).write_bytes(b"\0" * size)
        os.utime(tmp_path / name, (now - age, now - age))

    store = ExportStore.open(tmp_path, 85_000)

    assert sorted(on_disk(tmp_path)) == [".e.m4b.2.encoded", "b.m4b", "c.mp3"]
    assert store.taken == 80_000
    assert store.stored("b", ExportFormat.m4b) == tmp_path / "b.m4b"


def test_a_file_another_gateway_built_or_deleted_is_counted_as_it_stands(tmp_path):
    store = ExportStore.open(tmp_path, MAX_BYTES)

    (tmp_path / "f.mp3").write_bytes(b"\0" * 40_000)
    found = store.stored("f", ExportFormat.mp3)
    taken_with_it = store.taken
    (tmp_path / "f.mp3").unlink()
    gone = store.stored("f", ExportFormat.mp3)

    assert found == tmp_path / "f.mp3" and taken_with_it == 40_000
    assert gone is None and store.taken == 0
