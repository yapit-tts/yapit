import requests
import os

from .stack_auth_cli_template import prompt_cli_login

api_host = os.getenv("STACK_AUTH_API_HOST")
if api_host is None:
    print("Please specify STACK_AUTH_API_HOST")
    os._exit(1)

dash_host = os.getenv("STACK_AUTH_DASH_HOST")
if dash_host is None:
    print("Please specify STACK_AUTH_DASH_HOST")
    os._exit(1)

project_id = os.getenv("STACK_AUTH_PROJECT_ID")
if project_id is None:
    print("Please specify STACK_AUTH_PROJECT_ID")
    os._exit(1)

publishable_client_key = os.getenv("STACK_AUTH_CLIENT_KEY")
if publishable_client_key is None:
    print("Please specify STACK_AUTH_CLIENT_KEY")
    os._exit(1)

print(f"API HOST: '{api_host}'")
print(f"PROJECT ID: '{project_id}'")
print(f"PUBLISHABLE CLIENT KEY: '{publishable_client_key}'")

refresh_token = prompt_cli_login(
    base_url=api_host,
    app_url=dash_host,
    project_id=project_id,
    publishable_client_key=publishable_client_key,
)

if refresh_token is None:
    print("User cancelled the login process. Exiting")
    exit(1)


def get_access_token(refresh_token):
    access_token_response = requests.post(
        f"{api_host}/api/v1/auth/sessions/current/refresh",
        headers={
            "x-stack-refresh-token": refresh_token,
            "x-stack-project-id": project_id,
            "x-stack-access-type": "client",
            "x-stack-publishable-client-key": publishable_client_key,
        },
    )

    return access_token_response.json()["access_token"]


access_token = get_access_token(refresh_token)
print(f"ACCESS TOKEN: {access_token}")
