import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def test_live_server_does_not_trust_forwarded_client_addresses(service, tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment.update(
        APP_ENV="test",
        AUTH_ENABLED="true",
        AUTH_TENANT_ID="demo_001",
        AUTH_TRUSTED_ORIGIN="http://127.0.0.1:3000",
        DATABASE_URL=service.database.dsn,
    )
    with tempfile.TemporaryFile(dir=tmp_path) as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "backend.server", "--host", "127.0.0.1", "--port", str(port)],
            env=environment,
            stdout=output,
            stderr=output,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
                deadline = time.monotonic() + 30
                while True:
                    assert process.poll() is None, (
                        "Authentication test server exited before startup"
                    )
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert time.monotonic() < deadline, "Authentication test server did not start"
                    time.sleep(0.05)
                # Both the name and spoofed address rotate. The real loopback peer must
                # still exhaust one persistent bucket, even over a real Uvicorn server.
                for index in range(30):
                    response = client.post(
                        "/api/v1/auth/login",
                        json={"username": f"unknown-{index}", "password": "wrong"},
                        headers={
                            "Origin": "http://127.0.0.1:3000",
                            "X-Forwarded-For": f"192.0.2.{index + 1}",
                        },
                    )
                    assert response.status_code == 401
                response = client.post(
                    "/api/v1/auth/login",
                    json={"username": "student", "password": "a-long-student-test-password"},
                    headers={"Origin": "http://127.0.0.1:3000", "X-Forwarded-For": "192.0.2.100"},
                )
                assert response.status_code == 429
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
