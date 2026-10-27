# Contributing to Sugo

Thank you for helping. Before contributing, read `PRINCIPLES.md` and `CODE_STYLE.md`.

## Ways to contribute

- **Bug reports**: use the issue template and attach the output of `sugo doctor --report` (review it before sharing).
- **Translations**: interface strings use gettext (`.po` files); Italian is maintained by the project, other languages are welcome.
- **Language packs**: new languages through the `sugo.languages` extension family, with mandatory test cases.
- **Extensions**: see "Extension requirements" in `docs/ARCHITECTURE.md`. Run `sugo plugin check` before publishing.
- **Data contributions**: work profiles, recipes, provider formulas.
- **Code**: pick an issue labelled `good first issue`.

## Pull request checklist

- [ ] Tests added or updated, all passing
- [ ] No principle in `PRINCIPLES.md` is weakened
- [ ] Token-savings and content-loss benchmarks not regressed (CI gate)
- [ ] Documentation updated
- [ ] ADR added if a public contract, dependency or architectural decision changed
- [ ] AI assistance declared, if used

## Security issues

Do not open public issues for vulnerabilities. See `SECURITY.md`.
