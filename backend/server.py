"""Application server entrypoint; authentication throttles use the direct socket peer."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Rantau backend server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("backend.main:app", host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
