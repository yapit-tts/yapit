--
-- PostgreSQL database dump
--

-- Dumped from database version 16.9
-- Dumped by pg_dump version 16.9

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: BooleanTrue; Type: TYPE; Schema: public; Owner: yapit
--

CREATE TYPE public."BooleanTrue" AS ENUM (
    'TRUE'
);


ALTER TYPE public."BooleanTrue" OWNER TO yapit;

--
-- Name: ContactChannelType; Type: TYPE; Schema: public; Owner: yapit
--

CREATE TYPE public."ContactChannelType" AS ENUM (
    'EMAIL'
);


ALTER TYPE public."ContactChannelType" OWNER TO yapit;

--
-- Name: EmailTemplateType; Type: TYPE; Schema: public; Owner: yapit
--

CREATE TYPE public."EmailTemplateType" AS ENUM (
    'EMAIL_VERIFICATION',
    'PASSWORD_RESET',
    'MAGIC_LINK',
    'TEAM_INVITATION'
);


ALTER TYPE public."EmailTemplateType" OWNER TO yapit;

--
-- Name: OAuthAccountMergeStrategy; Type: TYPE; Schema: public; Owner: yapit
--

CREATE TYPE public."OAuthAccountMergeStrategy" AS ENUM (
    'LINK_METHOD',
    'RAISE_ERROR',
    'ALLOW_DUPLICATES'
);


ALTER TYPE public."OAuthAccountMergeStrategy" OWNER TO yapit;

--
-- Name: PermissionScope; Type: TYPE; Schema: public; Owner: yapit
--

CREATE TYPE public."PermissionScope" AS ENUM (
    'PROJECT',
    'TEAM'
);


ALTER TYPE public."PermissionScope" OWNER TO yapit;

--
-- Name: ProxiedOAuthProviderType; Type: TYPE; Schema: public; Owner: yapit
--

CREATE TYPE public."ProxiedOAuthProviderType" AS ENUM (
    'GITHUB',
    'GOOGLE',
    'MICROSOFT',
    'SPOTIFY'
);


ALTER TYPE public."ProxiedOAuthProviderType" OWNER TO yapit;

--
-- Name: StandardOAuthProviderType; Type: TYPE; Schema: public; Owner: yapit
--

CREATE TYPE public."StandardOAuthProviderType" AS ENUM (
    'GITHUB',
    'FACEBOOK',
    'GOOGLE',
    'MICROSOFT',
    'SPOTIFY',
    'DISCORD',
    'GITLAB',
    'BITBUCKET',
    'LINKEDIN',
    'APPLE',
    'X'
);


ALTER TYPE public."StandardOAuthProviderType" OWNER TO yapit;

--
-- Name: TeamSystemPermission; Type: TYPE; Schema: public; Owner: yapit
--

CREATE TYPE public."TeamSystemPermission" AS ENUM (
    'UPDATE_TEAM',
    'DELETE_TEAM',
    'READ_MEMBERS',
    'REMOVE_MEMBERS',
    'INVITE_MEMBERS',
    'MANAGE_API_KEYS'
);


ALTER TYPE public."TeamSystemPermission" OWNER TO yapit;

--
-- Name: VerificationCodeType; Type: TYPE; Schema: public; Owner: yapit
--

CREATE TYPE public."VerificationCodeType" AS ENUM (
    'ONE_TIME_PASSWORD',
    'CONTACT_CHANNEL_VERIFICATION',
    'PASSWORD_RESET',
    'TEAM_INVITATION',
    'MFA_ATTEMPT',
    'PASSKEY_REGISTRATION_CHALLENGE',
    'PASSKEY_AUTHENTICATION_CHALLENGE',
    'NEON_INTEGRATION_PROJECT_TRANSFER'
);


ALTER TYPE public."VerificationCodeType" OWNER TO yapit;

--
-- Name: update_project_user_count(); Type: FUNCTION; Schema: public; Owner: yapit
--

CREATE FUNCTION public.update_project_user_count() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Increment userCount when a new ProjectUser is added
        UPDATE "Project" SET "userCount" = "userCount" + 1
        WHERE "id" = NEW."mirroredProjectId";
    ELSIF TG_OP = 'DELETE' THEN
        -- Decrement userCount when a ProjectUser is deleted
        UPDATE "Project" SET "userCount" = "userCount" - 1
        WHERE "id" = OLD."mirroredProjectId";
    ELSIF TG_OP = 'UPDATE' AND OLD."mirroredProjectId" <> NEW."mirroredProjectId" THEN
        -- If mirroredProjectId changed, decrement count for old project and increment for new project
        UPDATE "Project" SET "userCount" = "userCount" - 1
        WHERE "id" = OLD."mirroredProjectId";
        
        UPDATE "Project" SET "userCount" = "userCount" + 1
        WHERE "id" = NEW."mirroredProjectId";
    END IF;
    RETURN NULL;
END;
$$;


ALTER FUNCTION public.update_project_user_count() OWNER TO yapit;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ApiKeySet; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ApiKeySet" (
    "projectId" text NOT NULL,
    id uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    description text NOT NULL,
    "expiresAt" timestamp(3) without time zone NOT NULL,
    "manuallyRevokedAt" timestamp(3) without time zone,
    "publishableClientKey" text,
    "secretServerKey" text,
    "superSecretAdminKey" text
);


ALTER TABLE public."ApiKeySet" OWNER TO yapit;

--
-- Name: AuthMethod; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."AuthMethod" (
    id uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    "authMethodConfigId" uuid NOT NULL,
    "projectConfigId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."AuthMethod" OWNER TO yapit;

--
-- Name: AuthMethodConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."AuthMethodConfig" (
    "projectConfigId" uuid NOT NULL,
    id uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    enabled boolean DEFAULT true NOT NULL
);


ALTER TABLE public."AuthMethodConfig" OWNER TO yapit;

--
-- Name: CliAuthAttempt; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."CliAuthAttempt" (
    "tenancyId" uuid NOT NULL,
    id uuid NOT NULL,
    "pollingCode" text NOT NULL,
    "loginCode" text NOT NULL,
    "refreshToken" text,
    "expiresAt" timestamp(3) without time zone NOT NULL,
    "usedAt" timestamp(3) without time zone,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


ALTER TABLE public."CliAuthAttempt" OWNER TO yapit;

--
-- Name: ConnectedAccount; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ConnectedAccount" (
    id uuid NOT NULL,
    "projectConfigId" uuid NOT NULL,
    "connectedAccountConfigId" uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    "oauthProviderConfigId" text NOT NULL,
    "providerAccountId" text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."ConnectedAccount" OWNER TO yapit;

--
-- Name: ConnectedAccountConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ConnectedAccountConfig" (
    "projectConfigId" uuid NOT NULL,
    id uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    enabled boolean DEFAULT true NOT NULL
);


ALTER TABLE public."ConnectedAccountConfig" OWNER TO yapit;

--
-- Name: ContactChannel; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ContactChannel" (
    id uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    type public."ContactChannelType" NOT NULL,
    "isPrimary" public."BooleanTrue",
    "isVerified" boolean NOT NULL,
    value text NOT NULL,
    "usedForAuth" public."BooleanTrue",
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."ContactChannel" OWNER TO yapit;

--
-- Name: EmailServiceConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."EmailServiceConfig" (
    "projectConfigId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


ALTER TABLE public."EmailServiceConfig" OWNER TO yapit;

--
-- Name: EmailTemplate; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."EmailTemplate" (
    "projectConfigId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    content jsonb NOT NULL,
    type public."EmailTemplateType" NOT NULL,
    subject text NOT NULL
);


ALTER TABLE public."EmailTemplate" OWNER TO yapit;

--
-- Name: Event; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."Event" (
    id uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "isWide" boolean NOT NULL,
    "eventStartedAt" timestamp(3) without time zone NOT NULL,
    "eventEndedAt" timestamp(3) without time zone NOT NULL,
    "systemEventTypeIds" text[],
    data jsonb NOT NULL,
    "endUserIpInfoGuessId" uuid,
    "isEndUserIpInfoGuessTrusted" boolean DEFAULT false NOT NULL
);


ALTER TABLE public."Event" OWNER TO yapit;

--
-- Name: EventIpInfo; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."EventIpInfo" (
    id uuid NOT NULL,
    ip text NOT NULL,
    "countryCode" text,
    "regionCode" text,
    "cityName" text,
    latitude double precision,
    longitude double precision,
    "tzIdentifier" text,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


ALTER TABLE public."EventIpInfo" OWNER TO yapit;

--
-- Name: IdPAccountToCdfcResultMapping; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."IdPAccountToCdfcResultMapping" (
    "idpId" text NOT NULL,
    id text NOT NULL,
    "idpAccountId" uuid NOT NULL,
    "cdfcResult" jsonb NOT NULL
);


ALTER TABLE public."IdPAccountToCdfcResultMapping" OWNER TO yapit;

--
-- Name: IdPAdapterData; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."IdPAdapterData" (
    "idpId" text NOT NULL,
    model text NOT NULL,
    id text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    payload jsonb NOT NULL,
    "expiresAt" timestamp(3) without time zone NOT NULL
);


ALTER TABLE public."IdPAdapterData" OWNER TO yapit;

--
-- Name: NeonProvisionedProject; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."NeonProvisionedProject" (
    "projectId" text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "neonClientId" text NOT NULL
);


ALTER TABLE public."NeonProvisionedProject" OWNER TO yapit;

--
-- Name: OAuthAccessToken; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."OAuthAccessToken" (
    id uuid NOT NULL,
    "oAuthProviderConfigId" text NOT NULL,
    "providerAccountId" text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "accessToken" text NOT NULL,
    scopes text[],
    "expiresAt" timestamp(3) without time zone NOT NULL,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."OAuthAccessToken" OWNER TO yapit;

--
-- Name: OAuthAuthMethod; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."OAuthAuthMethod" (
    "projectConfigId" uuid NOT NULL,
    "authMethodId" uuid NOT NULL,
    "oauthProviderConfigId" text NOT NULL,
    "providerAccountId" text NOT NULL,
    "projectUserId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."OAuthAuthMethod" OWNER TO yapit;

--
-- Name: OAuthOuterInfo; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."OAuthOuterInfo" (
    id uuid NOT NULL,
    info jsonb NOT NULL,
    "expiresAt" timestamp(3) without time zone NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "innerState" text NOT NULL
);


ALTER TABLE public."OAuthOuterInfo" OWNER TO yapit;

--
-- Name: OAuthProviderConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."OAuthProviderConfig" (
    "projectConfigId" uuid NOT NULL,
    id text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "authMethodConfigId" uuid,
    "connectedAccountConfigId" uuid
);


ALTER TABLE public."OAuthProviderConfig" OWNER TO yapit;

--
-- Name: OAuthToken; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."OAuthToken" (
    id uuid NOT NULL,
    "oAuthProviderConfigId" text NOT NULL,
    "providerAccountId" text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "refreshToken" text NOT NULL,
    scopes text[],
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."OAuthToken" OWNER TO yapit;

--
-- Name: OtpAuthMethod; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."OtpAuthMethod" (
    "authMethodId" uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."OtpAuthMethod" OWNER TO yapit;

--
-- Name: OtpAuthMethodConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."OtpAuthMethodConfig" (
    "projectConfigId" uuid NOT NULL,
    "authMethodConfigId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "contactChannelType" public."ContactChannelType" NOT NULL
);


ALTER TABLE public."OtpAuthMethodConfig" OWNER TO yapit;

--
-- Name: PasskeyAuthMethod; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."PasskeyAuthMethod" (
    "authMethodId" uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "credentialId" text NOT NULL,
    "publicKey" text NOT NULL,
    "userHandle" text NOT NULL,
    transports text[],
    "credentialDeviceType" text NOT NULL,
    counter integer NOT NULL,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."PasskeyAuthMethod" OWNER TO yapit;

--
-- Name: PasskeyAuthMethodConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."PasskeyAuthMethodConfig" (
    "projectConfigId" uuid NOT NULL,
    "authMethodConfigId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


ALTER TABLE public."PasskeyAuthMethodConfig" OWNER TO yapit;

--
-- Name: PasswordAuthMethod; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."PasswordAuthMethod" (
    "authMethodId" uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "passwordHash" text NOT NULL,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."PasswordAuthMethod" OWNER TO yapit;

--
-- Name: PasswordAuthMethodConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."PasswordAuthMethodConfig" (
    "projectConfigId" uuid NOT NULL,
    "authMethodConfigId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


ALTER TABLE public."PasswordAuthMethodConfig" OWNER TO yapit;

--
-- Name: Permission; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."Permission" (
    "queryableId" text NOT NULL,
    "dbId" uuid NOT NULL,
    "projectConfigId" uuid,
    "teamId" uuid,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    description text,
    scope public."PermissionScope" NOT NULL,
    "isDefaultTeamCreatorPermission" boolean DEFAULT false NOT NULL,
    "isDefaultTeamMemberPermission" boolean DEFAULT false NOT NULL,
    "tenancyId" uuid,
    "isDefaultProjectPermission" boolean DEFAULT false NOT NULL
);


ALTER TABLE public."Permission" OWNER TO yapit;

--
-- Name: PermissionEdge; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."PermissionEdge" (
    "edgeId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "parentPermissionDbId" uuid,
    "childPermissionDbId" uuid NOT NULL,
    "parentTeamSystemPermission" public."TeamSystemPermission"
);


ALTER TABLE public."PermissionEdge" OWNER TO yapit;

--
-- Name: Project; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."Project" (
    id text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "displayName" text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    "configId" uuid NOT NULL,
    "isProductionMode" boolean NOT NULL,
    "userCount" integer DEFAULT 0 NOT NULL
);


ALTER TABLE public."Project" OWNER TO yapit;

--
-- Name: ProjectApiKey; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProjectApiKey" (
    "projectId" text NOT NULL,
    "tenancyId" uuid NOT NULL,
    id uuid NOT NULL,
    "secretApiKey" text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "expiresAt" timestamp(3) without time zone,
    "manuallyRevokedAt" timestamp(3) without time zone,
    description text NOT NULL,
    "isPublic" boolean NOT NULL,
    "teamId" uuid,
    "projectUserId" uuid
);


ALTER TABLE public."ProjectApiKey" OWNER TO yapit;

--
-- Name: ProjectConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProjectConfig" (
    id uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "allowLocalhost" boolean NOT NULL,
    "createTeamOnSignUp" boolean NOT NULL,
    "teamCreateDefaultSystemPermissions" public."TeamSystemPermission"[],
    "teamMemberDefaultSystemPermissions" public."TeamSystemPermission"[],
    "signUpEnabled" boolean DEFAULT true NOT NULL,
    "clientTeamCreationEnabled" boolean NOT NULL,
    "clientUserDeletionEnabled" boolean DEFAULT false NOT NULL,
    "legacyGlobalJwtSigning" boolean DEFAULT false NOT NULL,
    "oauthAccountMergeStrategy" public."OAuthAccountMergeStrategy" DEFAULT 'LINK_METHOD'::public."OAuthAccountMergeStrategy" NOT NULL,
    "allowTeamApiKeys" boolean DEFAULT false NOT NULL,
    "allowUserApiKeys" boolean DEFAULT false NOT NULL
);


ALTER TABLE public."ProjectConfig" OWNER TO yapit;

--
-- Name: ProjectDomain; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProjectDomain" (
    "projectConfigId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    domain text NOT NULL,
    "handlerPath" text NOT NULL
);


ALTER TABLE public."ProjectDomain" OWNER TO yapit;

--
-- Name: ProjectUser; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProjectUser" (
    "projectUserId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "profileImageUrl" text,
    "displayName" text,
    "serverMetadata" jsonb,
    "clientMetadata" jsonb,
    "requiresTotpMfa" boolean DEFAULT false NOT NULL,
    "totpSecret" bytea,
    "clientReadOnlyMetadata" jsonb,
    "tenancyId" uuid NOT NULL,
    "mirroredBranchId" text NOT NULL,
    "mirroredProjectId" text NOT NULL,
    "isAnonymous" boolean DEFAULT false NOT NULL
);


ALTER TABLE public."ProjectUser" OWNER TO yapit;

--
-- Name: ProjectUserAuthorizationCode; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProjectUserAuthorizationCode" (
    "projectUserId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "authorizationCode" text NOT NULL,
    "redirectUri" text NOT NULL,
    "expiresAt" timestamp(3) without time zone NOT NULL,
    "codeChallenge" text NOT NULL,
    "codeChallengeMethod" text NOT NULL,
    "newUser" boolean NOT NULL,
    "afterCallbackRedirectUrl" text,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."ProjectUserAuthorizationCode" OWNER TO yapit;

--
-- Name: ProjectUserDirectPermission; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProjectUserDirectPermission" (
    id uuid NOT NULL,
    "tenancyId" uuid NOT NULL,
    "projectUserId" uuid NOT NULL,
    "permissionDbId" uuid,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


ALTER TABLE public."ProjectUserDirectPermission" OWNER TO yapit;

--
-- Name: ProjectUserOAuthAccount; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProjectUserOAuthAccount" (
    "projectUserId" uuid NOT NULL,
    "projectConfigId" uuid NOT NULL,
    "oauthProviderConfigId" text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    email text,
    "providerAccountId" text NOT NULL,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."ProjectUserOAuthAccount" OWNER TO yapit;

--
-- Name: ProjectUserRefreshToken; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProjectUserRefreshToken" (
    "projectUserId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "refreshToken" text NOT NULL,
    "expiresAt" timestamp(3) without time zone,
    "tenancyId" uuid NOT NULL,
    id uuid NOT NULL,
    "isImpersonation" boolean DEFAULT false NOT NULL
);


ALTER TABLE public."ProjectUserRefreshToken" OWNER TO yapit;

--
-- Name: ProjectWrapperCodes; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProjectWrapperCodes" (
    "idpId" text NOT NULL,
    id uuid NOT NULL,
    "interactionUid" text NOT NULL,
    "authorizationCode" text NOT NULL,
    "cdfcResult" jsonb NOT NULL
);


ALTER TABLE public."ProjectWrapperCodes" OWNER TO yapit;

--
-- Name: ProxiedEmailServiceConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProxiedEmailServiceConfig" (
    "projectConfigId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


ALTER TABLE public."ProxiedEmailServiceConfig" OWNER TO yapit;

--
-- Name: ProxiedOAuthProviderConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."ProxiedOAuthProviderConfig" (
    "projectConfigId" uuid NOT NULL,
    id text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    type public."ProxiedOAuthProviderType" NOT NULL
);


ALTER TABLE public."ProxiedOAuthProviderConfig" OWNER TO yapit;

--
-- Name: SentEmail; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."SentEmail" (
    "tenancyId" uuid NOT NULL,
    id uuid NOT NULL,
    "userId" uuid,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "senderConfig" jsonb NOT NULL,
    "to" text[],
    subject text NOT NULL,
    html text,
    text text,
    error jsonb
);


ALTER TABLE public."SentEmail" OWNER TO yapit;

--
-- Name: StandardEmailServiceConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."StandardEmailServiceConfig" (
    "projectConfigId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "senderEmail" text NOT NULL,
    host text NOT NULL,
    port integer NOT NULL,
    username text NOT NULL,
    password text NOT NULL,
    "senderName" text NOT NULL
);


ALTER TABLE public."StandardEmailServiceConfig" OWNER TO yapit;

--
-- Name: StandardOAuthProviderConfig; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."StandardOAuthProviderConfig" (
    "projectConfigId" uuid NOT NULL,
    id text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    type public."StandardOAuthProviderType" NOT NULL,
    "clientId" text NOT NULL,
    "clientSecret" text NOT NULL,
    "facebookConfigId" text,
    "microsoftTenantId" text
);


ALTER TABLE public."StandardOAuthProviderConfig" OWNER TO yapit;

--
-- Name: Team; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."Team" (
    "teamId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "displayName" text NOT NULL,
    "profileImageUrl" text,
    "clientMetadata" jsonb,
    "clientReadOnlyMetadata" jsonb,
    "serverMetadata" jsonb,
    "tenancyId" uuid NOT NULL,
    "mirroredBranchId" text NOT NULL,
    "mirroredProjectId" text NOT NULL
);


ALTER TABLE public."Team" OWNER TO yapit;

--
-- Name: TeamMember; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."TeamMember" (
    "projectUserId" uuid NOT NULL,
    "teamId" uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "isSelected" public."BooleanTrue",
    "displayName" text,
    "profileImageUrl" text,
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."TeamMember" OWNER TO yapit;

--
-- Name: TeamMemberDirectPermission; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."TeamMemberDirectPermission" (
    "projectUserId" uuid NOT NULL,
    "teamId" uuid NOT NULL,
    "permissionDbId" uuid,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    id uuid NOT NULL,
    "systemPermission" public."TeamSystemPermission",
    "tenancyId" uuid NOT NULL
);


ALTER TABLE public."TeamMemberDirectPermission" OWNER TO yapit;

--
-- Name: Tenancy; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."Tenancy" (
    id uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "projectId" text NOT NULL,
    "branchId" text NOT NULL,
    "organizationId" uuid,
    "hasNoOrganization" public."BooleanTrue"
);


ALTER TABLE public."Tenancy" OWNER TO yapit;

--
-- Name: VerificationCode; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public."VerificationCode" (
    "projectId" text NOT NULL,
    id uuid NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    type public."VerificationCodeType" NOT NULL,
    code text NOT NULL,
    "expiresAt" timestamp(3) without time zone NOT NULL,
    "usedAt" timestamp(3) without time zone,
    "redirectUrl" text,
    data jsonb NOT NULL,
    method jsonb DEFAULT 'null'::jsonb NOT NULL,
    "attemptCount" integer DEFAULT 0 NOT NULL,
    "branchId" text NOT NULL
);


ALTER TABLE public."VerificationCode" OWNER TO yapit;

--
-- Name: _prisma_migrations; Type: TABLE; Schema: public; Owner: yapit
--

CREATE TABLE public._prisma_migrations (
    id character varying(36) NOT NULL,
    checksum character varying(64) NOT NULL,
    finished_at timestamp with time zone,
    migration_name character varying(255) NOT NULL,
    logs text,
    rolled_back_at timestamp with time zone,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    applied_steps_count integer DEFAULT 0 NOT NULL
);


ALTER TABLE public._prisma_migrations OWNER TO yapit;

--
-- Data for Name: ApiKeySet; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ApiKeySet" ("projectId", id, "createdAt", "updatedAt", description, "expiresAt", "manuallyRevokedAt", "publishableClientKey", "secretServerKey", "superSecretAdminKey") FROM stdin;
internal	3142e763-b230-44b5-8636-aa62f7489c26	2025-05-26 20:37:49.219	2025-05-26 20:37:49.219	Internal API key set	2099-12-31 23:59:59	\N	pAnVG7RxJFIiYhfAWp7M1p4KsKhJqZT/uDmKdVuIzQs=	RqA9ensvm/cscD7wdR/VykGiAWNS2XhX6fx0nmIQQv4=	VC0qd8WpYTNYs45wE0QsoBmXPpzCoShtxI6481e6jtU=
a12651bb-7824-459d-b424-21a0950ab902	3b0c8158-97c6-4716-b5c5-a94b547fea69	2025-05-26 20:39:17.242	2025-05-26 20:39:17.242	Automatically created during onboarding.	2225-04-08 20:39:16.733	\N	pck_8ny111ccr9yyhty8vrmjk5ab32ezvcf19crck312j42p0	ssk_0fqsegjvkkas2yr4eb78z58wr3v5r3z7hv11qtv4n2qsr	\N
\.


--
-- Data for Name: AuthMethod; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."AuthMethod" (id, "projectUserId", "authMethodConfigId", "projectConfigId", "createdAt", "updatedAt", "tenancyId") FROM stdin;
7b0b56a1-d75d-49bf-991d-487854eaaac1	00bb639d-a1ac-4cdf-a53f-c76f377d21b5	10ebf684-5a65-4c4c-8a18-171f8f300b1b	284779e6-3793-445b-93f5-d5946ee98c37	2025-05-26 20:38:39.797	2025-05-26 20:38:39.797	584e6236-ce23-4184-9a88-e9f1338f051f
\.


--
-- Data for Name: AuthMethodConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."AuthMethodConfig" ("projectConfigId", id, "createdAt", "updatedAt", enabled) FROM stdin;
284779e6-3793-445b-93f5-d5946ee98c37	10ebf684-5a65-4c4c-8a18-171f8f300b1b	2025-05-26 20:37:49.174	2025-05-26 20:37:49.174	t
64154b84-50b0-4536-81be-68ab193adc7b	503a9494-dea5-4317-a928-9b92842b9b90	2025-05-26 20:39:16.257	2025-05-26 20:39:16.257	t
\.


--
-- Data for Name: CliAuthAttempt; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."CliAuthAttempt" ("tenancyId", id, "pollingCode", "loginCode", "refreshToken", "expiresAt", "usedAt", "createdAt", "updatedAt") FROM stdin;
\.


--
-- Data for Name: ConnectedAccount; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ConnectedAccount" (id, "projectConfigId", "connectedAccountConfigId", "projectUserId", "oauthProviderConfigId", "providerAccountId", "createdAt", "updatedAt", "tenancyId") FROM stdin;
\.


--
-- Data for Name: ConnectedAccountConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ConnectedAccountConfig" ("projectConfigId", id, "createdAt", "updatedAt", enabled) FROM stdin;
\.


--
-- Data for Name: ContactChannel; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ContactChannel" (id, "projectUserId", "createdAt", "updatedAt", type, "isPrimary", "isVerified", value, "usedForAuth", "tenancyId") FROM stdin;
eea93c03-d15d-40fb-9d27-31fac3ad992f	00bb639d-a1ac-4cdf-a53f-c76f377d21b5	2025-05-26 20:38:39.792	2025-05-26 20:38:39.792	EMAIL	TRUE	f	dev@yap.it	TRUE	584e6236-ce23-4184-9a88-e9f1338f051f
\.


--
-- Data for Name: EmailServiceConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."EmailServiceConfig" ("projectConfigId", "createdAt", "updatedAt") FROM stdin;
284779e6-3793-445b-93f5-d5946ee98c37	2025-05-26 20:37:49.174	2025-05-26 20:37:49.174
64154b84-50b0-4536-81be-68ab193adc7b	2025-05-26 20:39:16.247	2025-05-26 20:39:16.247
\.


--
-- Data for Name: EmailTemplate; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."EmailTemplate" ("projectConfigId", "createdAt", "updatedAt", content, type, subject) FROM stdin;
\.


--
-- Data for Name: Event; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."Event" (id, "createdAt", "updatedAt", "isWide", "eventStartedAt", "eventEndedAt", "systemEventTypeIds", data, "endUserIpInfoGuessId", "isEndUserIpInfoGuessTrusted") FROM stdin;
586baf2c-0278-43b7-b411-14d8cf519209	2025-05-26 20:38:39.866	2025-05-26 20:38:39.866	f	2025-05-26 20:38:39.86	2025-05-26 20:38:39.86	{$session-activity,$user-activity,$project-activity,$project}	{"userId": "00bb639d-a1ac-4cdf-a53f-c76f377d21b5", "branchId": "main", "projectId": "internal", "sessionId": "babbb6ea-e666-41d1-9220-e948156fb242"}	33481600-5df8-499e-bd4b-9040b49be5df	f
\.


--
-- Data for Name: EventIpInfo; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."EventIpInfo" (id, ip, "countryCode", "regionCode", "cityName", latitude, longitude, "tzIdentifier", "createdAt", "updatedAt") FROM stdin;
33481600-5df8-499e-bd4b-9040b49be5df	172.20.0.1	\N	\N	\N	\N	\N	\N	2025-05-26 20:38:39.866	2025-05-26 20:38:39.866
\.


--
-- Data for Name: IdPAccountToCdfcResultMapping; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."IdPAccountToCdfcResultMapping" ("idpId", id, "idpAccountId", "cdfcResult") FROM stdin;
\.


--
-- Data for Name: IdPAdapterData; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."IdPAdapterData" ("idpId", model, id, "createdAt", "updatedAt", payload, "expiresAt") FROM stdin;
\.


--
-- Data for Name: NeonProvisionedProject; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."NeonProvisionedProject" ("projectId", "createdAt", "updatedAt", "neonClientId") FROM stdin;
\.


--
-- Data for Name: OAuthAccessToken; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."OAuthAccessToken" (id, "oAuthProviderConfigId", "providerAccountId", "createdAt", "updatedAt", "accessToken", scopes, "expiresAt", "tenancyId") FROM stdin;
\.


--
-- Data for Name: OAuthAuthMethod; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."OAuthAuthMethod" ("projectConfigId", "authMethodId", "oauthProviderConfigId", "providerAccountId", "projectUserId", "createdAt", "updatedAt", "tenancyId") FROM stdin;
\.


--
-- Data for Name: OAuthOuterInfo; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."OAuthOuterInfo" (id, info, "expiresAt", "createdAt", "updatedAt", "innerState") FROM stdin;
\.


--
-- Data for Name: OAuthProviderConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."OAuthProviderConfig" ("projectConfigId", id, "createdAt", "updatedAt", "authMethodConfigId", "connectedAccountConfigId") FROM stdin;
\.


--
-- Data for Name: OAuthToken; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."OAuthToken" (id, "oAuthProviderConfigId", "providerAccountId", "createdAt", "updatedAt", "refreshToken", scopes, "tenancyId") FROM stdin;
\.


--
-- Data for Name: OtpAuthMethod; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."OtpAuthMethod" ("authMethodId", "projectUserId", "createdAt", "updatedAt", "tenancyId") FROM stdin;
\.


--
-- Data for Name: OtpAuthMethodConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."OtpAuthMethodConfig" ("projectConfigId", "authMethodConfigId", "createdAt", "updatedAt", "contactChannelType") FROM stdin;
\.


--
-- Data for Name: PasskeyAuthMethod; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."PasskeyAuthMethod" ("authMethodId", "projectUserId", "createdAt", "updatedAt", "credentialId", "publicKey", "userHandle", transports, "credentialDeviceType", counter, "tenancyId") FROM stdin;
\.


--
-- Data for Name: PasskeyAuthMethodConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."PasskeyAuthMethodConfig" ("projectConfigId", "authMethodConfigId", "createdAt", "updatedAt") FROM stdin;
\.


--
-- Data for Name: PasswordAuthMethod; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."PasswordAuthMethod" ("authMethodId", "projectUserId", "createdAt", "updatedAt", "passwordHash", "tenancyId") FROM stdin;
7b0b56a1-d75d-49bf-991d-487854eaaac1	00bb639d-a1ac-4cdf-a53f-c76f377d21b5	2025-05-26 20:38:39.797	2025-05-26 20:38:39.797	$2b$10$/zjDeI6Lk3GMpr.t9GVopeqEkj8xVY3EDOj1unw3gT4z33TkCaChO	584e6236-ce23-4184-9a88-e9f1338f051f
\.


--
-- Data for Name: PasswordAuthMethodConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."PasswordAuthMethodConfig" ("projectConfigId", "authMethodConfigId", "createdAt", "updatedAt") FROM stdin;
284779e6-3793-445b-93f5-d5946ee98c37	10ebf684-5a65-4c4c-8a18-171f8f300b1b	2025-05-26 20:37:49.174	2025-05-26 20:37:49.174
64154b84-50b0-4536-81be-68ab193adc7b	503a9494-dea5-4317-a928-9b92842b9b90	2025-05-26 20:39:16.257	2025-05-26 20:39:16.257
\.


--
-- Data for Name: Permission; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."Permission" ("queryableId", "dbId", "projectConfigId", "teamId", "createdAt", "updatedAt", description, scope, "isDefaultTeamCreatorPermission", "isDefaultTeamMemberPermission", "tenancyId", "isDefaultProjectPermission") FROM stdin;
member	80f828d8-49fd-41cf-8976-ed4a2ab508a3	64154b84-50b0-4536-81be-68ab193adc7b	\N	2025-05-26 20:39:16.261	2025-05-26 20:39:16.261	Default permission for team members	TEAM	f	t	84f518dc-6c53-41d7-9a0e-52d6220ee90d	f
admin	52d239fe-5fcc-4087-80d6-3b292804310f	64154b84-50b0-4536-81be-68ab193adc7b	\N	2025-05-26 20:39:16.264	2025-05-26 20:39:16.264	Default permission for team creators	TEAM	t	f	84f518dc-6c53-41d7-9a0e-52d6220ee90d	f
\.


--
-- Data for Name: PermissionEdge; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."PermissionEdge" ("edgeId", "createdAt", "updatedAt", "parentPermissionDbId", "childPermissionDbId", "parentTeamSystemPermission") FROM stdin;
d6cd69a8-6476-466e-95d1-143028e24d3b	2025-05-26 20:39:16.261	2025-05-26 20:39:16.261	\N	80f828d8-49fd-41cf-8976-ed4a2ab508a3	READ_MEMBERS
8981efb8-1604-4678-91cd-3c6ace184088	2025-05-26 20:39:16.261	2025-05-26 20:39:16.261	\N	80f828d8-49fd-41cf-8976-ed4a2ab508a3	INVITE_MEMBERS
912e1017-d42b-4345-8328-4daf36780b4b	2025-05-26 20:39:16.264	2025-05-26 20:39:16.264	\N	52d239fe-5fcc-4087-80d6-3b292804310f	UPDATE_TEAM
48526b99-83c7-4499-b9c5-d179c296ea05	2025-05-26 20:39:16.264	2025-05-26 20:39:16.264	\N	52d239fe-5fcc-4087-80d6-3b292804310f	DELETE_TEAM
07f68565-31e1-48d4-b78f-b55a2502ef9a	2025-05-26 20:39:16.264	2025-05-26 20:39:16.264	\N	52d239fe-5fcc-4087-80d6-3b292804310f	READ_MEMBERS
1a8a3e2a-58fd-4272-ab0c-2098914bedef	2025-05-26 20:39:16.264	2025-05-26 20:39:16.264	\N	52d239fe-5fcc-4087-80d6-3b292804310f	REMOVE_MEMBERS
be1f728b-9d5b-4d88-a5fa-435271910ea4	2025-05-26 20:39:16.264	2025-05-26 20:39:16.264	\N	52d239fe-5fcc-4087-80d6-3b292804310f	INVITE_MEMBERS
b3e1102a-04a9-4eb5-8e2b-d47c04592b92	2025-05-26 20:39:16.264	2025-05-26 20:39:16.264	\N	52d239fe-5fcc-4087-80d6-3b292804310f	MANAGE_API_KEYS
\.


--
-- Data for Name: Project; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."Project" (id, "createdAt", "updatedAt", "displayName", description, "configId", "isProductionMode", "userCount") FROM stdin;
internal	2025-05-26 20:37:49.174	2025-05-26 20:37:49.174	Stack Dashboard	Stack's admin dashboard	284779e6-3793-445b-93f5-d5946ee98c37	f	1
a12651bb-7824-459d-b424-21a0950ab902	2025-05-26 20:39:16.247	2025-05-26 20:39:16.247	yapit		64154b84-50b0-4536-81be-68ab193adc7b	f	0
\.


--
-- Data for Name: ProjectApiKey; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProjectApiKey" ("projectId", "tenancyId", id, "secretApiKey", "createdAt", "updatedAt", "expiresAt", "manuallyRevokedAt", description, "isPublic", "teamId", "projectUserId") FROM stdin;
\.


--
-- Data for Name: ProjectConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProjectConfig" (id, "createdAt", "updatedAt", "allowLocalhost", "createTeamOnSignUp", "teamCreateDefaultSystemPermissions", "teamMemberDefaultSystemPermissions", "signUpEnabled", "clientTeamCreationEnabled", "clientUserDeletionEnabled", "legacyGlobalJwtSigning", "oauthAccountMergeStrategy", "allowTeamApiKeys", "allowUserApiKeys") FROM stdin;
284779e6-3793-445b-93f5-d5946ee98c37	2025-05-26 20:37:49.174	2025-05-26 20:37:49.174	t	f	\N	\N	t	f	f	f	LINK_METHOD	f	f
64154b84-50b0-4536-81be-68ab193adc7b	2025-05-26 20:39:16.247	2025-05-26 20:39:16.247	t	f	\N	\N	t	f	f	f	LINK_METHOD	f	f
\.


--
-- Data for Name: ProjectDomain; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProjectDomain" ("projectConfigId", "createdAt", "updatedAt", domain, "handlerPath") FROM stdin;
\.


--
-- Data for Name: ProjectUser; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProjectUser" ("projectUserId", "createdAt", "updatedAt", "profileImageUrl", "displayName", "serverMetadata", "clientMetadata", "requiresTotpMfa", "totpSecret", "clientReadOnlyMetadata", "tenancyId", "mirroredBranchId", "mirroredProjectId", "isAnonymous") FROM stdin;
00bb639d-a1ac-4cdf-a53f-c76f377d21b5	2025-05-26 20:38:39.782	2025-05-26 20:39:16.268	\N	\N	{"managedProjectIds": ["a12651bb-7824-459d-b424-21a0950ab902"]}	\N	f	\N	\N	584e6236-ce23-4184-9a88-e9f1338f051f	main	internal	f
\.


--
-- Data for Name: ProjectUserAuthorizationCode; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProjectUserAuthorizationCode" ("projectUserId", "createdAt", "updatedAt", "authorizationCode", "redirectUri", "expiresAt", "codeChallenge", "codeChallengeMethod", "newUser", "afterCallbackRedirectUrl", "tenancyId") FROM stdin;
\.


--
-- Data for Name: ProjectUserDirectPermission; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProjectUserDirectPermission" (id, "tenancyId", "projectUserId", "permissionDbId", "createdAt", "updatedAt") FROM stdin;
\.


--
-- Data for Name: ProjectUserOAuthAccount; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProjectUserOAuthAccount" ("projectUserId", "projectConfigId", "oauthProviderConfigId", "createdAt", "updatedAt", email, "providerAccountId", "tenancyId") FROM stdin;
\.


--
-- Data for Name: ProjectUserRefreshToken; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProjectUserRefreshToken" ("projectUserId", "createdAt", "updatedAt", "refreshToken", "expiresAt", "tenancyId", id, "isImpersonation") FROM stdin;
00bb639d-a1ac-4cdf-a53f-c76f377d21b5	2025-05-26 20:38:39.858	2025-05-26 20:38:39.858	j7wd2pjkcbbmv7g1t80hj8x92y2k610wfye9y2ydehjs8	2026-05-26 20:38:39.857	584e6236-ce23-4184-9a88-e9f1338f051f	babbb6ea-e666-41d1-9220-e948156fb242	f
\.


--
-- Data for Name: ProjectWrapperCodes; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProjectWrapperCodes" ("idpId", id, "interactionUid", "authorizationCode", "cdfcResult") FROM stdin;
\.


--
-- Data for Name: ProxiedEmailServiceConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProxiedEmailServiceConfig" ("projectConfigId", "createdAt", "updatedAt") FROM stdin;
284779e6-3793-445b-93f5-d5946ee98c37	2025-05-26 20:37:49.174	2025-05-26 20:37:49.174
64154b84-50b0-4536-81be-68ab193adc7b	2025-05-26 20:39:16.247	2025-05-26 20:39:16.247
\.


--
-- Data for Name: ProxiedOAuthProviderConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."ProxiedOAuthProviderConfig" ("projectConfigId", id, "createdAt", "updatedAt", type) FROM stdin;
\.


--
-- Data for Name: SentEmail; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."SentEmail" ("tenancyId", id, "userId", "createdAt", "updatedAt", "senderConfig", "to", subject, html, text, error) FROM stdin;
\.


--
-- Data for Name: StandardEmailServiceConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."StandardEmailServiceConfig" ("projectConfigId", "createdAt", "updatedAt", "senderEmail", host, port, username, password, "senderName") FROM stdin;
\.


--
-- Data for Name: StandardOAuthProviderConfig; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."StandardOAuthProviderConfig" ("projectConfigId", id, "createdAt", "updatedAt", type, "clientId", "clientSecret", "facebookConfigId", "microsoftTenantId") FROM stdin;
\.


--
-- Data for Name: Team; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."Team" ("teamId", "createdAt", "updatedAt", "displayName", "profileImageUrl", "clientMetadata", "clientReadOnlyMetadata", "serverMetadata", "tenancyId", "mirroredBranchId", "mirroredProjectId") FROM stdin;
\.


--
-- Data for Name: TeamMember; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."TeamMember" ("projectUserId", "teamId", "createdAt", "updatedAt", "isSelected", "displayName", "profileImageUrl", "tenancyId") FROM stdin;
\.


--
-- Data for Name: TeamMemberDirectPermission; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."TeamMemberDirectPermission" ("projectUserId", "teamId", "permissionDbId", "createdAt", "updatedAt", id, "systemPermission", "tenancyId") FROM stdin;
\.


--
-- Data for Name: Tenancy; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."Tenancy" (id, "createdAt", "updatedAt", "projectId", "branchId", "organizationId", "hasNoOrganization") FROM stdin;
584e6236-ce23-4184-9a88-e9f1338f051f	2025-05-26 20:37:49.174	2025-05-26 20:37:49.174	internal	main	\N	TRUE
84f518dc-6c53-41d7-9a0e-52d6220ee90d	2025-05-26 20:39:16.255	2025-05-26 20:39:16.255	a12651bb-7824-459d-b424-21a0950ab902	main	\N	TRUE
\.


--
-- Data for Name: VerificationCode; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public."VerificationCode" ("projectId", id, "createdAt", "updatedAt", type, code, "expiresAt", "usedAt", "redirectUrl", data, method, "attemptCount", "branchId") FROM stdin;
internal	acdcbd3c-ebc6-426f-91a0-e2b3a85b9b4b	2025-05-26 20:38:39.858	2025-05-26 20:38:39.858	CONTACT_CHANNEL_VERIFICATION	amfbc7gv0w2z1zsw2xmsnmn9qnp1wn946qvsnhbprah28	2025-06-02 20:38:39.857	\N	http://localhost:8101/handler/email-verification?after_auth_return_to=%2Fhandler%2Fsign-in	{"user_id": "00bb639d-a1ac-4cdf-a53f-c76f377d21b5"}	{"email": "dev@yap.it"}	0	main
\.


--
-- Data for Name: _prisma_migrations; Type: TABLE DATA; Schema: public; Owner: yapit
--

COPY public._prisma_migrations (id, checksum, finished_at, migration_name, logs, rolled_back_at, started_at, applied_steps_count) FROM stdin;
8efd0dfc-f536-46bd-b51a-9837b0f113cd	c32e8dd678e59bb73976fc1b97a6d8fa6de1a3d6157c3fe13f852b8ac00257d4	2025-05-26 20:37:48.167473+00	20240809231417_disable_sign_up	\N	\N	2025-05-26 20:37:48.162837+00	1
a85d7857-c1a0-403e-affe-c5ddbdbacc33	5d08e4046489742447092caf0c9e06659670c0fc366ad56a5544ead32d23d1f0	2025-05-26 20:37:47.897702+00	20240306152532_initial_migration	\N	\N	2025-05-26 20:37:47.738692+00	1
a53bacf9-bb73-4e94-937d-1b56b7f7ae17	43747be799875262feba603bff6766009a8ca1a5f52ad10f96f145d0369ef133	2025-05-26 20:37:48.099573+00	20240707043509_team_profile_image	\N	\N	2025-05-26 20:37:48.095911+00	1
df0862d1-2dad-4622-abca-0ac5b1899e16	a4f805aab83a194279a8f9ead8e1dd5cb1319c846ea4e95ee0ebf671030a0757	2025-05-26 20:37:47.90252+00	20240313024014_authroization_code_new_user	\N	\N	2025-05-26 20:37:47.898845+00	1
1bac8cfb-ccb8-46eb-994f-0cd83367ca8e	d047d716ae0c6b6c2ebf151528273d5d04c56f66671c293b23c42eb27eaae536	2025-05-26 20:37:47.92044+00	20240418090527_magic_link	\N	\N	2025-05-26 20:37:47.903629+00	1
2ddd906d-4635-4902-99c9-1d504af82520	b0cc6c1e3a479397ac1cc1a2ce151db14845d9f9787a44ea8064429239ecb02a	2025-05-26 20:37:47.985048+00	20240507195652_team	\N	\N	2025-05-26 20:37:47.921719+00	1
53d9dc67-1611-4066-8954-8e0c6387699b	825fb4daa6f400142e959037d51e3070b4642f13c2fef0ac932029e0bf83c768	2025-05-26 20:37:48.115403+00	20240714031259_more_backend_endpoints	\N	\N	2025-05-26 20:37:48.100612+00	1
e30e9eb3-84c6-4d67-9edb-f3b893b83f52	bf0de509369c8281d48ce1025e54b27d40c64f4749dfc5c111cfbcde250dabb2	2025-05-26 20:37:47.992593+00	20240518151916_email_config	\N	\N	2025-05-26 20:37:47.987591+00	1
c564dba9-76f7-4454-b298-10e8ba537a5e	43e3c616fd0281e10d5cb3162c14aa3aa996cf28c8aed5c136020b3d2bd15c90	2025-05-26 20:37:47.998832+00	20240520152704_selected_team	\N	\N	2025-05-26 20:37:47.993714+00	1
df21ceec-9a4f-4c69-b368-c8029d069350	3ada085fc5f4a2ca8048645b4589d8356c7683e55ad0b215bcafe5ce51773a15	2025-05-26 20:37:48.348042+00	20240904155848_add_bitbucket_oauth	\N	\N	2025-05-26 20:37:48.343835+00	1
d42da096-22cb-4324-9bf4-5c52e6686dfd	5721a3620da63a258581a2145f0954fd9cade12e95573b62ea0aea85993529b5	2025-05-26 20:37:48.011924+00	20240528090210_email_templates	\N	\N	2025-05-26 20:37:48.000007+00	1
6fb9d6c8-6483-4bd8-9c0d-f82661820973	7c495c03d7073013623a9892b640653b446f4a758371ee1258b73e654fb44fb6	2025-05-26 20:37:48.126403+00	20240722004703_events	\N	\N	2025-05-26 20:37:48.116471+00	1
f219f77f-d529-4c43-a973-32bc98a0a79b	49a8ee89b1a9f0f1fe234df65bc1e8dcefccd6226dd2edd71345b402d00014ef	2025-05-26 20:37:48.016629+00	20240529121811_spotify_oauth	\N	\N	2025-05-26 20:37:48.012898+00	1
4d70370d-adbd-4516-9a42-39d1aeabb0ba	aa7334ec6d72a7a30c78b89943ed28aa7671086ceda62d8b5ec6537d596cfc82	2025-05-26 20:37:48.030867+00	20240608142105_oauth_access_token	\N	\N	2025-05-26 20:37:48.01836+00	1
3e9d8c62-37d9-4261-afeb-a31fe1f96a22	c7e8a15241fb0f87c3061c6f03ca2eb8358bab588a206c13440a1ce5a3375a48	2025-05-26 20:37:48.173461+00	20240810052738_multi_factor_authentication	\N	\N	2025-05-26 20:37:48.168659+00	1
69abecd3-cceb-410c-80a8-4223ac86c685	86ef2780c8bd6a1f1db5acae3d021ab065faa636f60a30a8c0be4ce240741b48	2025-05-26 20:37:48.042335+00	20240610085756_outer_oauth_info	\N	\N	2025-05-26 20:37:48.031962+00	1
19ca17e7-a72c-4f68-b097-3bf9d7401e0d	03ffed8ca8ecbe544d1394e5ba90cfadaf7d82b85b37ff12af9434d3177689fb	2025-05-26 20:37:48.130728+00	20240725161939_team_profiles	\N	\N	2025-05-26 20:37:48.12749+00	1
bdff80ec-8b02-495e-bc7f-6d36570359db	3a61c29e746af229f7471eec1de0a5499bbd7f6d0bffe4deb62a87a11ad55a02	2025-05-26 20:37:48.063256+00	20240618150845_system_team_permission	\N	\N	2025-05-26 20:37:48.043571+00	1
c68dc754-fd03-47f0-98e6-406a40404097	0696403c4a7379a0537c2ec4aa4230108ff58936e801589952b0f2803fdf6ccf	2025-05-26 20:37:48.080638+00	20240701161229_fix_selected_team_and_added_ondelete	\N	\N	2025-05-26 20:37:48.064329+00	1
e137c084-868a-4eb3-a7b4-75960a2c7f7f	524dc582483110e81f8ac86e5c89cfe1446d9c7737c936bb3667f81c402e4542	2025-05-26 20:37:48.094914+00	20240702050143_verification_codes	\N	\N	2025-05-26 20:37:48.08162+00	1
3d5a7467-329e-49df-9448-a820d190d77d	936e7df9d22e10753f4518f9270984fac955347d8d49bf73929e84a6339bd078	2025-05-26 20:37:48.135307+00	20240726225154_facebook_config_id	\N	\N	2025-05-26 20:37:48.131813+00	1
389a695c-7ecc-4b95-b33b-14ddfe2e62ad	4b66330d33b3f474cfb482b89512ccb8087df501a318d1b1f6e452f9a8c368dd	2025-05-26 20:37:48.207772+00	20240823172201_gitlab_oauth	\N	\N	2025-05-26 20:37:48.204152+00	1
95a793ed-7811-4489-a901-1d127d6f94bd	ce19bc90c0690c413921b661a25c260578862656cda9484055b2297389b9618c	2025-05-26 20:37:48.148748+00	20240730175523_oauth_access_token	\N	\N	2025-05-26 20:37:48.136439+00	1
d19b5d08-23a8-401f-b3b4-e2421ca3ba14	d222dad402c946baa728329372af5824f5158ec4950843ff23661a57cbaf8e9a	2025-05-26 20:37:48.178954+00	20240811194548_client_team_creation	\N	\N	2025-05-26 20:37:48.174762+00	1
1026f8d6-8804-42ce-9760-ffc3314ddf7c	d9dd963ce039cdf0c7030be4ebf4373796a4f4cbc25a4c5abe72953b3821bdee	2025-05-26 20:37:48.155472+00	20240802011240_password_reset_verification	\N	\N	2025-05-26 20:37:48.149896+00	1
4ef67306-ede8-4adb-8dd4-8789f9e92b49	db4d77573d02099717ee4e88e750b9e96d603e6d9f110e81e6645440eab7a5ad	2025-05-26 20:37:48.160408+00	20240804210316_team_invitation	\N	\N	2025-05-26 20:37:48.156674+00	1
f40221ce-bbe0-4539-ad18-f4bb99a903d5	598004b140463cf727c214541813c322c56c682fc9a5b55ec61383fe5bd031d1	2025-05-26 20:37:48.194136+00	20240812013545_project_on_delete	\N	\N	2025-05-26 20:37:48.180114+00	1
fcec22d3-b397-4b6d-a69b-05e623b2fb0c	13bda56991b9c269805ca4c8e68c28442c4d27db462f6815b75995366ebf9c81	2025-05-26 20:37:48.212552+00	20240830010429_event_index	\N	\N	2025-05-26 20:37:48.208759+00	1
7ffca942-c44a-43f7-8509-e84e1ac249ec	01b0c215bc3fc6ff5f13a800ad0e23c17c765243f3b38c7c45e13274b27bedf9	2025-05-26 20:37:48.198325+00	20240815125620_discord_oauth	\N	\N	2025-05-26 20:37:48.195191+00	1
b50ab72e-5c44-48fe-845f-9dc49cd8a6f9	0094474d9d018e14f98af1fe299f1ae165e239ebe9c1d74614d7919302969786	2025-05-26 20:37:48.203161+00	20240820045300_client_read_only_metadata	\N	\N	2025-05-26 20:37:48.199291+00	1
f62dae04-d985-4417-b0f0-f263a5b5f280	f00da6749eabcb61f67bceb9c73432b450c59d1d2fab853d4941ba1a3de2999b	2025-05-26 20:37:48.386268+00	20240912185510_password_auth_unique_key	\N	\N	2025-05-26 20:37:48.379436+00	1
5e552b98-ca13-4775-92d7-5018c845d59f	9b85d161338bfc52180e62f069f2b5b05bd3cecdd273c135058444f8605d1e39	2025-05-26 20:37:48.339485+00	20240901224341_connected_account	\N	\N	2025-05-26 20:37:48.213836+00	1
24ffe26c-585c-4aa3-b0af-b7e9355b163d	044e4c37c0e4ec84c7a8965d9836047806ab7171c853212cd17860be30ec1652	2025-05-26 20:37:48.378467+00	20240910211533_remove_shared_facebook	\N	\N	2025-05-26 20:37:48.362736+00	1
25efee06-7b30-4954-b066-6c1a772e7927	5b6af0341bcb0a144e9283e4d5bca7cca2e1c2bd9bd6cf30f87dab72ea8aea67	2025-05-26 20:37:48.352259+00	20240905201445_ms_tenant	\N	\N	2025-05-26 20:37:48.349093+00	1
d0b08f55-87f3-4fa4-8f90-cb25cb3f870f	2efa2d43c4c9fee2e2c71f0b28d6e1cf2d8fdf81c2283ea69924a28c1ce23083	2025-05-26 20:37:48.361827+00	20240909201430_project_on_delete	\N	\N	2025-05-26 20:37:48.353228+00	1
a2e83940-8231-4e92-a839-363936e50b18	cde0dc09a7d34f816cd51040dd2daef4e835746a9dd27da7dd4ea55474929c93	2025-05-26 20:37:48.39024+00	20240912212547_linkedin_oauth	\N	\N	2025-05-26 20:37:48.387177+00	1
61608406-83d5-4bde-b246-6946ead00acb	d356c98c4c693d5405055f4e78c23896b7d3d4d954831bd4bc8b6789e4a42157	2025-05-26 20:37:48.394261+00	20240914210306_apple_oauth	\N	\N	2025-05-26 20:37:48.391222+00	1
a528173e-0871-455f-be40-98d5ecdc8efa	5e3698741d0f99e3ed3764241a88cf0ee039e32ac9e03449d6d101b684bfc0d0	2025-05-26 20:37:48.398699+00	20240917182207_account_deletion	\N	\N	2025-05-26 20:37:48.395171+00	1
ecc8808b-3e25-48ec-949c-7bfb4b601f6f	072837a45f3cca1b4d0e90f5f89360a6660b9f8090b8c7cb9fa14d7acc71af26	2025-05-26 20:37:48.402453+00	20240919223009_x_and_slack_oauth	\N	\N	2025-05-26 20:37:48.399677+00	1
5a265ab3-0f56-4127-8099-1d609b28afe4	89848f2b62d81c93771e113b0971a874d1c42b83801a8af403c24368d26120cf	2025-05-26 20:37:48.407844+00	20240923165906_otp_attempts	\N	\N	2025-05-26 20:37:48.403365+00	1
2dc62e55-5590-4fae-a0e6-da141fd86acd	3de5136e016790890670c93b84b495dc9826138916659c3c3e71bfc4f802a690	2025-05-26 20:37:48.856033+00	20250225200857_add_another	\N	\N	2025-05-26 20:37:48.849006+00	1
74426a15-0136-46a3-b129-cd50f07126d2	4cb54da8cbfc4b981c3eb7486b9206621829092b2ea555d58b354312f1f606ec	2025-05-26 20:37:48.428411+00	20240929194058_remove_otp_contact_channel	\N	\N	2025-05-26 20:37:48.408776+00	1
2b8415db-4471-474c-92dd-34f199956d3f	4f8ab8f0d13919aed6b6921e435ec30211a46c2816b390be0ac2b35c90efb7c6	2025-05-26 20:37:48.580169+00	20241223231023_onlyhttps_domains	\N	\N	2025-05-26 20:37:48.573439+00	1
33062b7d-a6e4-4fc7-9ded-20ce3ebcfc90	6f3073ebc5544a2cfdde6da321aaac296ad612bc7c57742d0924747c149da5ce	2025-05-26 20:37:48.432912+00	20241007162201_legacy_jwt	\N	\N	2025-05-26 20:37:48.429339+00	1
e5aae332-6389-43a0-a6c5-a373164d0139	2dd8857cf2914135078dde654f402dd007ea5e06f6acc4cf7ef5d782aa1cdf83	2025-05-26 20:37:48.437264+00	20241013185548_remove_client_id_unique	\N	\N	2025-05-26 20:37:48.433848+00	1
aa46b966-c5c0-4794-a688-c9f78e69a013	b9218bf6144416e34b3d78187223f8101f80b5bda44d4f0152358eb499884e23	2025-05-26 20:37:48.461+00	20241024234115_passkey_support	\N	\N	2025-05-26 20:37:48.438249+00	1
942ccf78-7d7e-46ed-aaeb-8b3b27f11762	85a62df34e422bd3cb1d8a8e6507532eba5f83b8d230d48e9c30f215e5a49def	2025-05-26 20:37:48.589586+00	20241228033652_more_event_indices	\N	\N	2025-05-26 20:37:48.58279+00	1
3554b362-f69b-4810-9b5d-8b9d98ae047d	8097023d037e78aef72b7192574ec5aa82f875b75fe3f0686c96acdd8b2329ed	2025-05-26 20:37:48.478095+00	20241026024655_user_sorting_indices	\N	\N	2025-05-26 20:37:48.46199+00	1
eb23a8bd-880d-4d8f-8379-df5bb3d2141e	630f051973f689a471005cee4ad45b55a72d0fa41def439233406edf57c51479	2025-05-26 20:37:48.491885+00	20241116221711_geolocation_events	\N	\N	2025-05-26 20:37:48.479027+00	1
4b42c71c-e9ce-4359-9011-698fea426eef	6655f5dfbdd7525bd19185cc10e1fc8e71fd56727e2230ab9e777e2f2473c796	2025-05-26 20:37:48.964115+00	20250401220515_permission_unique_constraint	\N	\N	2025-05-26 20:37:48.95528+00	1
c109853e-db88-4cbf-a21f-280d802bda13	ce39b44003692d714167484ed031c396ac3430eef9d68f0651a1af7636fe728c	2025-05-26 20:37:48.496996+00	20241124163535_verification_code_handler_index	\N	\N	2025-05-26 20:37:48.493131+00	1
664edf3d-45db-4752-8202-4f8c85463e63	5ac67ffd340f7b06f8ce355dfaea55b8a8ec4b92f49b387bf2cdd8c228aa5a8c	2025-05-26 20:37:48.776445+00	20250206063807_tenancies	\N	\N	2025-05-26 20:37:48.590931+00	1
2b6f9c8b-c415-49a5-8879-d8f4f5e8bf09	705fa11b88ae2c1a47092638b6f4d400ab1761e0e9705818e7f8a17111838af7	2025-05-26 20:37:48.5327+00	20241201043500_idp	\N	\N	2025-05-26 20:37:48.498053+00	1
38a02445-f06c-4071-865d-fc866504a2ba	e386e6ff401d9db00fa09c13983c02a361bfe8df7b2c10d24121e72064fd078a	2025-05-26 20:37:48.547042+00	20241207223510_neon_project_transfers	\N	\N	2025-05-26 20:37:48.53605+00	1
b3e06772-dbcf-4f95-af58-298a3fbda9d7	b327093bbb42c91303be6450b55efc4c567785d051522db81b9aa2d752c639ae	2025-05-26 20:37:48.861384+00	20250227004548_make_project_description_non_nullable	\N	\N	2025-05-26 20:37:48.85705+00	1
e13e8fa4-80b1-42cf-baa6-1ef9f98d6489	9ab8854d492c97034bf7b24c08f90f883c99906bc485349d3745fe8e450d9d90	2025-05-26 20:37:48.56+00	20241220033652_event_indices	\N	\N	2025-05-26 20:37:48.548028+00	1
2b54c018-b642-4721-b215-8771f9b8eea4	96945fac5bf8c1b8e7dd9402f1d0e2d943af6ca24afe3feeebd71845c17f05b0	2025-05-26 20:37:48.78421+00	20250206073652_branch_event_indices	\N	\N	2025-05-26 20:37:48.777393+00	1
a8b6a333-107e-4418-a0c0-9852a2714f91	fee9837e04e1e15c6bb0255e1bad39e49dbcba3a530483585431860a3ee87f7b	2025-05-26 20:37:48.564445+00	20241223205737_remove_empty_profile_images	\N	\N	2025-05-26 20:37:48.561077+00	1
5ead7948-91b8-4c53-a94d-e3770a70dcf8	0db57158122c719d9445cc78ea5f8bd956d5e3d148f7fec16829bd45cd3e9047	2025-05-26 20:37:48.568719+00	20241223225110_fill_empty_project_config_values	\N	\N	2025-05-26 20:37:48.565772+00	1
c3092ea3-d105-45d5-9a72-0807d4d7be66	f3ef012f36dbe25c1f7316c2fe9d01de4d6a2eeb7f0013e2e40f447fb6b1d082	2025-05-26 20:37:48.572493+00	20241223231022_remove_empty_team_profile_images	\N	\N	2025-05-26 20:37:48.569764+00	1
a323e6da-3f5f-45f2-8aba-9a4fcff2e15d	ddc09fedfd43b4f3e89587960cdb2e14eae0df1c2e9ac7ab50aa0091220f6f62	2025-05-26 20:37:48.808984+00	20250207071519_tenancies_finalization	\N	\N	2025-05-26 20:37:48.78556+00	1
69cf33e7-42d4-4183-8509-49c863659acb	387bbea262e37525fd420a16236f83bbac76f708ac8b86c3257f30bde3bde2a1	2025-05-26 20:37:48.907506+00	20250320223454_anonymous_users	\N	\N	2025-05-26 20:37:48.903939+00	1
c82c3947-3a1b-4360-8c91-d3069e7ab873	09a64d9a45f52b2e8a3a9636c9150dd1d5b56208dc17d75345f14d4cd559ad2e	2025-05-26 20:37:48.827938+00	20250214175437_create_user_indices	\N	\N	2025-05-26 20:37:48.809902+00	1
6910370f-5350-4e4d-974e-28515643f6bf	1a73e8fee21ff77f25836ac25b7755a931860222a56020c1112f5cd5ab7c8465	2025-05-26 20:37:48.880113+00	20250303231152_add_cli_auth	\N	\N	2025-05-26 20:37:48.862453+00	1
43a12664-32c0-46f8-8703-0efd24879ac4	67a88adf4d5af7349260b972f900d4bc3cf4bb4e8a023c535dc5c83c81b91620	2025-05-26 20:37:48.841143+00	20250221013242_sent_email_table	\N	\N	2025-05-26 20:37:48.829085+00	1
7171257c-fd9c-463d-81d9-998d45fbdb4d	3dcd65d52f58eacfe99165948439e1f4dcc4fcb00b4e69ea0cd88374d9936968	2025-05-26 20:37:48.847981+00	20250225200753_add_tenancy_cascade	\N	\N	2025-05-26 20:37:48.842093+00	1
c36cabab-e733-40c6-9dde-e3adca4bda70	01669161b9b0011733ee07ab611193600646cdbfb98ccdc7726adbeb70918679	2025-05-26 20:37:48.885456+00	20250304004231_merge_oauth_methods	\N	\N	2025-05-26 20:37:48.881083+00	1
34c72cb5-c8b6-47c1-8bfc-6b267bee0acd	2d9e8c665dfb03d0ea637ee5379973630b32f1e5c81857a187fb0a9b0314258c	2025-05-26 20:37:48.936049+00	20250325235813_project_user_permissions	\N	\N	2025-05-26 20:37:48.908526+00	1
6b08ebe7-b7e7-47f1-aff1-568fd6161079	7b5662ffb199e8525f081787db47b1db56385198e2b0174b3409102f5b4102a5	2025-05-26 20:37:48.891792+00	20250304200822_add_project_user_count	\N	\N	2025-05-26 20:37:48.886481+00	1
5a24bac0-6f92-47da-8412-f7e84422d636	b39fac212b1cc268fd122ce7e1753c0c2346579a75225c61bb3979e74cbf322e	2025-05-26 20:37:48.90297+00	20250310172256_add_id_and_impersonation_field	\N	\N	2025-05-26 20:37:48.893041+00	1
8425c00b-bf6b-458d-b6a1-0560bd9bbd84	ece2cca08dcd6a15bb446711b49965acfad5ff1cd42eb59ed0fd4ab3e0b87892	2025-05-26 20:37:48.954346+00	20250327194649_api_keys	\N	\N	2025-05-26 20:37:48.937029+00	1
\.


--
-- Name: ApiKeySet ApiKeySet_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ApiKeySet"
    ADD CONSTRAINT "ApiKeySet_pkey" PRIMARY KEY ("projectId", id);


--
-- Name: AuthMethodConfig AuthMethodConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."AuthMethodConfig"
    ADD CONSTRAINT "AuthMethodConfig_pkey" PRIMARY KEY ("projectConfigId", id);


--
-- Name: AuthMethod AuthMethod_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."AuthMethod"
    ADD CONSTRAINT "AuthMethod_pkey" PRIMARY KEY ("tenancyId", id);


--
-- Name: CliAuthAttempt CliAuthAttempt_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."CliAuthAttempt"
    ADD CONSTRAINT "CliAuthAttempt_pkey" PRIMARY KEY ("tenancyId", id);


--
-- Name: ConnectedAccountConfig ConnectedAccountConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ConnectedAccountConfig"
    ADD CONSTRAINT "ConnectedAccountConfig_pkey" PRIMARY KEY ("projectConfigId", id);


--
-- Name: ConnectedAccount ConnectedAccount_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ConnectedAccount"
    ADD CONSTRAINT "ConnectedAccount_pkey" PRIMARY KEY ("tenancyId", id);


--
-- Name: ContactChannel ContactChannel_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ContactChannel"
    ADD CONSTRAINT "ContactChannel_pkey" PRIMARY KEY ("tenancyId", "projectUserId", id);


--
-- Name: EmailServiceConfig EmailServiceConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."EmailServiceConfig"
    ADD CONSTRAINT "EmailServiceConfig_pkey" PRIMARY KEY ("projectConfigId");


--
-- Name: EmailTemplate EmailTemplate_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."EmailTemplate"
    ADD CONSTRAINT "EmailTemplate_pkey" PRIMARY KEY ("projectConfigId", type);


--
-- Name: EventIpInfo EventIpInfo_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."EventIpInfo"
    ADD CONSTRAINT "EventIpInfo_pkey" PRIMARY KEY (id);


--
-- Name: Event Event_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Event"
    ADD CONSTRAINT "Event_pkey" PRIMARY KEY (id);


--
-- Name: IdPAccountToCdfcResultMapping IdPAccountToCdfcResultMapping_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."IdPAccountToCdfcResultMapping"
    ADD CONSTRAINT "IdPAccountToCdfcResultMapping_pkey" PRIMARY KEY ("idpId", id);


--
-- Name: IdPAdapterData IdPAdapterData_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."IdPAdapterData"
    ADD CONSTRAINT "IdPAdapterData_pkey" PRIMARY KEY ("idpId", model, id);


--
-- Name: NeonProvisionedProject NeonProvisionedProject_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."NeonProvisionedProject"
    ADD CONSTRAINT "NeonProvisionedProject_pkey" PRIMARY KEY ("projectId");


--
-- Name: OAuthAccessToken OAuthAccessToken_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthAccessToken"
    ADD CONSTRAINT "OAuthAccessToken_pkey" PRIMARY KEY (id);


--
-- Name: OAuthAuthMethod OAuthAuthMethod_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthAuthMethod"
    ADD CONSTRAINT "OAuthAuthMethod_pkey" PRIMARY KEY ("tenancyId", "authMethodId");


--
-- Name: OAuthOuterInfo OAuthOuterInfo_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthOuterInfo"
    ADD CONSTRAINT "OAuthOuterInfo_pkey" PRIMARY KEY (id);


--
-- Name: OAuthProviderConfig OAuthProviderConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthProviderConfig"
    ADD CONSTRAINT "OAuthProviderConfig_pkey" PRIMARY KEY ("projectConfigId", id);


--
-- Name: OAuthToken OAuthToken_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthToken"
    ADD CONSTRAINT "OAuthToken_pkey" PRIMARY KEY (id);


--
-- Name: OtpAuthMethodConfig OtpAuthMethodConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OtpAuthMethodConfig"
    ADD CONSTRAINT "OtpAuthMethodConfig_pkey" PRIMARY KEY ("projectConfigId", "authMethodConfigId");


--
-- Name: OtpAuthMethod OtpAuthMethod_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OtpAuthMethod"
    ADD CONSTRAINT "OtpAuthMethod_pkey" PRIMARY KEY ("tenancyId", "authMethodId");


--
-- Name: PasskeyAuthMethodConfig PasskeyAuthMethodConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasskeyAuthMethodConfig"
    ADD CONSTRAINT "PasskeyAuthMethodConfig_pkey" PRIMARY KEY ("projectConfigId", "authMethodConfigId");


--
-- Name: PasskeyAuthMethod PasskeyAuthMethod_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasskeyAuthMethod"
    ADD CONSTRAINT "PasskeyAuthMethod_pkey" PRIMARY KEY ("tenancyId", "authMethodId");


--
-- Name: PasswordAuthMethodConfig PasswordAuthMethodConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasswordAuthMethodConfig"
    ADD CONSTRAINT "PasswordAuthMethodConfig_pkey" PRIMARY KEY ("projectConfigId", "authMethodConfigId");


--
-- Name: PasswordAuthMethod PasswordAuthMethod_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasswordAuthMethod"
    ADD CONSTRAINT "PasswordAuthMethod_pkey" PRIMARY KEY ("tenancyId", "authMethodId");


--
-- Name: PermissionEdge PermissionEdge_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PermissionEdge"
    ADD CONSTRAINT "PermissionEdge_pkey" PRIMARY KEY ("edgeId");


--
-- Name: Permission Permission_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Permission"
    ADD CONSTRAINT "Permission_pkey" PRIMARY KEY ("dbId");


--
-- Name: ProjectApiKey ProjectApiKey_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectApiKey"
    ADD CONSTRAINT "ProjectApiKey_pkey" PRIMARY KEY ("tenancyId", id);


--
-- Name: ProjectConfig ProjectConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectConfig"
    ADD CONSTRAINT "ProjectConfig_pkey" PRIMARY KEY (id);


--
-- Name: ProjectUserAuthorizationCode ProjectUserAuthorizationCode_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserAuthorizationCode"
    ADD CONSTRAINT "ProjectUserAuthorizationCode_pkey" PRIMARY KEY ("tenancyId", "authorizationCode");


--
-- Name: ProjectUserDirectPermission ProjectUserDirectPermission_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserDirectPermission"
    ADD CONSTRAINT "ProjectUserDirectPermission_pkey" PRIMARY KEY (id);


--
-- Name: ProjectUserOAuthAccount ProjectUserOAuthAccount_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserOAuthAccount"
    ADD CONSTRAINT "ProjectUserOAuthAccount_pkey" PRIMARY KEY ("tenancyId", "oauthProviderConfigId", "providerAccountId");


--
-- Name: ProjectUserRefreshToken ProjectUserRefreshToken_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserRefreshToken"
    ADD CONSTRAINT "ProjectUserRefreshToken_pkey" PRIMARY KEY ("tenancyId", id);


--
-- Name: ProjectUser ProjectUser_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUser"
    ADD CONSTRAINT "ProjectUser_pkey" PRIMARY KEY ("tenancyId", "projectUserId");


--
-- Name: ProjectWrapperCodes ProjectWrapperCodes_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectWrapperCodes"
    ADD CONSTRAINT "ProjectWrapperCodes_pkey" PRIMARY KEY ("idpId", id);


--
-- Name: Project Project_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Project"
    ADD CONSTRAINT "Project_pkey" PRIMARY KEY (id);


--
-- Name: ProxiedEmailServiceConfig ProxiedEmailServiceConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProxiedEmailServiceConfig"
    ADD CONSTRAINT "ProxiedEmailServiceConfig_pkey" PRIMARY KEY ("projectConfigId");


--
-- Name: ProxiedOAuthProviderConfig ProxiedOAuthProviderConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProxiedOAuthProviderConfig"
    ADD CONSTRAINT "ProxiedOAuthProviderConfig_pkey" PRIMARY KEY ("projectConfigId", id);


--
-- Name: SentEmail SentEmail_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."SentEmail"
    ADD CONSTRAINT "SentEmail_pkey" PRIMARY KEY ("tenancyId", id);


--
-- Name: StandardEmailServiceConfig StandardEmailServiceConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."StandardEmailServiceConfig"
    ADD CONSTRAINT "StandardEmailServiceConfig_pkey" PRIMARY KEY ("projectConfigId");


--
-- Name: StandardOAuthProviderConfig StandardOAuthProviderConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."StandardOAuthProviderConfig"
    ADD CONSTRAINT "StandardOAuthProviderConfig_pkey" PRIMARY KEY ("projectConfigId", id);


--
-- Name: TeamMemberDirectPermission TeamMemberDirectPermission_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."TeamMemberDirectPermission"
    ADD CONSTRAINT "TeamMemberDirectPermission_pkey" PRIMARY KEY (id);


--
-- Name: TeamMember TeamMember_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."TeamMember"
    ADD CONSTRAINT "TeamMember_pkey" PRIMARY KEY ("tenancyId", "projectUserId", "teamId");


--
-- Name: Team Team_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Team"
    ADD CONSTRAINT "Team_pkey" PRIMARY KEY ("tenancyId", "teamId");


--
-- Name: Tenancy Tenancy_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Tenancy"
    ADD CONSTRAINT "Tenancy_pkey" PRIMARY KEY (id);


--
-- Name: VerificationCode VerificationCode_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."VerificationCode"
    ADD CONSTRAINT "VerificationCode_pkey" PRIMARY KEY ("projectId", "branchId", id);


--
-- Name: _prisma_migrations _prisma_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public._prisma_migrations
    ADD CONSTRAINT _prisma_migrations_pkey PRIMARY KEY (id);


--
-- Name: ApiKeySet_publishableClientKey_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ApiKeySet_publishableClientKey_key" ON public."ApiKeySet" USING btree ("publishableClientKey");


--
-- Name: ApiKeySet_secretServerKey_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ApiKeySet_secretServerKey_key" ON public."ApiKeySet" USING btree ("secretServerKey");


--
-- Name: ApiKeySet_superSecretAdminKey_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ApiKeySet_superSecretAdminKey_key" ON public."ApiKeySet" USING btree ("superSecretAdminKey");


--
-- Name: AuthMethod_tenancyId_projectUserId_idx; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "AuthMethod_tenancyId_projectUserId_idx" ON public."AuthMethod" USING btree ("tenancyId", "projectUserId");


--
-- Name: CliAuthAttempt_loginCode_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "CliAuthAttempt_loginCode_key" ON public."CliAuthAttempt" USING btree ("loginCode");


--
-- Name: CliAuthAttempt_pollingCode_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "CliAuthAttempt_pollingCode_key" ON public."CliAuthAttempt" USING btree ("pollingCode");


--
-- Name: ConnectedAccount_tenancyId_oauthProviderConfigId_providerAc_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ConnectedAccount_tenancyId_oauthProviderConfigId_providerAc_key" ON public."ConnectedAccount" USING btree ("tenancyId", "oauthProviderConfigId", "providerAccountId");


--
-- Name: ContactChannel_tenancyId_projectUserId_type_isPrimary_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ContactChannel_tenancyId_projectUserId_type_isPrimary_key" ON public."ContactChannel" USING btree ("tenancyId", "projectUserId", type, "isPrimary");


--
-- Name: ContactChannel_tenancyId_projectUserId_type_value_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ContactChannel_tenancyId_projectUserId_type_value_key" ON public."ContactChannel" USING btree ("tenancyId", "projectUserId", type, value);


--
-- Name: ContactChannel_tenancyId_type_value_usedForAuth_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ContactChannel_tenancyId_type_value_usedForAuth_key" ON public."ContactChannel" USING btree ("tenancyId", type, value, "usedForAuth");


--
-- Name: Event_data_idx; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "Event_data_idx" ON public."Event" USING gin (data jsonb_path_ops);


--
-- Name: IdPAccountToCdfcResultMapping_idpAccountId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "IdPAccountToCdfcResultMapping_idpAccountId_key" ON public."IdPAccountToCdfcResultMapping" USING btree ("idpAccountId");


--
-- Name: IdPAdapterData_expiresAt_idx; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "IdPAdapterData_expiresAt_idx" ON public."IdPAdapterData" USING btree ("expiresAt");


--
-- Name: IdPAdapterData_payload_idx; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "IdPAdapterData_payload_idx" ON public."IdPAdapterData" USING gin (payload jsonb_path_ops);


--
-- Name: OAuthAuthMethod_tenancyId_oauthProviderConfigId_providerAcc_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "OAuthAuthMethod_tenancyId_oauthProviderConfigId_providerAcc_key" ON public."OAuthAuthMethod" USING btree ("tenancyId", "oauthProviderConfigId", "providerAccountId");


--
-- Name: OAuthOuterInfo_innerState_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "OAuthOuterInfo_innerState_key" ON public."OAuthOuterInfo" USING btree ("innerState");


--
-- Name: OAuthProviderConfig_projectConfigId_authMethodConfigId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "OAuthProviderConfig_projectConfigId_authMethodConfigId_key" ON public."OAuthProviderConfig" USING btree ("projectConfigId", "authMethodConfigId");


--
-- Name: OAuthProviderConfig_projectConfigId_connectedAccountConfigI_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "OAuthProviderConfig_projectConfigId_connectedAccountConfigI_key" ON public."OAuthProviderConfig" USING btree ("projectConfigId", "connectedAccountConfigId");


--
-- Name: OtpAuthMethod_tenancyId_projectUserId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "OtpAuthMethod_tenancyId_projectUserId_key" ON public."OtpAuthMethod" USING btree ("tenancyId", "projectUserId");


--
-- Name: PasskeyAuthMethod_tenancyId_projectUserId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "PasskeyAuthMethod_tenancyId_projectUserId_key" ON public."PasskeyAuthMethod" USING btree ("tenancyId", "projectUserId");


--
-- Name: PasswordAuthMethod_tenancyId_projectUserId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "PasswordAuthMethod_tenancyId_projectUserId_key" ON public."PasswordAuthMethod" USING btree ("tenancyId", "projectUserId");


--
-- Name: PermissionEdge_childPermissionDbId_idx; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "PermissionEdge_childPermissionDbId_idx" ON public."PermissionEdge" USING btree ("childPermissionDbId");


--
-- Name: PermissionEdge_parentPermissionDbId_idx; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "PermissionEdge_parentPermissionDbId_idx" ON public."PermissionEdge" USING btree ("parentPermissionDbId");


--
-- Name: Permission_projectConfigId_queryableId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "Permission_projectConfigId_queryableId_key" ON public."Permission" USING btree ("projectConfigId", "queryableId");


--
-- Name: Permission_tenancyId_queryableId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "Permission_tenancyId_queryableId_key" ON public."Permission" USING btree ("tenancyId", "queryableId");


--
-- Name: Permission_tenancyId_teamId_queryableId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "Permission_tenancyId_teamId_queryableId_key" ON public."Permission" USING btree ("tenancyId", "teamId", "queryableId");


--
-- Name: ProjectApiKey_secretApiKey_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ProjectApiKey_secretApiKey_key" ON public."ProjectApiKey" USING btree ("secretApiKey");


--
-- Name: ProjectDomain_projectConfigId_domain_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ProjectDomain_projectConfigId_domain_key" ON public."ProjectDomain" USING btree ("projectConfigId", domain);


--
-- Name: ProjectUserAuthorizationCode_authorizationCode_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ProjectUserAuthorizationCode_authorizationCode_key" ON public."ProjectUserAuthorizationCode" USING btree ("authorizationCode");


--
-- Name: ProjectUserDirectPermission_tenancyId_projectUserId_permiss_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ProjectUserDirectPermission_tenancyId_projectUserId_permiss_key" ON public."ProjectUserDirectPermission" USING btree ("tenancyId", "projectUserId", "permissionDbId");


--
-- Name: ProjectUserOAuthAccount_tenancyId_projectUserId_idx; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "ProjectUserOAuthAccount_tenancyId_projectUserId_idx" ON public."ProjectUserOAuthAccount" USING btree ("tenancyId", "projectUserId");


--
-- Name: ProjectUserRefreshToken_refreshToken_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ProjectUserRefreshToken_refreshToken_key" ON public."ProjectUserRefreshToken" USING btree ("refreshToken");


--
-- Name: ProjectUser_createdAt_asc; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "ProjectUser_createdAt_asc" ON public."ProjectUser" USING btree ("tenancyId", "createdAt");


--
-- Name: ProjectUser_createdAt_desc; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "ProjectUser_createdAt_desc" ON public."ProjectUser" USING btree ("tenancyId", "createdAt" DESC);


--
-- Name: ProjectUser_displayName_asc; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "ProjectUser_displayName_asc" ON public."ProjectUser" USING btree ("tenancyId", "displayName");


--
-- Name: ProjectUser_displayName_desc; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "ProjectUser_displayName_desc" ON public."ProjectUser" USING btree ("tenancyId", "displayName" DESC);


--
-- Name: ProjectUser_mirroredProjectId_mirroredBranchId_projectUserI_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ProjectUser_mirroredProjectId_mirroredBranchId_projectUserI_key" ON public."ProjectUser" USING btree ("mirroredProjectId", "mirroredBranchId", "projectUserId");


--
-- Name: ProjectWrapperCodes_authorizationCode_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ProjectWrapperCodes_authorizationCode_key" ON public."ProjectWrapperCodes" USING btree ("authorizationCode");


--
-- Name: ProxiedOAuthProviderConfig_projectConfigId_type_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "ProxiedOAuthProviderConfig_projectConfigId_type_key" ON public."ProxiedOAuthProviderConfig" USING btree ("projectConfigId", type);


--
-- Name: TeamMemberDirectPermission_tenancyId_projectUserId_teamId_p_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "TeamMemberDirectPermission_tenancyId_projectUserId_teamId_p_key" ON public."TeamMemberDirectPermission" USING btree ("tenancyId", "projectUserId", "teamId", "permissionDbId");


--
-- Name: TeamMemberDirectPermission_tenancyId_projectUserId_teamId_s_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "TeamMemberDirectPermission_tenancyId_projectUserId_teamId_s_key" ON public."TeamMemberDirectPermission" USING btree ("tenancyId", "projectUserId", "teamId", "systemPermission");


--
-- Name: TeamMember_tenancyId_projectUserId_isSelected_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "TeamMember_tenancyId_projectUserId_isSelected_key" ON public."TeamMember" USING btree ("tenancyId", "projectUserId", "isSelected");


--
-- Name: Team_mirroredProjectId_mirroredBranchId_teamId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "Team_mirroredProjectId_mirroredBranchId_teamId_key" ON public."Team" USING btree ("mirroredProjectId", "mirroredBranchId", "teamId");


--
-- Name: Tenancy_projectId_branchId_hasNoOrganization_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "Tenancy_projectId_branchId_hasNoOrganization_key" ON public."Tenancy" USING btree ("projectId", "branchId", "hasNoOrganization");


--
-- Name: Tenancy_projectId_branchId_organizationId_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "Tenancy_projectId_branchId_organizationId_key" ON public."Tenancy" USING btree ("projectId", "branchId", "organizationId");


--
-- Name: VerificationCode_data_idx; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX "VerificationCode_data_idx" ON public."VerificationCode" USING gin (data jsonb_path_ops);


--
-- Name: VerificationCode_projectId_branchId_code_key; Type: INDEX; Schema: public; Owner: yapit
--

CREATE UNIQUE INDEX "VerificationCode_projectId_branchId_code_key" ON public."VerificationCode" USING btree ("projectId", "branchId", code);


--
-- Name: idx_event_projectid; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX idx_event_projectid ON public."Event" USING btree (((data ->> 'projectId'::text)));


--
-- Name: idx_event_userid; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX idx_event_userid ON public."Event" USING btree (((data ->> 'userId'::text)));


--
-- Name: idx_event_userid_projectid_branchid_eventstartedat; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX idx_event_userid_projectid_branchid_eventstartedat ON public."Event" USING btree (((data ->> 'projectId'::text)), ((data ->> 'branchId'::text)), ((data ->> 'userId'::text)), "eventStartedAt");


--
-- Name: idx_event_userid_projectid_eventstartedat; Type: INDEX; Schema: public; Owner: yapit
--

CREATE INDEX idx_event_userid_projectid_eventstartedat ON public."Event" USING btree (((data ->> 'projectId'::text)), ((data ->> 'userId'::text)), "eventStartedAt");


--
-- Name: ProjectUser project_user_delete_trigger; Type: TRIGGER; Schema: public; Owner: yapit
--

CREATE TRIGGER project_user_delete_trigger AFTER DELETE ON public."ProjectUser" FOR EACH ROW EXECUTE FUNCTION public.update_project_user_count();


--
-- Name: ProjectUser project_user_insert_trigger; Type: TRIGGER; Schema: public; Owner: yapit
--

CREATE TRIGGER project_user_insert_trigger AFTER INSERT ON public."ProjectUser" FOR EACH ROW EXECUTE FUNCTION public.update_project_user_count();


--
-- Name: ProjectUser project_user_update_trigger; Type: TRIGGER; Schema: public; Owner: yapit
--

CREATE TRIGGER project_user_update_trigger AFTER UPDATE ON public."ProjectUser" FOR EACH ROW EXECUTE FUNCTION public.update_project_user_count();


--
-- Name: ApiKeySet ApiKeySet_projectId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ApiKeySet"
    ADD CONSTRAINT "ApiKeySet_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES public."Project"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AuthMethodConfig AuthMethodConfig_projectConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."AuthMethodConfig"
    ADD CONSTRAINT "AuthMethodConfig_projectConfigId_fkey" FOREIGN KEY ("projectConfigId") REFERENCES public."ProjectConfig"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AuthMethod AuthMethod_projectConfigId_authMethodConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."AuthMethod"
    ADD CONSTRAINT "AuthMethod_projectConfigId_authMethodConfigId_fkey" FOREIGN KEY ("projectConfigId", "authMethodConfigId") REFERENCES public."AuthMethodConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AuthMethod AuthMethod_tenancyId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."AuthMethod"
    ADD CONSTRAINT "AuthMethod_tenancyId_fkey" FOREIGN KEY ("tenancyId") REFERENCES public."Tenancy"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: AuthMethod AuthMethod_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."AuthMethod"
    ADD CONSTRAINT "AuthMethod_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: CliAuthAttempt CliAuthAttempt_tenancyId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."CliAuthAttempt"
    ADD CONSTRAINT "CliAuthAttempt_tenancyId_fkey" FOREIGN KEY ("tenancyId") REFERENCES public."Tenancy"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ConnectedAccountConfig ConnectedAccountConfig_projectConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ConnectedAccountConfig"
    ADD CONSTRAINT "ConnectedAccountConfig_projectConfigId_fkey" FOREIGN KEY ("projectConfigId") REFERENCES public."ProjectConfig"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ConnectedAccount ConnectedAccount_projectConfigId_connectedAccountConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ConnectedAccount"
    ADD CONSTRAINT "ConnectedAccount_projectConfigId_connectedAccountConfigId_fkey" FOREIGN KEY ("projectConfigId", "connectedAccountConfigId") REFERENCES public."ConnectedAccountConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ConnectedAccount ConnectedAccount_projectConfigId_oauthProviderConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ConnectedAccount"
    ADD CONSTRAINT "ConnectedAccount_projectConfigId_oauthProviderConfigId_fkey" FOREIGN KEY ("projectConfigId", "oauthProviderConfigId") REFERENCES public."OAuthProviderConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ConnectedAccount ConnectedAccount_tenancyId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ConnectedAccount"
    ADD CONSTRAINT "ConnectedAccount_tenancyId_fkey" FOREIGN KEY ("tenancyId") REFERENCES public."Tenancy"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ConnectedAccount ConnectedAccount_tenancyId_oauthProviderConfigId_providerA_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ConnectedAccount"
    ADD CONSTRAINT "ConnectedAccount_tenancyId_oauthProviderConfigId_providerA_fkey" FOREIGN KEY ("tenancyId", "oauthProviderConfigId", "providerAccountId") REFERENCES public."ProjectUserOAuthAccount"("tenancyId", "oauthProviderConfigId", "providerAccountId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ConnectedAccount ConnectedAccount_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ConnectedAccount"
    ADD CONSTRAINT "ConnectedAccount_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ContactChannel ContactChannel_tenancyId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ContactChannel"
    ADD CONSTRAINT "ContactChannel_tenancyId_fkey" FOREIGN KEY ("tenancyId") REFERENCES public."Tenancy"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ContactChannel ContactChannel_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ContactChannel"
    ADD CONSTRAINT "ContactChannel_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: EmailServiceConfig EmailServiceConfig_projectConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."EmailServiceConfig"
    ADD CONSTRAINT "EmailServiceConfig_projectConfigId_fkey" FOREIGN KEY ("projectConfigId") REFERENCES public."ProjectConfig"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: EmailTemplate EmailTemplate_projectConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."EmailTemplate"
    ADD CONSTRAINT "EmailTemplate_projectConfigId_fkey" FOREIGN KEY ("projectConfigId") REFERENCES public."EmailServiceConfig"("projectConfigId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Event Event_endUserIpInfoGuessId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Event"
    ADD CONSTRAINT "Event_endUserIpInfoGuessId_fkey" FOREIGN KEY ("endUserIpInfoGuessId") REFERENCES public."EventIpInfo"(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: NeonProvisionedProject NeonProvisionedProject_projectId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."NeonProvisionedProject"
    ADD CONSTRAINT "NeonProvisionedProject_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES public."Project"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OAuthAccessToken OAuthAccessToken_tenancyId_oAuthProviderConfigId_providerA_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthAccessToken"
    ADD CONSTRAINT "OAuthAccessToken_tenancyId_oAuthProviderConfigId_providerA_fkey" FOREIGN KEY ("tenancyId", "oAuthProviderConfigId", "providerAccountId") REFERENCES public."ProjectUserOAuthAccount"("tenancyId", "oauthProviderConfigId", "providerAccountId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OAuthAuthMethod OAuthAuthMethod_projectConfigId_oauthProviderConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthAuthMethod"
    ADD CONSTRAINT "OAuthAuthMethod_projectConfigId_oauthProviderConfigId_fkey" FOREIGN KEY ("projectConfigId", "oauthProviderConfigId") REFERENCES public."OAuthProviderConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OAuthAuthMethod OAuthAuthMethod_tenancyId_authMethodId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthAuthMethod"
    ADD CONSTRAINT "OAuthAuthMethod_tenancyId_authMethodId_fkey" FOREIGN KEY ("tenancyId", "authMethodId") REFERENCES public."AuthMethod"("tenancyId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OAuthAuthMethod OAuthAuthMethod_tenancyId_oauthProviderConfigId_providerAc_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthAuthMethod"
    ADD CONSTRAINT "OAuthAuthMethod_tenancyId_oauthProviderConfigId_providerAc_fkey" FOREIGN KEY ("tenancyId", "oauthProviderConfigId", "providerAccountId") REFERENCES public."ProjectUserOAuthAccount"("tenancyId", "oauthProviderConfigId", "providerAccountId") ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: OAuthAuthMethod OAuthAuthMethod_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthAuthMethod"
    ADD CONSTRAINT "OAuthAuthMethod_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OAuthProviderConfig OAuthProviderConfig_projectConfigId_authMethodConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthProviderConfig"
    ADD CONSTRAINT "OAuthProviderConfig_projectConfigId_authMethodConfigId_fkey" FOREIGN KEY ("projectConfigId", "authMethodConfigId") REFERENCES public."AuthMethodConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OAuthProviderConfig OAuthProviderConfig_projectConfigId_connectedAccountConfig_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthProviderConfig"
    ADD CONSTRAINT "OAuthProviderConfig_projectConfigId_connectedAccountConfig_fkey" FOREIGN KEY ("projectConfigId", "connectedAccountConfigId") REFERENCES public."ConnectedAccountConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OAuthProviderConfig OAuthProviderConfig_projectConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthProviderConfig"
    ADD CONSTRAINT "OAuthProviderConfig_projectConfigId_fkey" FOREIGN KEY ("projectConfigId") REFERENCES public."ProjectConfig"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OAuthToken OAuthToken_tenancyId_oAuthProviderConfigId_providerAccount_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OAuthToken"
    ADD CONSTRAINT "OAuthToken_tenancyId_oAuthProviderConfigId_providerAccount_fkey" FOREIGN KEY ("tenancyId", "oAuthProviderConfigId", "providerAccountId") REFERENCES public."ProjectUserOAuthAccount"("tenancyId", "oauthProviderConfigId", "providerAccountId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OtpAuthMethodConfig OtpAuthMethodConfig_projectConfigId_authMethodConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OtpAuthMethodConfig"
    ADD CONSTRAINT "OtpAuthMethodConfig_projectConfigId_authMethodConfigId_fkey" FOREIGN KEY ("projectConfigId", "authMethodConfigId") REFERENCES public."AuthMethodConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OtpAuthMethod OtpAuthMethod_tenancyId_authMethodId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OtpAuthMethod"
    ADD CONSTRAINT "OtpAuthMethod_tenancyId_authMethodId_fkey" FOREIGN KEY ("tenancyId", "authMethodId") REFERENCES public."AuthMethod"("tenancyId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: OtpAuthMethod OtpAuthMethod_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."OtpAuthMethod"
    ADD CONSTRAINT "OtpAuthMethod_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PasskeyAuthMethodConfig PasskeyAuthMethodConfig_projectConfigId_authMethodConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasskeyAuthMethodConfig"
    ADD CONSTRAINT "PasskeyAuthMethodConfig_projectConfigId_authMethodConfigId_fkey" FOREIGN KEY ("projectConfigId", "authMethodConfigId") REFERENCES public."AuthMethodConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PasskeyAuthMethod PasskeyAuthMethod_tenancyId_authMethodId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasskeyAuthMethod"
    ADD CONSTRAINT "PasskeyAuthMethod_tenancyId_authMethodId_fkey" FOREIGN KEY ("tenancyId", "authMethodId") REFERENCES public."AuthMethod"("tenancyId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PasskeyAuthMethod PasskeyAuthMethod_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasskeyAuthMethod"
    ADD CONSTRAINT "PasskeyAuthMethod_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PasswordAuthMethodConfig PasswordAuthMethodConfig_projectConfigId_authMethodConfigI_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasswordAuthMethodConfig"
    ADD CONSTRAINT "PasswordAuthMethodConfig_projectConfigId_authMethodConfigI_fkey" FOREIGN KEY ("projectConfigId", "authMethodConfigId") REFERENCES public."AuthMethodConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PasswordAuthMethod PasswordAuthMethod_tenancyId_authMethodId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasswordAuthMethod"
    ADD CONSTRAINT "PasswordAuthMethod_tenancyId_authMethodId_fkey" FOREIGN KEY ("tenancyId", "authMethodId") REFERENCES public."AuthMethod"("tenancyId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PasswordAuthMethod PasswordAuthMethod_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PasswordAuthMethod"
    ADD CONSTRAINT "PasswordAuthMethod_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PermissionEdge PermissionEdge_childPermissionDbId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PermissionEdge"
    ADD CONSTRAINT "PermissionEdge_childPermissionDbId_fkey" FOREIGN KEY ("childPermissionDbId") REFERENCES public."Permission"("dbId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: PermissionEdge PermissionEdge_parentPermissionDbId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."PermissionEdge"
    ADD CONSTRAINT "PermissionEdge_parentPermissionDbId_fkey" FOREIGN KEY ("parentPermissionDbId") REFERENCES public."Permission"("dbId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Permission Permission_projectConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Permission"
    ADD CONSTRAINT "Permission_projectConfigId_fkey" FOREIGN KEY ("projectConfigId") REFERENCES public."ProjectConfig"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Permission Permission_tenancyId_teamId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Permission"
    ADD CONSTRAINT "Permission_tenancyId_teamId_fkey" FOREIGN KEY ("tenancyId", "teamId") REFERENCES public."Team"("tenancyId", "teamId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectApiKey ProjectApiKey_projectId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectApiKey"
    ADD CONSTRAINT "ProjectApiKey_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES public."Project"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectApiKey ProjectApiKey_tenancyId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectApiKey"
    ADD CONSTRAINT "ProjectApiKey_tenancyId_fkey" FOREIGN KEY ("tenancyId") REFERENCES public."Tenancy"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectApiKey ProjectApiKey_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectApiKey"
    ADD CONSTRAINT "ProjectApiKey_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectApiKey ProjectApiKey_tenancyId_teamId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectApiKey"
    ADD CONSTRAINT "ProjectApiKey_tenancyId_teamId_fkey" FOREIGN KEY ("tenancyId", "teamId") REFERENCES public."Team"("tenancyId", "teamId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectDomain ProjectDomain_projectConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectDomain"
    ADD CONSTRAINT "ProjectDomain_projectConfigId_fkey" FOREIGN KEY ("projectConfigId") REFERENCES public."ProjectConfig"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectUserAuthorizationCode ProjectUserAuthorizationCode_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserAuthorizationCode"
    ADD CONSTRAINT "ProjectUserAuthorizationCode_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectUserDirectPermission ProjectUserDirectPermission_permissionDbId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserDirectPermission"
    ADD CONSTRAINT "ProjectUserDirectPermission_permissionDbId_fkey" FOREIGN KEY ("permissionDbId") REFERENCES public."Permission"("dbId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectUserDirectPermission ProjectUserDirectPermission_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserDirectPermission"
    ADD CONSTRAINT "ProjectUserDirectPermission_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectUserOAuthAccount ProjectUserOAuthAccount_projectConfigId_oauthProviderConfi_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserOAuthAccount"
    ADD CONSTRAINT "ProjectUserOAuthAccount_projectConfigId_oauthProviderConfi_fkey" FOREIGN KEY ("projectConfigId", "oauthProviderConfigId") REFERENCES public."OAuthProviderConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectUserOAuthAccount ProjectUserOAuthAccount_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserOAuthAccount"
    ADD CONSTRAINT "ProjectUserOAuthAccount_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectUserRefreshToken ProjectUserRefreshToken_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUserRefreshToken"
    ADD CONSTRAINT "ProjectUserRefreshToken_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectUser ProjectUser_mirroredProjectId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUser"
    ADD CONSTRAINT "ProjectUser_mirroredProjectId_fkey" FOREIGN KEY ("mirroredProjectId") REFERENCES public."Project"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProjectUser ProjectUser_tenancyId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProjectUser"
    ADD CONSTRAINT "ProjectUser_tenancyId_fkey" FOREIGN KEY ("tenancyId") REFERENCES public."Tenancy"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Project Project_configId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Project"
    ADD CONSTRAINT "Project_configId_fkey" FOREIGN KEY ("configId") REFERENCES public."ProjectConfig"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProxiedEmailServiceConfig ProxiedEmailServiceConfig_projectConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProxiedEmailServiceConfig"
    ADD CONSTRAINT "ProxiedEmailServiceConfig_projectConfigId_fkey" FOREIGN KEY ("projectConfigId") REFERENCES public."EmailServiceConfig"("projectConfigId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ProxiedOAuthProviderConfig ProxiedOAuthProviderConfig_projectConfigId_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."ProxiedOAuthProviderConfig"
    ADD CONSTRAINT "ProxiedOAuthProviderConfig_projectConfigId_id_fkey" FOREIGN KEY ("projectConfigId", id) REFERENCES public."OAuthProviderConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SentEmail SentEmail_tenancyId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."SentEmail"
    ADD CONSTRAINT "SentEmail_tenancyId_fkey" FOREIGN KEY ("tenancyId") REFERENCES public."Tenancy"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: SentEmail SentEmail_tenancyId_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."SentEmail"
    ADD CONSTRAINT "SentEmail_tenancyId_userId_fkey" FOREIGN KEY ("tenancyId", "userId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: StandardEmailServiceConfig StandardEmailServiceConfig_projectConfigId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."StandardEmailServiceConfig"
    ADD CONSTRAINT "StandardEmailServiceConfig_projectConfigId_fkey" FOREIGN KEY ("projectConfigId") REFERENCES public."EmailServiceConfig"("projectConfigId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: StandardOAuthProviderConfig StandardOAuthProviderConfig_projectConfigId_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."StandardOAuthProviderConfig"
    ADD CONSTRAINT "StandardOAuthProviderConfig_projectConfigId_id_fkey" FOREIGN KEY ("projectConfigId", id) REFERENCES public."OAuthProviderConfig"("projectConfigId", id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: TeamMemberDirectPermission TeamMemberDirectPermission_permissionDbId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."TeamMemberDirectPermission"
    ADD CONSTRAINT "TeamMemberDirectPermission_permissionDbId_fkey" FOREIGN KEY ("permissionDbId") REFERENCES public."Permission"("dbId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: TeamMemberDirectPermission TeamMemberDirectPermission_tenancyId_projectUserId_teamId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."TeamMemberDirectPermission"
    ADD CONSTRAINT "TeamMemberDirectPermission_tenancyId_projectUserId_teamId_fkey" FOREIGN KEY ("tenancyId", "projectUserId", "teamId") REFERENCES public."TeamMember"("tenancyId", "projectUserId", "teamId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: TeamMember TeamMember_tenancyId_projectUserId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."TeamMember"
    ADD CONSTRAINT "TeamMember_tenancyId_projectUserId_fkey" FOREIGN KEY ("tenancyId", "projectUserId") REFERENCES public."ProjectUser"("tenancyId", "projectUserId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: TeamMember TeamMember_tenancyId_teamId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."TeamMember"
    ADD CONSTRAINT "TeamMember_tenancyId_teamId_fkey" FOREIGN KEY ("tenancyId", "teamId") REFERENCES public."Team"("tenancyId", "teamId") ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Team Team_tenancyId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Team"
    ADD CONSTRAINT "Team_tenancyId_fkey" FOREIGN KEY ("tenancyId") REFERENCES public."Tenancy"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Tenancy Tenancy_projectId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."Tenancy"
    ADD CONSTRAINT "Tenancy_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES public."Project"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: VerificationCode VerificationCode_projectId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: yapit
--

ALTER TABLE ONLY public."VerificationCode"
    ADD CONSTRAINT "VerificationCode_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES public."Project"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

