"""The export store's bound, driven over a real directory the way builds, downloads and the sweep use it."""

import os
import random
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from yapit.gateway import audio_export
from yapit.gateway.audio_export import EXPORT_TTL_S, ExportFormat, ExportStore, NoRoom

MAX_BYTES = 100_000


def on_disk(directory: Path) -> dict[str, int]:
    return {p.name: p.stat().st_size for p in directory.iterdir()}


@pytest.mark.parametrize("seed", range(30))
def test_builds_downloads_and_sweeps_in_any_order_keep_the_files_within_the_bound_oldest_going_first(
    tmp_path, seed, monkeypatch
):
    rng = random.Random(seed)
    days_later = [0]
    clock = SimpleNamespace(time=lambda: time.time() + days_later[0] * (EXPORT_TTL_S + 1), monotonic=time.monotonic)
    monkeypatch.setattr(audio_export, "time", clock)
    store = ExportStore.open(tmp_path, MAX_BYTES)
    rooms: dict[str, int] = {}
    built: dict[str, float] = {}
    holds: list[tuple[str, object]] = []

    for step in range(400):
        before = on_disk(tmp_path)
        held = {name for name, _ in holds}
        op = rng.choice(
            ["reserve", "reserve", "reserve", "finish", "hold", "let go", "sweep", "a day", "other gateway"]
        )
        if op == "reserve":
            stored_keys = [name.split(".")[0] for name in before if not name.startswith(".")]
            key = rng.choice([*rooms, *stored_keys, f"k{step}"])  # a running build, a rebuild, or a new one
            total = rooms.get(key, 0) + rng.randint(1, 30_000)
            scratch = tmp_path / f".{key}.m4b.scratch"
            try:
                store.reserve(key, total, "user")
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
            built[path.name] = clock.time()
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
        elif op == "a day":
            days_later[0] += 1
            store.sweep()
        elif op == "other gateway":  # it built a file this store finds when someone asks for it
            path = tmp_path / f"o{step}.mp3"
            path.write_bytes(b"\0" * rng.randint(1, 30_000))
            built[path.name] = clock.time() - rng.uniform(0, 3600)
            os.utime(path, (built[path.name], built[path.name]))
            store.stored(f"o{step}", ExportFormat.mp3)

        after = on_disk(tmp_path)
        assert sum(after.values()) <= store.taken <= MAX_BYTES
        assert store.taken == sum(size for n, size in after.items() if not n.startswith(".")) + sum(rooms.values())
        assert all(name in after for name, _ in holds), "a file being downloaded was deleted"
        deleted = [n for n in before if n not in after and not n.startswith(".")]
        kept = [n for n in after if not n.startswith(".") and n not in held]
        if deleted and kept:
            assert max(built[n] for n in deleted) < min(built[n] for n in kept), "a newer file went first"


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


def built(store: ExportStore, key: str, size: int, user_id: str = "someone") -> Path:
    """A file of size bytes that a build user_id started left in the store."""
    store.reserve(key, size, user_id)
    path = store.path(key, ExportFormat.m4b)
    path.write_bytes(b"\0" * size)
    store.shelve(key, path)
    return path


def test_a_file_the_bound_deletes_before_its_day_is_over_is_recorded_and_one_whose_day_is_over_is_not(
    tmp_path, monkeypatch, metrics_events
):
    days_later = [0]
    clock = SimpleNamespace(time=lambda: time.time() + days_later[0] * (EXPORT_TTL_S + 1), monotonic=time.monotonic)
    monkeypatch.setattr(audio_export, "time", clock)
    store = ExportStore.open(tmp_path, MAX_BYTES)

    built(store, "a", 60_000)
    built(store, "b", 30_000)
    built(store, "c", 50_000, "flooder")  # pushes a out
    early = metrics_events()
    days_later[0] = 1
    built(store, "d", 80_000)  # pushes out b and c, their day over but not yet swept
    built(store, "e", 10_000)
    store.sweep()  # d's day is not over
    days_later[0] = 2
    store.sweep()  # deletes d and e

    assert [(e["event_type"], e["user_id"], e["data"]["bytes"]) for e in early] == [
        ("audio_export_deleted_early", "flooder", 60_000)
    ]
    assert metrics_events() == []


def test_a_file_another_gateway_already_deleted_is_not_recorded_as_deleted_early(tmp_path, metrics_events):
    store = ExportStore.open(tmp_path, MAX_BYTES)
    built(store, "a", 60_000).unlink()

    built(store, "b", 50_000)

    assert metrics_events() == []


def test_a_build_refused_for_lack_of_room_is_recorded_with_why(tmp_path, metrics_events):
    store = ExportStore.open(tmp_path, MAX_BYTES)
    release = store.hold(built(store, "held", 60_000))
    store.reserve("growing", 30_000, "grower")

    for key, total, user_id in [("huge", MAX_BYTES + 1, "picky"), ("new", 50_000, "late"), ("growing", 50_000, "grower")]:
        with pytest.raises(NoRoom):
            store.reserve(key, total, user_id)
    release()

    refused = [
        (e["event_type"], e["user_id"], e["data"]["reason"], e["data"]["bytes"], e["data"]["while_building"])
        for e in metrics_events()
    ]
    assert refused == [
        ("audio_export_refused", "picky", "larger_than_bound", MAX_BYTES + 1, False),
        ("audio_export_refused", "late", "no_room", 50_000, False),
        ("audio_export_refused", "grower", "no_room", 50_000, True),
    ]
