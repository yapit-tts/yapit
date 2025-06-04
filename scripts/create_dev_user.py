#!/usr/bin/env python3
"""Create a development test user in stack-auth."""

import argparse
import os
import sys
import time
import requests


def wait_for_stack_auth(api_host: str, max_attempts: int = 30):
    """Wait for stack-auth to be ready."""
    print(f"Waiting for stack-auth at {api_host}...", file=sys.stderr)
    for i in range(max_attempts):
        try:
            r = requests.get(f"{api_host}/health", timeout=1)
            if r.status_code == 200:
                print("Stack-auth is ready!", file=sys.stderr)
                return True
        except Exception as e:
            if i == 0:
                print(f"Connection error: {e}", file=sys.stderr)
        time.sleep(1)
    return False


def create_dev_user(print_token: bool = False):
    """Create a test user for development."""
    api_host = os.getenv("SCRIPT_STACK_AUTH_API_HOST", "http://localhost:8102")
    project_id = os.getenv("STACK_AUTH_PROJECT_ID")
    server_key = os.getenv("STACK_AUTH_SERVER_KEY")
    
    if not project_id or not server_key:
        print("Error: STACK_AUTH_PROJECT_ID and STACK_AUTH_SERVER_KEY must be set", file=sys.stderr)
        print(f"STACK_AUTH_PROJECT_ID={project_id}", file=sys.stderr)
        print(f"STACK_AUTH_SERVER_KEY={server_key}", file=sys.stderr)
        sys.exit(1)
    
    # Wait for stack-auth
    if not wait_for_stack_auth(api_host):
        print("Error: Stack-auth not responding", file=sys.stderr)
        sys.exit(1)
    
    # Fixed dev user credentials
    dev_email = "dev@example.com"
    dev_password = "dev-password-123"
    
    headers = {
        "X-Stack-Access-Type": "server",
        "X-Stack-Project-Id": project_id,
        "X-Stack-Secret-Server-Key": server_key,
    }
    
    if not print_token:
        print(f"Using project_id: {project_id}", file=sys.stderr)
        print(f"Using server_key: {server_key[:10]}...", file=sys.stderr)
    
    # Try to create user (might already exist)
    r = requests.post(
        f"{api_host}/api/v1/users",
        headers=headers,
        json={
            "primary_email": dev_email,
            "password": dev_password,
            "primary_email_verified": True,
            "primary_email_auth_enabled": True,
            "display_name": "Dev User",
        }
    )
    
    if r.status_code in [200, 201]:
        user_id = r.json()["id"]
        if not print_token:
            print(f"User created with ID: {user_id}", file=sys.stderr)
    elif (r.status_code == 400 and "already exists" in r.text) or (r.status_code == 409):
        # User already exists, which is fine
        if not print_token:
            print(f"User already exists: {dev_email}", file=sys.stderr)
    else:
        print(f"Error creating user: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    
    if print_token:
        # Use the client API to sign in with password and get an access token
        # Note: We need to use client headers for this endpoint
        client_key = os.getenv("STACK_AUTH_CLIENT_KEY")
        if not client_key:
            # Try alternative env var names
            client_key = os.getenv("SCRIPT_STACK_AUTH_CLIENT_KEY")

        if not client_key:
            print("Error: STACK_AUTH_CLIENT_KEY or SCRIPT_STACK_AUTH_CLIENT_KEY must be set", file=sys.stderr)
            sys.exit(1)

        client_headers = {
            "X-Stack-Access-Type": "client",
            "X-Stack-Project-Id": project_id,
            "X-Stack-Publishable-Client-Key": client_key,
        }
        
        r = requests.post(
            f"{api_host}/api/v1/auth/password/sign-in",
            headers=client_headers,
            json={
                "email": dev_email,
                "password": dev_password
            }
        )
        
        if r.status_code not in [200, 201]:
            print(f"Error signing in: {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
        
        # Only print the token, nothing else
        print(r.json()["access_token"])
    else:
        # Development mode - just print user info
        print(f"Dev user ready: {dev_email} / {dev_password}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Create development user in stack-auth")
    parser.add_argument("--print-token", action="store_true", 
                       help="Print access token to stdout (for CI)")
    args = parser.parse_args()
    
    create_dev_user(print_token=args.print_token)


if __name__ == "__main__":
    main()
