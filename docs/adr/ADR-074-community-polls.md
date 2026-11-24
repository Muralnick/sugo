# ADR-074: Community polls for proposals

**Status:** Accepted (maintainer decision 2026-11-24)
**Date:** 2026-11-24
**Deciders:** project author
**Amends:** `GOVERNANCE.md` (until now: the maintainer has final say on everything)
**Used by:** ADR-073 (PDF engine, condition 2)

## Context

Sugo has one maintainer, who has had the final say on product direction and architecture. The maintainer wants users to decide on changes and new features through an official poll, while keeping the project open source and on topic. The rule must be clear before a poll is ever needed, so that nobody can argue about the counting afterwards.

## Decision

### 1. What can be put to a poll

Any proposal to add a feature or to change how Sugo works: a new format, a change of behaviour, a change of engine (ADR-073), a new port.

**Never put to a poll:**

- **Sugo stays open source.** Its licence is the maintainer's decision and is not voted on.
- **The principles** (`PRINCIPLES.md`). They already have their own procedure: an ADR, a public discussion and a major version (`GOVERNANCE.md`).
- **Security protections and rules**: the protections of the threat model (`docs/THREAT_MODEL.md`), the hardening of ADR-031, `src/sugo/security/`, and the dependency and supply-chain rules (ADR-033, ADR-035). A poll cannot, for example, remove the hidden-text protection or let documents leave the computer.
- Legal obligations, and the code of conduct.

### 2. When a poll opens

- **At least 10 different users** support the same proposal on GitHub: the author of the issue or discussion, plus each account that comments in support or adds a 👍 reaction. One count per account.
- The maintainer may open a poll earlier, at any time.
- The proposal must say concretely what would change. A proposal that was rejected by a poll is not put to a new poll for 6 months, unless there are new facts.

### 3. Where and for how long

- In **GitHub Discussions**, with GitHub's built-in poll (one vote per account), in the repository's own Discussions.
- Two choices: change, or keep things as they are.
- Open for **30 days**, announced in the README and in the release notes of a release published while it is open, if there is one.

### 4. How votes are counted

| Total votes | The change passes with |
|---|---|
| Fewer than 20 | Never: too few votes to decide. Things stay as they are |
| 20 to 99 | At least **two thirds** in favour: a clear win |
| 100 or more | A **simple majority**: more than half in favour |

A tie keeps things as they are. These thresholds can be raised by an amendment to this ADR if the community grows.

If there is clear evidence that a poll was manipulated (for example, many accounts created just to vote), the maintainer may cancel it, with a public explanation of the evidence, and open a new one.

### 5. The maintainer's role

- **Usually the maintainer does not intervene:** the poll decides.
- The maintainer may **refuse a proposal, even one that won its poll**, when it takes the project off topic or conflicts with section 1. The refusal is written publicly in the poll's discussion, with a **detailed explanation**.
- A proposal that passes goes into the roadmap. It is then built under the usual rules: an ADR where one is needed, tests, code and security review. A poll decides *what* is done, not that these checks are skipped.

## Alternatives considered

| Alternative | Why not |
|---|---|
| The maintainer decides everything, as before | The maintainer wants users to have a real say |
| Simple majority at any turnout | A handful of votes could change the project |
| A poll on an external site | Needs another account and service, and gives less protection against repeat votes; GitHub is where the code and the discussions already are |
| Counting 👍 reactions on an issue as the vote | Reactions are not a closed, dated vote, and anyone can add one at any time |

## Consequences

- `GOVERNANCE.md` describes polls and points to this ADR.
- ADR-073's user condition becomes a poll under this ADR.
- Polls can never change the licence model, the principles or the security rules, so those stay stable for users and contributors.
