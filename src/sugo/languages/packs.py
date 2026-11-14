"""The language packs: Italian, Spanish, French, German, English, Japanese, Chinese, Korean.

Most text rules hold for every language and live in the text normalisation
cleaner. A pack adds only what one language needs. In v0.1 that is the
elisions of Italian and French: "dell' albero" and "l' arbre", where a PDF or
OCR left a space after the apostrophe, become "dell'albero" and "l'arbre".

Rules that would change letters are left out on purpose, because no core edit
may change a letter (ADR-050): restoring "è" from "e'", "¿" lost by OCR, or
undoing pre-1996 German hyphenation ("Zuk-ker" -> "Zucker").

Japanese and Chinese are written without spaces between words, so a line
break inside a paragraph can split a word in two: their packs join lines
between two CJK characters and write full-width letters and digits as ASCII
(ADR-069). One Chinese pack covers simplified and traditional writing; Sugo
never converts between them. Korean separates words with spaces, so it needs
no rule of its own; what it needs is its OCR model, which Sugo downloads on
request (ADR-070). Languages are chosen in the configuration, never guessed:
Sugo has no language detector.
"""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class LanguagePack:
    """What one language adds to the universal text rules."""

    code: str
    # Words that end in an apostrophe and attach to the next word.
    elisions: frozenset[str] = frozenset()
    # Written without spaces between words: join lines between CJK characters
    # and normalise character width (ADR-069).
    cjk: bool = False


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
        "ja": LanguagePack("ja", cjk=True),
        "zh": LanguagePack("zh", cjk=True),
        # Korean separates words with spaces: the universal rules are enough.
        "ko": LanguagePack("ko"),
    }
)


def elisions(languages: tuple[str, ...]) -> frozenset[str]:
    """The elided words of the given languages, lower case.

    Raises:
        ValueError: If a language has no pack.
    """
    return frozenset().union(*(pack.elisions for pack in _packs(languages)))


def writes_cjk(languages: tuple[str, ...]) -> bool:
    """Whether one of the given languages is written without spaces (ADR-069).

    Raises:
        ValueError: If a language has no pack.
    """
    return any(pack.cjk for pack in _packs(languages))


def _packs(languages: tuple[str, ...]) -> list[LanguagePack]:
    unknown = sorted(set(languages) - set(PACKS))
    if unknown:
        raise ValueError(f"no language pack for: {', '.join(unknown)}")
    return [PACKS[code] for code in languages]
