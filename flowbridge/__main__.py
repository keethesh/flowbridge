import argparse

from . import serve


def main():
    p = argparse.ArgumentParser(prog="flowbridge", description="Serve Google Flow as a local HTTP API.")
    p.add_argument("cmd", choices=["serve"])
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--host", default="127.0.0.1", help="keep on localhost: anyone who can reach it can spend your credits")
    a = p.parse_args()
    serve(a.port, a.host)


if __name__ == "__main__":
    main()
