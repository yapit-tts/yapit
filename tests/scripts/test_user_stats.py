"""`scripts/user_stats.py` replaces Stack Auth's dashboard: who signed up, how,
and whether they came back. These run it against a seeded Postgres and check
its numbers against a hand count of the seed, as of 2026-10-28 (a Wednesday;
its week starts Monday 2026-10-26).

The seed, with each user's active days:

    alice  signed up 2026-08-03  google         docs 08-03, 09-10; TTS 10-20      plus, active
    bob    signed up 2026-08-20  github         doc 09-28 23:30 at UTC-2 = 09-29  no subscription
    carol  signed up 2026-09-05  github+google  docs 09-05, 09-06; browser 10-27  basic, trialing
                                                (an API token used 10-01 is not activity)
    dave   signed up 2026-09-15  email only     TTS 09-18                         basic, past_due
    erin   signed up 2026-10-26  email only     doc 10-26                         free, active
    frank  signed up 2026-10-27  google         nothing                           no subscription
    gina   signed up 2026-11-02  google                                           after the as-of day

    anon-1: doc 10-25, TTS 10-27.  anon-2: doc 09-01.  A deleted account's doc 10-27 counts for nobody.
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine
from testcontainers.postgres import PostgresContainer

from yapit.gateway.domain_models import (
    AuthSession,
    AuthSessionKind,
    Document,
    OAuthIdentity,
    Plan,
    PlanTier,
    SubscriptionStatus,
    UsageLog,
    UsageType,
    UserAccount,
    UserSubscription,
)

USER_STATS = Path(__file__).resolve().parents[2] / "scripts" / "user_stats.py"
AS_OF = "2026-10-28"


def at(stamp: str) -> datetime:
    """A bare day is noon UTC on it."""
    return datetime.fromisoformat(stamp if "T" in stamp else stamp + "T12:00:00+00:00")


def seed(session: Session) -> None:
    plans = {tier: Plan(tier=tier, name=tier.value) for tier in (PlanTier.free, PlanTier.basic, PlanTier.plus)}
    session.add_all(plans.values())
    session.flush()

    def user(name: str, signed_up: str, providers: tuple[str, ...] = ()) -> str:
        uid = f"user-{name}"
        session.add(UserAccount(id=uid, email=f"{name}@example.com", name=name.title(), created=at(signed_up)))
        session.flush()
        for p in providers:
            session.add(OAuthIdentity(provider=p, provider_account_id=f"{p}-{name}", user_id=uid))
        return uid

    def doc(uid: str, created: str) -> None:
        session.add(Document(user_id=uid, original_text="x", structured_content="x", created=at(created)))

    def tts(uid: str, created: str) -> None:
        session.add(UsageLog(user_id=uid, type=UsageType.server_kokoro, amount=100, created=at(created)))

    def session_used(uid: str, kind: AuthSessionKind, last_used: str) -> None:
        session.add(AuthSession(token_hash=uuid.uuid4().hex, user_id=uid, kind=kind, last_used=at(last_used)))

    def subscribe(uid: str, tier: PlanTier, status: SubscriptionStatus) -> None:
        session.add(
            UserSubscription(
                user_id=uid,
                plan_id=plans[tier].id,
                status=status,
                current_period_start=at("2026-10-01"),
                current_period_end=at("2026-11-01"),
            )
        )

    alice = user("alice", "2026-08-03", ("google",))
    doc(alice, "2026-08-03")
    doc(alice, "2026-09-10")
    tts(alice, "2026-10-20")
    subscribe(alice, PlanTier.plus, SubscriptionStatus.active)

    bob = user("bob", "2026-08-20", ("github",))
    doc(bob, "2026-09-28T23:30:00-02:00")

    carol = user("carol", "2026-09-05", ("google", "github"))
    doc(carol, "2026-09-05")
    doc(carol, "2026-09-06")
    session_used(carol, AuthSessionKind.browser, "2026-10-27")
    session_used(carol, AuthSessionKind.api, "2026-10-01")
    subscribe(carol, PlanTier.basic, SubscriptionStatus.trialing)

    dave = user("dave", "2026-09-15")
    tts(dave, "2026-09-18")
    subscribe(dave, PlanTier.basic, SubscriptionStatus.past_due)

    erin = user("erin", "2026-10-26")
    doc(erin, "2026-10-26")
    subscribe(erin, PlanTier.free, SubscriptionStatus.active)

    user("frank", "2026-10-27", ("google",))
    user("gina", "2026-11-02", ("google",))

    doc("anon-1", "2026-10-25")
    tts("anon-1", "2026-10-27")
    doc("anon-2", "2026-09-01")
    doc("user-deleted", "2026-10-27")
    session.commit()


@pytest.fixture(scope="module")
def database_url():
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        engine = create_engine(postgres.get_connection_url())
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            seed(session)
        engine.dispose()
        yield postgres.get_connection_url()


def user_stats(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(USER_STATS), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )


def stats_json(database_url: str, *args: str):
    done = user_stats("--database-url", database_url, "--as-of", AS_OF, "--json", *args)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_overview_counts_the_seed(database_url: str) -> None:
    data = stats_json(database_url, "overview")

    assert data["users"] == 6
    weekly = {r["week"]: r["signups"] for r in data["signups_weekly"]}
    assert len(weekly) == 12
    assert {w: n for w, n in weekly.items() if n} == {
        "2026-08-17": 1,
        "2026-08-31": 1,
        "2026-09-14": 1,
        "2026-10-26": 2,
    }
    monthly = {r["month"]: r["signups"] for r in data["signups_monthly"]}
    assert next(iter(monthly)) == "2025-11"
    assert {m: n for m, n in monthly.items() if n} == {"2026-08": 2, "2026-09": 2, "2026-10": 2}
    assert {r["method"]: r["users"] for r in data["methods"]} == {
        "google": 2,
        "github": 1,
        "github + google": 1,
        "email only": 2,
    }
    assert data["active"] == {"7": 3, "30": 5, "90": 6}
    assert data["guests_active"] == {"7": 1, "30": 1, "90": 2}
    assert data["paying"] == {"total": 2, "by_plan": {"plus": 1, "basic": 1}}
    assert data["trialing"] == 1


def test_user_table_counts_the_seed(database_url: str) -> None:
    rows = {r["email"].split("@")[0]: r for r in stats_json(database_url, "users")}

    assert {name: (r["last_active"], r["active_days_30"], r["documents"], r["plan"]) for name, r in rows.items()} == {
        "alice": ("2026-10-20", 1, 2, "plus"),
        "bob": ("2026-09-29", 1, 1, "free"),
        "carol": ("2026-10-27", 1, 2, "basic trialing"),
        "dave": ("2026-09-18", 0, 0, "basic past due"),
        "erin": ("2026-10-26", 1, 1, "free"),
        "frank": ("2026-10-27", 1, 0, "free"),
    }
    assert rows["carol"]["methods"] == ["github", "google"]
    assert rows["carol"]["signed_up"] == "2026-09-05"


@pytest.mark.parametrize(
    "args,names",
    [
        ((), ["frank", "erin", "dave", "carol", "bob", "alice"]),
        (("--sort", "last-active"), ["carol", "frank", "erin", "alice", "bob", "dave"]),
        (("--sort", "documents", "--reverse"), ["dave", "frank", "bob", "erin", "alice", "carol"]),
        (("--sort", "email", "--limit", "2"), ["alice", "bob"]),
        (("--since", "2026-09-06"), ["frank", "erin", "dave"]),
        (("--method", "github"), ["carol", "bob"]),
        (("--method", "email-only"), ["erin", "dave"]),
    ],
)
def test_user_table_sorts_and_filters(database_url: str, args: tuple[str, ...], names: list[str]) -> None:
    rows = stats_json(database_url, "users", *args)
    assert [r["email"].split("@")[0] for r in rows] == names


def test_retention_counts_the_seed(database_url: str) -> None:
    data = stats_json(database_url, "retention")

    cohorts = {r["month"]: (r["signups"], r["active"]) for r in data["cohorts"]}
    assert cohorts["2026-08"] == (2, [2, 2, 1])
    assert cohorts["2026-09"] == (2, [2, 1])
    assert cohorts["2026-10"] == (2, [2])
    assert cohorts["2026-01"] == (0, [0] * 6)
    # alice, bob and carol came back a week or more after their first day; dave
    # only 3 days after; erin and frank signed up under a week ago.
    assert data["came_back"] == {"eligible": 4, "came_back": 3}


@pytest.mark.parametrize(
    "command,whole_row",
    [
        # Rich fits a wide table by squeezing columns to an ellipsis or dropping
        # them, so a row has to come out whole, not just short enough.
        ("overview", "github + google   1"),
        ("users", "dave@example.com   Dave   2026-09-15  email     40d     0     0  basic past due"),
        ("retention", "2026-08       2   2 100%   2 100%   1  50%"),
    ],
)
def test_tables_fit_80_columns(database_url: str, command: str, whole_row: str) -> None:
    done = user_stats("--database-url", database_url, "--as-of", AS_OF, command, env={**os.environ, "COLUMNS": "80"})
    assert done.returncode == 0, done.stderr
    assert whole_row in done.stdout
    assert max(len(line) for line in done.stdout.splitlines()) <= 80


def test_prod_reads_are_read_only_copies(tmp_path: Path) -> None:
    """Against prod every query goes over ssh to psql with read-only transactions,
    as a COPY of a SELECT.
    """
    calls = tmp_path / "calls"
    calls.mkdir()
    fake_ssh = tmp_path / "ssh"
    fake_ssh.write_text(
        "#!/bin/bash\n"
        f'n=$(ls {calls} | wc -l); printf "%s\\n" "$@" > {calls}/$n.args; cat > {calls}/$n.sql\n'
        f'if grep -q useraccount {calls}/$n.sql; then echo "id,email,name,signed_up,providers,plan,status,documents";'
        ' else echo "user_id,day"; fi\n'
    )
    fake_ssh.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "VPS_HOST": "prod-host"}

    done = user_stats("--json", "overview", env=env)

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["users"] == 0
    args = sorted(calls.glob("*.args"))
    assert len(args) == 2
    for a in args:
        host, remote = a.read_text().splitlines()
        assert host == "prod-host"
        assert "PGOPTIONS='-c default_transaction_read_only=on'" in remote
        sql = a.with_suffix(".sql").read_text()
        assert sql.startswith("COPY (SELECT")
