#!/usr/bin/env python3
"""Run the local browser using settings outside the Git checkout's tracked files."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    args = parser.parse_args()
    settings = json.loads(Path(args.settings).read_text())
    os.environ.update({key: str(value) for key, value in settings.items()})
    from luogu_proxy import main as serve
    serve()


if __name__ == "__main__":
    main()
