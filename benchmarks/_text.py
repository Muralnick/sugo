"""Character-level accuracy against an exact ground truth, for benchmark scripts."""


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b))
            )
        previous = current
    return previous[-1]


def character_error_rate(truth: list[str], read: list[str]) -> float:
    """Edit distance between corresponding lines of ``truth`` and ``read``, over ``truth``'s length.

    Extra ``truth`` lines missing from ``read`` count as fully wrong; ``read``
    is compared line by line in order, as callers sort both the same way.
    """
    errors = sum(_edit_distance(a, b) for a, b in zip(truth, read, strict=False))
    errors += sum(len(line) for line in truth[len(read) :])
    total = sum(len(line) for line in truth)
    return round(errors / total, 4) if total else 0.0
