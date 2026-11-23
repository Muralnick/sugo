"""The normal level's PyTorch pair in the locks (ADR-071 note, 2026-11-23).

CI does not install the ``normal`` extra (1.3 GB), so it cannot import
torch and torchvision together. These tests read the locks instead: each
torch release has exactly one matching torchvision (2.N with 0.N+15), and on
Linux both must come from PyTorch's CPU index. A mismatched pair breaks
Docling's layout model at load time ("operator torchvision::nms does not
exist"), as torch 2.15 with torchvision 0.29.2 did.
"""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCKS = [ROOT / "uv.lock", *sorted((ROOT / "integrations").glob("*/uv.lock"))]
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
# torchvision's minor version is torch's plus this.
_VISION_OFFSET = 15


def _packages(lock: Path, name: str) -> list[dict[str, object]]:
    with lock.open("rb") as file:
        packages: list[dict[str, object]] = tomllib.load(file)["package"]
    return [package for package in packages if package["name"] == name]


def _release(version: object) -> tuple[int, int, int]:
    major, minor, patch = str(version).split("+")[0].split(".")
    return int(major), int(minor), int(patch)


@pytest.mark.parametrize("lock", LOCKS, ids=lambda lock: lock.parent.name)
def test_torch_and_torchvision_are_a_matched_pair(lock: Path) -> None:
    torch = {_release(package["version"]) for package in _packages(lock, "torch")}
    vision = {_release(package["version"]) for package in _packages(lock, "torchvision")}
    if not torch:
        pytest.skip("this lock has no normal extra")
    assert len(torch) == 1
    assert len(vision) == 1
    (major, minor, patch), (_, vision_minor, vision_patch) = torch.pop(), vision.pop()
    assert (major, vision_minor, vision_patch) == (2, minor + _VISION_OFFSET, patch)


def test_on_linux_both_come_from_the_cpu_index() -> None:
    for name in ("torch", "torchvision"):
        sources = {
            str(package["version"]): package["source"]["registry"]  # type: ignore[index]
            for package in _packages(ROOT / "uv.lock", name)
        }
        cpu = [version for version, registry in sources.items() if registry == CPU_INDEX]
        assert cpu, f"{name} has no CPU build in the lock"
        assert all(version.endswith("+cpu") for version in cpu)
