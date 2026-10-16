"""Generate local contracts from the approved Python models."""

import json
from pathlib import Path

from backend.contracts.schema import contract_schema


def main() -> None:
    target = Path(".generated/openapi.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(contract_schema(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
