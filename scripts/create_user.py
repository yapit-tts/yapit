#!/usr/bin/env python3
"""Create a development test user in stack-auth."""

import argparse
import os
import sys
import time

import requests


def wait_for_stack_auth(api_host: str, max_attempts: int = 30):
    """Wait for stack-auth to be ready."""
    print(f"Waiting for stack-auth at {api_host}...")
    for i in range(max_attempts):
        try:
            r = requests.get(f"{api_host}/health", timeout=1)
            if r.status_code == 200:
                print("Stack-auth is ready!")
                return True
        except Exception as e:
            if i == 0:
                print(f"Connection error: {e}")
        time.sleep(1)
    return False


def create_dev_user(
    email: str = "dev@example.com",
    password: str = "dev-password-123",
    is_admin: bool = True,
    display_name: str = "Dev User",
):
    """Create a test user for development."""
    api_host = os.getenv("DEV_STACK_AUTH_API_HOST", "http://localhost:8102")
    project_id = os.getenv("STACK_AUTH_PROJECT_ID")
    server_key = os.getenv("STACK_AUTH_SERVER_KEY")

    if not project_id or not server_key:
        print("Error: STACK_AUTH_PROJECT_ID and STACK_AUTH_SERVER_KEY must be set")
        sys.exit(1)

    # Wait for stack-auth
    if not wait_for_stack_auth(api_host):
        print("Error: Stack-auth not responding")
        sys.exit(1)

    headers = {
        "X-Stack-Access-Type": "server",
        "X-Stack-Project-Id": project_id,
        "X-Stack-Secret-Server-Key": server_key,
    }

    print(f"Using project_id: {project_id}")
    print(f"Using server_key: {server_key[:10]}...")

    # Try to create user (might already exist)
    r = requests.post(
        f"{api_host}/api/v1/users",
        headers=headers,
        json={
            "primary_email": email,
            "password": password,
            "primary_email_verified": True,
            "primary_email_auth_enabled": True,
            "display_name": display_name,
            "server_metadata": {"is_admin": is_admin},
        },
    )

    if r.status_code in [200, 201]:
        user_id = r.json()["id"]
        print(f"User created with ID: {user_id}")
        return user_id
    elif (r.status_code == 400 and "already exists" in r.text) or (r.status_code == 409):
        print(f"User already exists: {email}")
        # Try to find existing user
        r = requests.get(
            f"{api_host}/api/v1/users",
            headers=headers,
        )
        if r.status_code == 200:
            users = r.json()["items"]
            for user in users:
                if user.get("primary_email") == email:
                    return user["id"]
        return None
    else:
        print(f"Error creating user: {r.status_code} {r.text}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Create a development test user in stack-auth")
    parser.add_argument("--email", default="dev@example.com", help="User email (default: dev@example.com)")
    parser.add_argument("--password", default="dev-password-123", help="User password (default: dev-password-123)")
    parser.add_argument("--no-admin", action="store_true", help="Create regular user instead of admin")
    parser.add_argument("--display-name", default="Dev User", help="User display name (default: Dev User)")

    args = parser.parse_args()

    user_id = create_dev_user(
        email=args.email, password=args.password, is_admin=not args.no_admin, display_name=args.display_name
    )

    print(f"Dev user ready: {args.email} / {args.password}")

    # Return user_id via exit code 0 and print to stderr for programmatic use
    if user_id:
        sys.stderr.write(user_id + "\n")


if __name__ == "__main__":
    main()
