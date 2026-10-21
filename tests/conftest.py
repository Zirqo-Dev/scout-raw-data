"""Shared paths and loaders for the test suite.

Nothing here touches the network. Every payload is a small JSON file under
tests/fixtures/, shaped like a GeckoTerminal pool-list response. Every address
in them is synthetic (0x000...0a01 style) and belongs to no real contract.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

# The scripts are not a package and are run as files, so the tests import
# them the same way they are invoked.
sys.path.insert(0, str(ROOT / "scripts"))


def load_fixture(name):
    with open(FIXTURES / name, encoding="utf-8") as fh:
        return json.load(fh)
