"""drop Stack Auth's tables, enum types and sequence

Runs right after `5154eb03f6c9` copied Stack Auth's users into the gateway's auth
tables. The names are the ones prod's database held on 2026-10-28, dropped by name
with `IF EXISTS`, so a database that never ran Stack Auth passes through. Its enum
types are PascalCase and quoted, which keeps our lowercase `subscriptionstatus`
apart from Stack Auth's `"SubscriptionStatus"`.

The downgrade does nothing: the way back is the `pg_dump` taken before the deploy
that runs this revision.

Revision ID: d4b8c97a743c
Revises: 5154eb03f6c9
Create Date: 2026-10-28

"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4b8c97a743c"
down_revision: str | None = "5154eb03f6c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STACK_AUTH_TABLES = (
    "ApiKeySet",
    "AuthMethod",
    "BranchConfigOverride",
    "CacheEntry",
    "CliAuthAttempt",
    "ContactChannel",
    "DataVaultEntry",
    "DeletedRow",
    "EmailDraft",
    "EmailOutbox",
    "EmailOutboxProcessingMetadata",
    "EmailTemplate",
    "EnvironmentConfigOverride",
    "Event",
    "EventIpInfo",
    "ExternalDbSyncMetadata",
    "IdPAccountToCdfcResultMapping",
    "IdPAdapterData",
    "ItemQuantityChange",
    "OAuthAccessToken",
    "OAuthAuthMethod",
    "OAuthOuterInfo",
    "OAuthToken",
    "OneTimePurchase",
    "OtpAuthMethod",
    "OutgoingRequest",
    "PasskeyAuthMethod",
    "PasswordAuthMethod",
    "ProductVersion",
    "Project",
    "ProjectApiKey",
    "ProjectUser",
    "ProjectUserAuthorizationCode",
    "ProjectUserDirectPermission",
    "ProjectUserOAuthAccount",
    "ProjectUserRefreshToken",
    "ProjectWrapperCodes",
    "ProvisionedProject",
    "SchemaMigration",
    "SessionReplay",
    "SessionReplayChunk",
    "Subscription",
    "SubscriptionInvoice",
    "Team",
    "TeamMember",
    "TeamMemberDirectPermission",
    "Tenancy",
    "ThreadMessage",
    "UserNotificationPreference",
    "VerificationCode",
    # Not on prod; older Stack Auth builds, which a selfhost may have run, kept Prisma's own table.
    "_prisma_migrations",
)

STACK_AUTH_ENUM_TYPES = (
    "BooleanTrue",
    "ContactChannelType",
    "CustomerType",
    "DraftThemeMode",
    "EmailOutboxCreatedWith",
    "EmailOutboxSimpleStatus",
    "EmailOutboxSkippedReason",
    "EmailOutboxStatus",
    "EmailTemplateType",
    "PurchaseCreationSource",
    "StandardOAuthProviderType",
    "SubscriptionStatus",
    "VerificationCodeType",
)

STACK_AUTH_SEQUENCES = ("global_seq_id",)


def quoted(names: Sequence[str]) -> str:
    return ", ".join(f'"{name}"' for name in names)


def upgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {quoted(STACK_AUTH_TABLES)} CASCADE")
    op.execute(f"DROP TYPE IF EXISTS {quoted(STACK_AUTH_ENUM_TYPES)} CASCADE")
    op.execute(f"DROP SEQUENCE IF EXISTS {quoted(STACK_AUTH_SEQUENCES)} CASCADE")


def downgrade() -> None:
    pass
