import time

import pytest
import requests

GATEWAY = "http://localhost:8000"
WS = GATEWAY.replace("http", "ws")


@pytest.fixture(scope="session", autouse=True)
def wait_until_gateway(timeout: int = 60) -> None:
    """Block until GET /docs returns 200 or *timeout* seconds passed."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(f"{GATEWAY}/docs").status_code == 200:
                return
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    raise RuntimeError("Gateway did not come up in time")
