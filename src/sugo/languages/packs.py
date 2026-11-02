"""The language packs of v0.1: Italian, Spanish, French, German and English.

Most text rules hold for every language and live in the text normalisation
cleaner. A pack adds only what one language needs. In v0.1 that is the
elisions of Italian and French: "dell' albero" and "l' arbre", where a PDF or
OCR left a space after the apostrophe, become "dell'albero" and "l'arbre".

Rules that would change letters are left out on purpose, because no core edit
may change a letter (ADR-050): restoring "è" from "e'", "¿" lost by OCR, or
undoing pre-1996 German hyphenation ("Zuk-ker" -> "Zucker"). Languages are
chosen in the configuration, never guessed: v0.1 has no language detector.
"""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class LanguagePack:
    """What one language adds to the universal text rules."""

    code: str
    # Words that end in an apostrophe and attach to the next word.
    elisions: frozenset[str] = frozenset()


PACKS = MappingProxyType(
    {
        "it": LanguagePack(
            "it",
            elisions=frozenset(
                {
                    "l",
                    "un",
                    "dell",
                    "nell",
                    "all",
                    "dall",
                    "sull",
                    "coll",
                    "pell",
                    "quell",
                    "bell",
                    "sant",
                    "buon",
                    "nessun",
                    "qualcun",
                    "c",
                    "d",
                    "m",
                    "t",
                    "s",
                    "v",
                    "n",
                    "anch",
                    "com",
                    "dov",
                    "quest",
                }
            ),
        ),
        "fr": LanguagePack(
            "fr",
            elisions=frozenset(
                {
                    "l",
                    "d",
                    "j",
                    "m",
                    "n",
                    "s",
                    "t",
                    "c",
                    "qu",
                    "jusqu",
                    "lorsqu",
                    "puisqu",
                    "quoiqu",
                    "presqu",
                    "quelqu",
                }
            ),
        ),
        "es": LanguagePack("es"),
        "de": LanguagePack("de"),
        "en": LanguagePack("en"),
    }
)


def elisions(languages: tuple[str, ...]) -> frozenset[str]:
    """The elided words of the given languages, lower case.

    Raises:
        ValueError: If a language has no pack.
    """
    unknown = sorted(set(languages) - set(PACKS))
    if unknown:
        raise ValueError(f"no language pack for: {', '.join(unknown)}")
    return frozenset().union(*(PACKS[code].elisions for code in languages))
