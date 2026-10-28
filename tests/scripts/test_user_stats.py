"""`scripts/user_stats.py` shows who signed up, how, and whether they came
back. These run it against a seeded Postgres and check
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

Last sign-in: alice 10-20 23:30 at UTC-2 = 10-21, carol 10-27, dave 09-15,
frank 10-29 (after the as-of day, so blank); bob and erin never signed in.

frank has a long email and a long name, which no table may cut short.

    anon-1: doc 10-25, TTS 10-27.  anon-2: doc 09-01.  A deleted account's doc 10-27 counts for nobody.
"""

import csv
import io
import json
import os
import re
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
FRANK_DOMAIN = "physics.example-university.org"
EMAILS = [f"{n}@example.com" for n in ("alice", "bob", "carol", "dave", "erin")] + [f"frank@{FRANK_DOMAIN}"]


def at(stamp: str) -> datetime:
    """A bare day is noon UTC on it."""
    return datetime.fromisoformat(stamp if "T" in stamp else stamp + "T12:00:00+00:00")


def seed(session: Session) -> None:
    plans = {tier: Plan(tier=tier, name=tier.value) for tier in (PlanTier.free, PlanTier.basic, PlanTier.plus)}
    session.add_all(plans.values())
    session.flush()

    def user(
        name: str,
        signed_up: str,
        providers: tuple[str, ...] = (),
        last_sign_in: str | None = None,
        domain: str = "example.com",
        full_name: str | None = None,
    ) -> str:
        uid = f"user-{name}"
        session.add(
            UserAccount(
                id=uid,
                email=f"{name}@{domain}",
                name=full_name or name.title(),
                created=at(signed_up),
                last_sign_in=last_sign_in and at(last_sign_in),
            )
        )
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

    alice = user("alice", "2026-08-03", ("google",), last_sign_in="2026-10-20T23:30:00-02:00")
    doc(alice, "2026-08-03")
    doc(alice, "2026-09-10")
    tts(alice, "2026-10-20")
    subscribe(alice, PlanTier.plus, SubscriptionStatus.active)

    bob = user("bob", "2026-08-20", ("github",))
    doc(bob, "2026-09-28T23:30:00-02:00")

    carol = user("carol", "2026-09-05", ("google", "github"), last_sign_in="2026-10-27")
    doc(carol, "2026-09-05")
    doc(carol, "2026-09-06")
    session_used(carol, AuthSessionKind.browser, "2026-10-27")
    session_used(carol, AuthSessionKind.api, "2026-10-01")
    subscribe(carol, PlanTier.basic, SubscriptionStatus.trialing)

    dave = user("dave", "2026-09-15", last_sign_in="2026-09-15")
    tts(dave, "2026-09-18")
    subscribe(dave, PlanTier.basic, SubscriptionStatus.past_due)

    erin = user("erin", "2026-10-26")
    doc(erin, "2026-10-26")
    subscribe(erin, PlanTier.free, SubscriptionStatus.active)

    user(
        "frank",
        "2026-10-27",
        ("google",),
        last_sign_in="2026-10-29",
        domain=FRANK_DOMAIN,
        full_name="Frank Alexander Mustermann",
    )
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

    assert {
        name: (r["last_active"], r["active_days_30"], r["documents"], r["plan"], r["status"])
        for name, r in rows.items()
    } == {
        "alice": ("2026-10-20", 1, 2, "plus", "active"),
        "bob": ("2026-09-29", 1, 1, "free", ""),
        "carol": ("2026-10-27", 1, 2, "basic", "trialing"),
        "dave": ("2026-09-18", 0, 0, "basic", "past_due"),
        "erin": ("2026-10-26", 1, 1, "free", "active"),
        "frank": ("2026-10-27", 1, 0, "free", ""),
    }
    assert rows["carol"]["methods"] == ["github", "google"]
    assert rows["carol"]["signed_up"] == "2026-09-05"
    assert {name: r["last_sign_in"] for name, r in rows.items()} == {
        "alice": "2026-10-21",
        "bob": None,
        "carol": "2026-10-27",
        "dave": "2026-09-15",
        "erin": None,
        "frank": None,
    }


@pytest.mark.parametrize(
    "args,names",
    [
        ((), ["frank", "erin", "dave", "carol", "bob", "alice"]),
        (("--sort", "last-sign-in"), ["carol", "alice", "dave", "bob", "erin", "frank"]),
        (("--sort", "last-active"), ["carol", "frank", "erin", "alice", "bob", "dave"]),
        (("--sort", "documents", "--reverse"), ["dave", "frank", "bob", "erin", "alice", "carol"]),
        (("--sort", "email", "--limit", "2"), ["alice", "bob"]),
        (("--sort", "name", "--reverse"), ["frank", "erin", "dave", "carol", "bob", "alice"]),
        (("--sort", "methods"), ["dave", "erin", "bob", "carol", "alice", "frank"]),
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
        ("overview", ["github + google", "1"]),
        ("retention", ["2026-08", "2", "2 100%", "2 100%", "1  50%"]),
    ],
)
def test_tables_fit_80_columns(database_url: str, command: str, whole_row: list[str]) -> None:
    done = user_stats("--database-url", database_url, "--as-of", AS_OF, command, env={**os.environ, "COLUMNS": "80"})
    assert done.returncode == 0, done.stderr
    assert re.search(r"\s+".join(map(re.escape, whole_row)), done.stdout)
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
        f'if grep -q useraccount {calls}/$n.sql; then echo "id,email,name,signed_up,last_sign_in,providers,plan,status,documents";'
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


@pytest.mark.parametrize("wide", [False, True])
def test_user_table_never_cuts_an_email(database_url: str, wide: bool) -> None:
    """At 80 columns frank's 36-character email does not fit beside the other
    columns, so the table runs wider than the terminal rather than cut it.
    """
    done = user_stats(
        "--database-url",
        database_url,
        "--as-of",
        AS_OF,
        "users",
        *(["--wide"] if wide else []),
        env={**os.environ, "COLUMNS": "80"},
    )
    assert done.returncode == 0, done.stderr
    for email in EMAILS:
        assert re.search(rf"(^|\s){re.escape(email)}\s", done.stdout, re.MULTILINE), email
    # name is the column that gives way: cut short with --wide, absent without.
    assert "Frank Alexander Mustermann" not in done.stdout
    assert ("Frank…" in done.stdout) == wide
    assert re.search(
        r"dave@example\.com\s+(Dave\s+)?26-09-15\s+26-09-15\s+email\s+40d\s+0\s+0\s+basic past due", done.stdout
    )


def test_user_table_of_typical_emails_fits_80_columns(database_url: str) -> None:
    done = user_stats(
        "--database-url",
        database_url,
        "--as-of",
        AS_OF,
        "users",
        "--method",
        "github",
        env={**os.environ, "COLUMNS": "80"},
    )
    assert done.returncode == 0, done.stderr
    assert re.search(r"bob@example\.com\s+26-08-20\s+GH\s+29d\s+1\s+1\s+free", done.stdout)
    assert max(len(line) for line in done.stdout.splitlines()) <= 80


def test_users_csv(database_url: str) -> None:
    done = user_stats("--database-url", database_url, "--as-of", AS_OF, "users", "--csv", "--sort", "email")
    assert done.returncode == 0, done.stderr
    rows = list(csv.reader(io.StringIO(done.stdout)))
    assert rows[0] == [
        "email",
        "name",
        "signed up",
        "last sign-in",
        "via",
        "last active",
        "days/30",
        "docs",
        "plan",
        "status",
    ]
    assert rows[1] == [
        "alice@example.com",
        "Alice",
        "2026-08-03",
        "2026-10-21",
        "google",
        "2026-10-20",
        "1",
        "2",
        "plus",
        "active",
    ]
    assert rows[3] == [
        "carol@example.com",
        "Carol",
        "2026-09-05",
        "2026-10-27",
        "github+google",
        "2026-10-27",
        "1",
        "2",
        "basic",
        "trialing",
    ]
    assert rows[6][:5] == [f"frank@{FRANK_DOMAIN}", "Frank Alexander Mustermann", "2026-10-27", "", "google"]
    assert len(rows) == 7
