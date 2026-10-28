"""The Alembic revisions that copy Stack Auth's users into the gateway's auth tables, keeping every user's id,
and then drop Stack Auth's data."""

import uuid

import psycopg
import pytest
from alembic import command, config
from testcontainers.postgres import PostgresContainer

from yapit.gateway.db import ALEMBIC_INI

YAPIT_TENANCY = "11111111-1111-1111-1111-111111111111"
INTERNAL_TENANCY = "22222222-2222-2222-2222-222222222222"

PASSWORD_USER = "a0000000-0000-0000-0000-000000000001"
GOOGLE_USER = "a0000000-0000-0000-0000-000000000002"
BOTH_USER = "a0000000-0000-0000-0000-000000000003"
NO_EMAIL_USER = "a0000000-0000-0000-0000-000000000004"
STALE_TWIN = "a0000000-0000-0000-0000-000000000005"
ACTIVE_TWIN = "a0000000-0000-0000-0000-000000000006"
STACK_AUTH_GUEST = "a0000000-0000-0000-0000-000000000007"
INTERNAL_ADMIN = "b0000000-0000-0000-0000-000000000001"

# The parts of Stack Auth's schema (stackauth/server:53c1c9e, apps/backend/prisma/schema.prisma) the copy reads.
STACK_AUTH_SCHEMA = """
CREATE TYPE "BooleanTrue" AS ENUM ('TRUE');
CREATE TYPE "ContactChannelType" AS ENUM ('EMAIL');
CREATE TABLE "ProjectUser" (
    "tenancyId" uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    "mirroredProjectId" text NOT NULL,
    "mirroredBranchId" text NOT NULL,
    "createdAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastActiveAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "displayName" text,
    "isAnonymous" boolean NOT NULL DEFAULT false,
    PRIMARY KEY ("tenancyId", "projectUserId")
);
CREATE TABLE "ContactChannel" (
    "tenancyId" uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    id uuid NOT NULL,
    "createdAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    type "ContactChannelType" NOT NULL,
    "isPrimary" "BooleanTrue",
    "usedForAuth" "BooleanTrue",
    "isVerified" boolean NOT NULL,
    value text NOT NULL,
    PRIMARY KEY ("tenancyId", "projectUserId", id)
);
CREATE TABLE "PasswordAuthMethod" (
    "tenancyId" uuid NOT NULL,
    "authMethodId" uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    "passwordHash" text NOT NULL,
    PRIMARY KEY ("tenancyId", "authMethodId")
);
CREATE TABLE "ProjectUserOAuthAccount" (
    id uuid NOT NULL,
    "tenancyId" uuid NOT NULL,
    "projectUserId" uuid,
    "configOAuthProviderId" text NOT NULL,
    "providerAccountId" text NOT NULL,
    "createdAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    email text,
    "allowConnectedAccounts" boolean NOT NULL DEFAULT true,
    "allowSignIn" boolean NOT NULL DEFAULT true,
    PRIMARY KEY ("tenancyId", id)
);
"""

# Every object Stack Auth held in prod's `public` schema on 2026-10-28, besides the ones above.
STACK_AUTH_TABLES_NOT_READ = (
    "ApiKeySet", "AuthMethod", "BranchConfigOverride", "CacheEntry", "CliAuthAttempt", "DataVaultEntry",
    "DeletedRow", "EmailDraft", "EmailOutbox", "EmailOutboxProcessingMetadata", "EmailTemplate",
    "EnvironmentConfigOverride", "Event", "EventIpInfo", "ExternalDbSyncMetadata", "IdPAccountToCdfcResultMapping",
    "IdPAdapterData", "ItemQuantityChange", "OAuthAccessToken", "OAuthAuthMethod", "OAuthOuterInfo", "OAuthToken",
    "OneTimePurchase", "OtpAuthMethod", "OutgoingRequest", "PasskeyAuthMethod", "ProductVersion", "Project",
    "ProjectApiKey", "ProjectUserAuthorizationCode", "ProjectUserDirectPermission", "ProjectUserRefreshToken",
    "ProjectWrapperCodes", "ProvisionedProject", "SchemaMigration", "SessionReplay", "SessionReplayChunk",
    "SubscriptionInvoice", "Team", "TeamMember", "TeamMemberDirectPermission", "Tenancy", "ThreadMessage",
    "UserNotificationPreference", "VerificationCode",
    "_prisma_migrations",  # not on prod, but older Stack Auth builds a selfhost may have run kept it
)  # fmt: skip
STACK_AUTH_ENUM_TYPES_NOT_READ = (
    "CustomerType", "DraftThemeMode", "EmailOutboxCreatedWith", "EmailOutboxSimpleStatus", "EmailOutboxSkippedReason",
    "EmailOutboxStatus", "EmailTemplateType", "PurchaseCreationSource", "StandardOAuthProviderType",
    "VerificationCodeType",
)  # fmt: skip
STACK_AUTH_REST_OF_SCHEMA = "\n".join(
    [f'CREATE TABLE "{table}" (id uuid PRIMARY KEY);' for table in STACK_AUTH_TABLES_NOT_READ]
    + [f'CREATE TYPE "{enum}" AS ENUM (\'A\');' for enum in STACK_AUTH_ENUM_TYPES_NOT_READ]
    + [
        "CREATE SEQUENCE global_seq_id;",
        'CREATE TYPE "SubscriptionStatus" AS ENUM (\'active\');',
        'CREATE TABLE "Subscription" (id uuid PRIMARY KEY, status "SubscriptionStatus",'
        " seq bigint DEFAULT nextval('global_seq_id'));",
        'ALTER TABLE "ContactChannel" ADD FOREIGN KEY ("tenancyId", "projectUserId")'
        ' REFERENCES "ProjectUser" ("tenancyId", "projectUserId");',
    ]
)


@pytest.fixture(scope="module")
def postgres():
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        yield postgres


def create_database(postgres) -> str:
    name = f"t_{uuid.uuid4().hex[:12]}"
    admin_url = postgres.get_connection_url().replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name}")
    return admin_url.rsplit("/", 1)[0] + f"/{name}"


def use_database(monkeypatch, url: str) -> None:
    """Points Alembic's env.py at the database."""
    monkeypatch.setenv("DATABASE_URL", url.replace("postgresql://", "postgresql+psycopg://"))


@pytest.fixture
def database(postgres, monkeypatch) -> str:
    """A fresh database in the container, the one Alembic migrates."""
    url = create_database(postgres)
    use_database(monkeypatch, url)
    return url


@pytest.fixture
def yapit_schema(postgres, monkeypatch) -> dict[str, set[str]]:
    """The schema objects of a database that never held Stack Auth's, migrated to head."""
    url = create_database(postgres)
    with monkeypatch.context() as patch:
        use_database(patch, url)
        upgrade_to_head()
    return schema_objects(url)


def alembic_config() -> config.Config:
    alembic_cfg = config.Config(str(ALEMBIC_INI))
    alembic_cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
    return alembic_cfg


def upgrade_to_head() -> None:
    command.upgrade(alembic_config(), "head")


def schema_objects(url: str) -> dict[str, set[str]]:
    with psycopg.connect(url) as conn:
        return {
            "tables": {row[0] for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")},
            "enum types": {
                row[0]
                for row in conn.execute(
                    "SELECT typname FROM pg_type JOIN pg_namespace ON pg_namespace.oid = typnamespace"
                    " WHERE nspname = 'public' AND typtype = 'e'"
                )
            },
            "sequences": {
                row[0] for row in conn.execute("SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'")
            },
        }


def add_user(
    conn,
    user_id: str,
    *,
    tenancy: str = YAPIT_TENANCY,
    project: str = "yapit-project",
    email: str | None = None,
    other_email: str | None = None,
    name: str | None = None,
    password: bool = False,
    oauth: tuple[str, str, str] | None = None,
    last_active: str = "2026-10-01",
    anonymous: bool = False,
) -> None:
    conn.execute(
        'INSERT INTO "ProjectUser" ("tenancyId", "projectUserId", "mirroredProjectId", "mirroredBranchId",'
        ' "displayName", "lastActiveAt", "isAnonymous") VALUES (%s, %s, %s, %s, %s, %s, %s)',
        (tenancy, user_id, project, "main", name, last_active, anonymous),
    )
    if email is not None:
        conn.execute(
            'INSERT INTO "ContactChannel" ("tenancyId", "projectUserId", id, type, "isPrimary", "usedForAuth",'
            ' "isVerified", value) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (tenancy, user_id, str(uuid.uuid4()), "EMAIL", "TRUE", "TRUE" if password else None, True, email),
        )
    if other_email is not None:
        conn.execute(
            'INSERT INTO "ContactChannel" ("tenancyId", "projectUserId", id, type, "isVerified", value)'
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (tenancy, user_id, str(uuid.uuid4()), "EMAIL", True, other_email),
        )
    if password:
        conn.execute(
            'INSERT INTO "PasswordAuthMethod" ("tenancyId", "authMethodId", "projectUserId", "passwordHash")'
            " VALUES (%s, %s, %s, %s)",
            (tenancy, str(uuid.uuid4()), user_id, "$2b$10$abcdefghijklmnopqrstuv"),
        )
    if oauth is not None:
        provider, account_id, oauth_email = oauth
        conn.execute(
            'INSERT INTO "ProjectUserOAuthAccount" (id, "tenancyId", "projectUserId", "configOAuthProviderId",'
            ' "providerAccountId", email) VALUES (%s, %s, %s, %s, %s, %s)',
            (str(uuid.uuid4()), tenancy, user_id, provider, account_id, oauth_email),
        )


def test_revisions_copy_stack_auth_users_keeping_their_ids_then_drop_stack_auth(yapit_schema, database):
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(STACK_AUTH_SCHEMA)
        conn.execute(STACK_AUTH_REST_OF_SCHEMA)
        add_user(conn, PASSWORD_USER, email="Pat@Example.com", name="Pat", password=True)
        add_user(conn, GOOGLE_USER, email="gina@gmail.com", oauth=("google", "1001", "gina@gmail.com"))
        add_user(
            conn,
            BOTH_USER,
            email="bo@example.com",
            other_email="aaa-bo-old@example.com",
            name="Bo",
            password=True,
            oauth=("github", "42", "bo@users.gh"),
        )
        add_user(conn, NO_EMAIL_USER, oauth=("github", "77", None))
        add_user(conn, STALE_TWIN, email="twin@example.com", last_active="2026-01-01")
        add_user(conn, ACTIVE_TWIN, email="Twin@example.com", last_active="2026-09-01")
        add_user(conn, STACK_AUTH_GUEST, email="guest@example.com", anonymous=True)
        add_user(
            conn,
            INTERNAL_ADMIN,
            tenancy=INTERNAL_TENANCY,
            project="internal",
            email="admin@example.com",
            password=True,
            oauth=("github", "1", "admin@example.com"),
        )

    upgrade_to_head()

    with psycopg.connect(database) as conn:
        accounts = set(conn.execute("SELECT id, email, name FROM useraccount").fetchall())
        identities = set(conn.execute("SELECT provider, provider_account_id, user_id, email FROM oauthidentity"))
    assert accounts == {
        (PASSWORD_USER, "pat@example.com", "Pat"),
        (GOOGLE_USER, "gina@gmail.com", None),
        (BOTH_USER, "bo@example.com", "Bo"),
        (ACTIVE_TWIN, "twin@example.com", None),
    }
    assert identities == {
        ("google", "1001", GOOGLE_USER, "gina@gmail.com"),
        ("github", "42", BOTH_USER, "bo@users.gh"),
    }
    assert "subscriptionstatus" in yapit_schema["enum types"]
    assert schema_objects(database) == yapit_schema


def test_drop_of_stack_auth_runs_again_on_a_database_it_already_cleared(yapit_schema, database):
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(STACK_AUTH_SCHEMA)
        conn.execute(STACK_AUTH_REST_OF_SCHEMA)
    upgrade_to_head()

    command.downgrade(alembic_config(), "5154eb03f6c9")
    upgrade_to_head()

    assert schema_objects(database) == yapit_schema


def test_revision_without_stack_auth_tables_only_creates_the_auth_tables(database):
    upgrade_to_head()

    with psycopg.connect(database) as conn:
        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()
            for table in ("useraccount", "oauthidentity", "authsession", "emailchallenge")
        }
    assert counts == {table: (0,) for table in counts}
