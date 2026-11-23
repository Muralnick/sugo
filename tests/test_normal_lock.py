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


def _linux_only(markers: list[str]) -> bool:
    return bool(markers) and all("sys_platform == 'linux'" in marker for marker in markers)


def test_on_linux_both_come_from_the_cpu_index() -> None:
    # Checked on each record's resolution markers, so a CPU build that stopped
    # being selected for Linux fails here too (#128 review).
    for name in ("torch", "torchvision"):
        records = _packages(ROOT / "uv.lock", name)
        cpu = [r for r in records if r["source"]["registry"] == CPU_INDEX]  # type: ignore[index]
        other = [r for r in records if r["source"]["registry"] != CPU_INDEX]  # type: ignore[index]
        assert len(cpu) == 1, f"{name} has no single CPU build in the lock"
        assert str(cpu[0]["version"]).endswith("+cpu")
        assert _linux_only(cpu[0]["resolution-markers"])  # type: ignore[arg-type]
        for record in other:
            markers: list[str] = record["resolution-markers"]  # type: ignore[assignment]
            assert not any("sys_platform == 'linux'" in marker for marker in markers)
