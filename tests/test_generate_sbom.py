"""The release SBOM's serial number (ADR-033, ADR-075)."""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def load() -> ModuleType:
    path = ROOT / "scripts" / "release" / "generate_sbom.py"
    spec = importlib.util.spec_from_file_location("generate_sbom", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_sbom = load()
SBOM = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"name": "numpy"}]}


def test_the_serial_number_is_a_urn_uuid() -> None:
    # GitHub's SBOM attestation refuses CycloneDX without one (v0.3.2 release).
    serial = generate_sbom.serial_number(SBOM)
    assert re.fullmatch(
        r"urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", serial
    )


def test_the_same_content_gives_the_same_serial_number() -> None:
    # Two builds of one release must stay byte for byte identical.
    again = dict(reversed(list(SBOM.items())))
    assert generate_sbom.serial_number(SBOM) == generate_sbom.serial_number(again)
    assert generate_sbom.serial_number(SBOM) == generate_sbom.serial_number(
        {**SBOM, "serialNumber": "urn:uuid:anything"}
    )


def test_other_content_gives_another_serial_number() -> None:
    other = {**SBOM, "components": [{"name": "pillow"}]}
    assert generate_sbom.serial_number(SBOM) != generate_sbom.serial_number(other)
