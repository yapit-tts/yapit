import time

import pytest
import requests


@pytest.fixture(scope="session")
def gateway_url() -> str:
    return "http://localhost:8000"


@pytest.fixture(scope="session")
def ws_url(gateway_url: str) -> str:
    return gateway_url.replace("http", "ws")


@pytest.fixture(scope="session", autouse=True)
def wait_until_gateway(gateway_url: str, timeout: int = 60) -> None:
    """Block until GET /docs returns 200 or *timeout* seconds passed."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(f"{gateway_url}/docs").status_code == 200:
                return
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    raise RuntimeError("Gateway did not come up in time")
