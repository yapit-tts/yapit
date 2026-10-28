#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = ["tyro", "rich", "psycopg[binary]"]
# ///
"""Who signs up, how, and whether they come back.

Reads prod Postgres read-only: ssh to $VPS_HOST, then psql inside the postgres
container with default_transaction_read_only=on. --database-url reads a local
database instead (the dev stack, a test database).

A user is a signed-up account; guests (anon-…) only ever appear as one
aggregate line. A user is active on a day when they signed up that day, or
created a document, used TTS or OCR (usagelog), or last used a browser session
on it. Days are UTC. A session keeps only its latest use, so a day of reading
that created no document and no usage counts only while it is that session's
latest; with --as-of in the past, sessions used since then add nothing.

Examples:
    make user-stats
    make user-stats ARGS="users --sort last-active --since 2026-09-01"
    uv run scripts/user_stats.py --database-url postgresql://yapit:yapit@localhost:5432/yapit retention
    uv run scripts/user_stats.py overview --json | jq .methods
"""

from __future__ import annotations

import csv
import io
import json
import os
import shlex
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

import tyro
from rich import box
from rich.console import Console
from rich.table import Table


@dataclass(frozen=True)
class Overview:
    """Sign-ups per week and month, the sign-in method mix, active users, paying users.

    JSON schema (--json):

        {"as_of": "YYYY-MM-DD", "users": int,
         "signups_weekly": [{"week": "YYYY-MM-DD", "signups": int}],
         "signups_monthly": [{"month": "YYYY-MM", "signups": int}],
         "methods": [{"method": "str", "users": int}],
         "active": {"7": int, "30": int, "90": int},
         "guests_active": {"7": int, "30": int, "90": int},
         "paying": {"total": int, "by_plan": {"tier": int}}, "trialing": int}
    """

    weeks: int = 12
    """Weeks of sign-ups to show, the current one included."""
    months: int = 12
    """Months of sign-ups to show, the current one included."""


SortKey = Literal["signed-up", "last-active", "active-days", "documents", "email", "name", "methods", "plan"]
TEXT_SORTS = ("email", "name", "methods", "plan")


@dataclass(frozen=True)
class Users:
    """One row per user: email, name, signed up, methods, last active, active days in the last 30, documents, plan.

    JSON schema (--json):

        [{"email": "str", "name": "str", "signed_up": "YYYY-MM-DD", "methods": ["google|github"],
          "last_active": "YYYY-MM-DD", "last_active_days_ago": int, "active_days_30": int, "documents": int, "plan": "str"}]
    """

    sort: SortKey = "signed-up"
    """Column to sort by. Dates and counts sort newest or largest first, text A to Z."""
    reverse: bool = False
    """Reverse the sort order."""
    since: date | None = None
    """Only users who signed up on or after this day (YYYY-MM-DD)."""
    method: Literal["google", "github", "email-only"] | None = None
    """Only users linked to this provider, or with none linked."""
    limit: int | None = None
    """Show at most this many rows."""


@dataclass(frozen=True)
class Retention:
    """Monthly sign-up cohorts, active in each month after; and the share who came back a week or more after their first day.

    Cohort cells count the cohort's users active at least once in that month.
    Users count toward "came back" once their first day is 7 or more days
    before --as-of.

    JSON schema (--json):

        {"as_of": "YYYY-MM-DD",
         "cohorts": [{"month": "YYYY-MM", "signups": int, "active": [int]}],
         "came_back": {"eligible": int, "came_back": int}}

    active[k] is the count active in month M+k, up to the month of --as-of.
    """

    cohorts: int = 12
    """Sign-up months to show, the current one included."""
    months: int = 6
    """Months after sign-up to show, M+0 included."""


Command = (
    Annotated[Overview, tyro.conf.subcommand(name="overview", prefix_name=False)]
    | Annotated[Users, tyro.conf.subcommand(name="users", prefix_name=False)]
    | Annotated[Retention, tyro.conf.subcommand(name="retention", prefix_name=False)]
)


@dataclass(frozen=True)
class Cli:
    command: Command
    database_url: Annotated[str | None, tyro.conf.arg(metavar="URL")] = None
    """Read this database instead of prod, e.g. postgresql://yapit:yapit@localhost:5432/yapit."""
    as_of: date = field(default_factory=lambda: datetime.now(UTC).date())
    """Count as if today were this day (YYYY-MM-DD), leaving out later sign-ups and activity."""
    json: bool = False
    """Print the numbers as JSON instead of tables."""


def main(cli: Cli) -> None:
    fetch = local_fetch(cli.database_url) if cli.database_url else prod_fetch(vps_host())
    people = load(fetch, cli.as_of)
    match cli.command:
        case Overview() as cmd:
            data = overview(people, cli.as_of, cmd.weeks, cmd.months)
            render = render_overview
        case Users() as cmd:
            data = user_rows(people, cli.as_of, cmd)
            render = render_users
        case Retention() as cmd:
            data = retention(people, cli.as_of, cmd.cohorts, cmd.months)
            render = render_retention
    if cli.json:
        print(json.dumps(data, indent=2))
    else:
        render(Console(), data)


# --- The numbers ---------------------------------------------------------------

WINDOWS = (7, 30, 90)


@dataclass(frozen=True)
class User:
    email: str
    name: str
    signed_up: date
    providers: tuple[str, ...]
    plan: str
    status: str
    documents: int
    active_days: frozenset[date]


@dataclass(frozen=True)
class People:
    users: list[User]
    guest_days: dict[str, frozenset[date]]


def method_label(providers: tuple[str, ...]) -> str:
    return " + ".join(providers) if providers else "email only"


def active_within(days: Iterable[date], as_of: date, window: int) -> bool:
    return any(as_of - timedelta(days=window) < d <= as_of for d in days)


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_back(as_of: date, n: int) -> list[str]:
    """The n months ending with as_of's, oldest first."""
    index = as_of.year * 12 + as_of.month - 1
    return [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(index - n + 1, index + 1)]


def month_offset(start: str, end: str) -> int:
    (y0, m0), (y1, m1) = (map(int, start.split("-")), map(int, end.split("-")))
    return (y1 - y0) * 12 + m1 - m0


def is_paying(user: User) -> bool:
    return user.plan not in ("", "free") and user.status in ("active", "past_due")


def overview(people: People, as_of: date, weeks: int, months: int) -> dict:
    users = people.users
    this_week = as_of - timedelta(days=as_of.weekday())
    week_starts = [this_week - timedelta(weeks=k) for k in reversed(range(weeks))]
    by_week = Counter(u.signed_up - timedelta(days=u.signed_up.weekday()) for u in users)
    by_month = Counter(month_key(u.signed_up) for u in users)
    paying = Counter(u.plan for u in users if is_paying(u))
    return {
        "as_of": as_of.isoformat(),
        "users": len(users),
        "signups_weekly": [{"week": w.isoformat(), "signups": by_week[w]} for w in week_starts],
        "signups_monthly": [{"month": m, "signups": by_month[m]} for m in months_back(as_of, months)],
        "methods": [
            {"method": method, "users": n}
            for method, n in Counter(method_label(u.providers) for u in users).most_common()
        ],
        "active": {str(w): sum(active_within(u.active_days, as_of, w) for u in users) for w in WINDOWS},
        "guests_active": {
            str(w): sum(active_within(days, as_of, w) for days in people.guest_days.values()) for w in WINDOWS
        },
        "paying": {"total": paying.total(), "by_plan": dict(paying.most_common())},
        "trialing": sum(u.status == "trialing" for u in users),
    }


def plan_label(user: User) -> str:
    plan = user.plan or "free"
    return plan if user.status in ("", "active") else f"{plan} {user.status.replace('_', ' ')}"


def user_rows(people: People, as_of: date, cmd: Users) -> list[dict]:
    users = [
        u
        for u in people.users
        if (cmd.since is None or u.signed_up >= cmd.since)
        and (cmd.method is None or (cmd.method == "email-only" and not u.providers) or cmd.method in u.providers)
    ]
    rows = [
        {
            "email": u.email,
            "name": u.name,
            "signed_up": u.signed_up.isoformat(),
            "methods": list(u.providers),
            "last_active": max(u.active_days).isoformat(),
            "last_active_days_ago": (as_of - max(u.active_days)).days,
            "active_days_30": sum(as_of - timedelta(days=30) < d <= as_of for d in u.active_days),
            "documents": u.documents,
            "plan": plan_label(u),
        }
        for u in users
    ]
    rows.sort(key=lambda r: r["email"])
    rows.sort(key=SORT_KEYS[cmd.sort], reverse=(cmd.sort not in TEXT_SORTS) != cmd.reverse)
    return rows[: cmd.limit]


SORT_KEYS = {
    "signed-up": lambda r: r["signed_up"],
    "last-active": lambda r: r["last_active"],
    "active-days": lambda r: r["active_days_30"],
    "documents": lambda r: r["documents"],
    "email": lambda r: r["email"],
    "name": lambda r: r["name"],
    "methods": lambda r: method_label(tuple(r["methods"])),
    "plan": lambda r: r["plan"],
}


def retention(people: People, as_of: date, cohorts: int, months: int) -> dict:
    cohort_months = months_back(as_of, cohorts)
    members: dict[str, list[User]] = {m: [] for m in cohort_months}
    for u in people.users:
        members.get(month_key(u.signed_up), []).append(u)
    rows = []
    for m in cohort_months:
        active_months = [{month_key(d) for d in u.active_days} for u in members[m]]
        reachable = min(months, month_offset(m, month_key(as_of)) + 1)
        rows.append(
            {
                "month": m,
                "signups": len(members[m]),
                "active": [sum(month_after(m, k) in seen for seen in active_months) for k in range(reachable)],
            }
        )
    eligible = [u for u in people.users if min(u.active_days) <= as_of - timedelta(days=7)]
    came_back = [u for u in eligible if max(u.active_days) >= min(u.active_days) + timedelta(days=7)]
    return {
        "as_of": as_of.isoformat(),
        "cohorts": rows,
        "came_back": {"eligible": len(eligible), "came_back": len(came_back)},
    }


def month_after(month: str, k: int) -> str:
    year, mon = map(int, month.split("-"))
    index = year * 12 + mon - 1 + k
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


# --- Rendering -----------------------------------------------------------------

BAR_WIDTH = 30
EIGHTHS = " ▏▎▍▌▋▊▉"


def bar(n: int, top: int) -> str:
    if not top:
        return ""
    eighths = round(n / top * BAR_WIDTH * 8)
    return "█" * (eighths // 8) + EIGHTHS[eighths % 8].strip()


def count_table(title: str, label: str, rows: list[tuple[str, int]]) -> Table:
    table = Table(title=title, title_justify="left", box=box.SIMPLE_HEAD, pad_edge=False)
    table.add_column(label)
    table.add_column("n", justify="right")
    table.add_column("", style="green", no_wrap=True)
    top = max((n for _, n in rows), default=0)
    for name, n in rows:
        table.add_row(name, str(n), bar(n, top))
    return table


def render_overview(console: Console, data: dict) -> None:
    console.print(f"[bold]Users as of {data['as_of']}[/]: {data['users']}")
    console.print()
    for w in WINDOWS:
        console.print(
            f"  active in the last {w:>2} days: [bold]{data['active'][str(w)]:>4}[/]"
            f"   guest activity: {data['guests_active'][str(w)]:>4}"
        )
    plans = ", ".join(f"{plan} {n}" for plan, n in data["paying"]["by_plan"].items())
    console.print(
        f"  paying: [bold]{data['paying']['total']}[/]"
        + (f" ({plans})" if plans else "")
        + f"   trialing: {data['trialing']}"
    )
    console.print()
    console.print(
        count_table("Sign-ups per week", "week of", [(r["week"], r["signups"]) for r in data["signups_weekly"]])
    )
    console.print(
        count_table("Sign-ups per month", "month", [(r["month"], r["signups"]) for r in data["signups_monthly"]])
    )
    console.print(count_table("Sign-in methods", "method", [(r["method"], r["users"]) for r in data["methods"]]))


def render_users(console: Console, rows: list[dict]) -> None:
    table = Table(
        box=box.SIMPLE_HEAD, pad_edge=False, collapse_padding=True, caption=f"{len(rows)} users", caption_justify="left"
    )
    table.add_column("email", overflow="ellipsis", no_wrap=True)
    table.add_column("name", overflow="ellipsis", no_wrap=True, max_width=10)
    table.add_column("signed up", min_width=10)
    table.add_column("via", min_width=5)
    table.add_column("last\nactive", justify="right", min_width=6)
    table.add_column("days\n/30", justify="right", min_width=4)
    table.add_column("docs", justify="right", min_width=4)
    table.add_column("plan", min_width=14)
    short = {"google": "G", "github": "GH"}
    for r in rows:
        table.add_row(
            r["email"],
            r["name"],
            r["signed_up"],
            "+".join(short.get(p, p) for p in r["methods"]) or "email",
            f"{r['last_active_days_ago']}d" if r["last_active_days_ago"] else "today",
            str(r["active_days_30"]),
            str(r["documents"]),
            r["plan"],
        )
    console.print(table)
    console.print("G Google, GH GitHub, email: email only. days/30: days active in the last 30.", style="dim")


def render_retention(console: Console, data: dict) -> None:
    width = max((len(r["active"]) for r in data["cohorts"]), default=1)
    table = Table(
        title=f"Active in the months after sign-up, as of {data['as_of']}",
        title_justify="left",
        box=box.SIMPLE_HEAD,
        pad_edge=False,
    )
    table.add_column("cohort")
    table.add_column("users", justify="right")
    for k in range(width):
        table.add_column(f"M+{k}", justify="right")
    for r in data["cohorts"]:
        cells = [f"{n} [dim]{n * 100 // r['signups']:>3}%[/]" if r["signups"] else "" for n in r["active"]]
        table.add_row(r["month"], str(r["signups"]), *cells, *[""] * (width - len(cells)))
    console.print(table)
    back = data["came_back"]
    share = f"{back['came_back'] * 100 // back['eligible']}%" if back["eligible"] else "–"
    console.print(
        f"Came back 7 or more days after their first day: [bold]{back['came_back']}[/] of "
        f"{back['eligible']} ({share}); users whose first day is under a week ago are left out."
    )


# --- The data ------------------------------------------------------------------

USERS_SQL = """
SELECT u.id, u.email, coalesce(u.name, '') AS name,
       (u.created AT TIME ZONE 'UTC')::date AS signed_up,
       coalesce((SELECT string_agg(o.provider, ' ' ORDER BY o.provider)
                 FROM oauthidentity o WHERE o.user_id = u.id), '') AS providers,
       coalesce(p.tier::text, '') AS plan, coalesce(s.status::text, '') AS status,
       (SELECT count(*) FROM document d WHERE d.user_id = u.id) AS documents
FROM useraccount u
LEFT JOIN usersubscription s ON s.user_id = u.id
LEFT JOIN plan p ON p.id = s.plan_id
"""

ACTIVITY_SQL = """
SELECT user_id, (created AT TIME ZONE 'UTC')::date AS day FROM document WHERE created IS NOT NULL
UNION SELECT user_id, (created AT TIME ZONE 'UTC')::date FROM usagelog WHERE created IS NOT NULL
UNION SELECT user_id, (last_used AT TIME ZONE 'UTC')::date FROM authsession WHERE kind = 'browser'
"""


def copy_statement(sql: str) -> str:
    return f"COPY ({sql.strip()}) TO STDOUT WITH CSV HEADER"


def load(fetch, as_of: date) -> People:
    days: dict[str, set[date]] = {}
    for row in fetch(ACTIVITY_SQL):
        day = date.fromisoformat(row["day"])
        if day <= as_of:
            days.setdefault(row["user_id"], set()).add(day)
    users = []
    for row in fetch(USERS_SQL):
        signed_up = date.fromisoformat(row["signed_up"])
        if signed_up > as_of:
            continue
        users.append(
            User(
                email=row["email"],
                name=row["name"],
                signed_up=signed_up,
                providers=tuple(row["providers"].split()),
                plan=row["plan"],
                status=row["status"],
                documents=int(row["documents"]),
                active_days=frozenset(days.get(row["id"], set()) | {signed_up}),
            )
        )
    guests = {uid: frozenset(d) for uid, d in days.items() if uid.startswith("anon-")}
    return People(users=users, guest_days=guests)


def parse_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def local_fetch(database_url: str):
    import psycopg

    url = database_url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )

    def fetch(sql: str) -> list[dict[str, str]]:
        with (
            psycopg.connect(url, options="-c default_transaction_read_only=on") as conn,
            conn.cursor().copy(copy_statement(sql)) as copy,
        ):
            return parse_csv(b"".join(bytes(chunk) for chunk in copy).decode())

    return fetch


PROD_PSQL = (
    "docker exec -i -e PGOPTIONS='-c default_transaction_read_only=on' "
    '"$(docker ps -qf name=yapit_postgres)" '
    "psql -X -q -v ON_ERROR_STOP=1 -U yapit_prod -d yapit_prod"
)


def prod_fetch(host: str):
    def fetch(sql: str) -> list[dict[str, str]]:
        done = subprocess.run(
            ["ssh", host, PROD_PSQL],
            input=copy_statement(sql) + ";\n",
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if done.returncode != 0:
            sys.exit(f"Reading prod over ssh {shlex.quote(host)} failed:\n{done.stderr.strip()}")
        return parse_csv(done.stdout)

    return fetch


def vps_host() -> str:
    host = os.environ.get("VPS_HOST")
    if not host:
        sys.exit("VPS_HOST is not set: run `make prod-env` and use `make user-stats`, or pass --database-url.")
    return host


if __name__ == "__main__":
    main(tyro.cli(Cli, description=__doc__, config=(tyro.conf.CascadeSubcommandArgs, tyro.conf.OmitArgPrefixes)))
