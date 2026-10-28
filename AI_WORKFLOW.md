# AI-assisted development

Sugo is built with the assistance of Claude (Anthropic), openly and on purpose. Part of the project's goal is to show how to direct an AI through a complex software project.

## Division of roles

| Role | Who |
|---|---|
| Product vision, target users, priorities | Author |
| Scope, platforms, licence, features, naming | Author, after reviewing alternatives proposed by the AI |
| Technical analysis, library and model comparison, architectural proposals | AI, on request, checked against primary sources |
| Code | AI, under the author's direction, with tests and benchmarks |
| Verification of recent information | Author, providing official documentation (READMEs, changelogs, provider guides) |

## Method

1. **Architecture first.** The complete design was written before any code; every significant decision is an ADR.
2. **Primary sources.** The AI has a knowledge cutoff. Versions, licences and cost formulas were checked against official documents supplied by the author; unverified items are marked as such.
3. **One module at a time**, each with tests and token measurements.
4. **Real numbers.** Every claim about token savings is backed by reproducible benchmarks, always paired with a content-preservation measure.
5. **Tooling as a safety net.** Static analysis, invariant tests, mutation testing and security scans compensate for the risks of AI-generated code.
6. **Isolated environment.** Development happens in GitHub Codespaces; the agent has no access to the author's personal machine.

## Corrections log

Mistakes caught during design are part of the record:

- The Claude image-token formula first assumed (area / 750) was outdated; official documentation describes 28×28-pixel patches. The design was corrected (ADR-003).
- "Economical RAM upgrade" advice ignored 2025–2026 memory prices; withdrawn.
- One file per page for the page store was replaced by SQLite after considering crash safety and Windows antivirus overhead (ADR-006).
- The command name `tsp` conflicted with Debian's task-spooler; the project was renamed Sugo (ADR-034).
- The first implementation of the Claude formula capped the patch count instead of shrinking the image, overestimating a 1920×1080 image by 8 tokens, and defaulted to the standard tier although current models use the high-resolution one. Both were corrected against the official table, which is now part of the tests.
- The OpenAI formula first shipped was the tile formula of older models; recent models use patches with a budget and a multiplier. Corrected from the official documentation supplied by the author.
- A test value for the token count of "ciao" was written from memory and was wrong; it was replaced by a cross-check against tiktoken's own definition.
