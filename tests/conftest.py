import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]
# github.com/caliperforge/sky-schema 4120d171a397c153ced2e1d7e683d5a8c7f84b98, schema/object.json
SCHEMA = json.loads((ROOT / "tests" / "fixtures" / "sky-schema" / "object.json").read_text())


@pytest.fixture
def valid():
    return Draft202012Validator(SCHEMA).validate
