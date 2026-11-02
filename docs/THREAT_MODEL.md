# Threat model

Method: assets → attackers → trust boundaries → threats per surface → mitigations → **declared residual risks**.

## 1. Assets

| Asset | Why it matters |
|---|---|
| Document content | Contracts, personal data, trade secrets |
| **Anonymization maps** | Most sensitive asset: they re-identify people |
| Other files on the user's machine | SSH keys, credentials, private documents reachable by a tricked agent |
| Machine integrity | No file may cause code execution |
| Output integrity | A poisoned RAG answers wrongly with authority |
| Audit log integrity | Evidentiary value in legal settings |
| Supply chain | Repository, PyPI packages, models |
| Availability | A document must not freeze the computer |

## 2. Attackers

| Attacker | Likelihood | Example |
|---|---|---|
| **Malicious document author** | High | Email attachment, downloaded file |
| Malicious web page | Medium | Hidden text aimed at LLMs |
| Malicious extension author | Medium | Typosquatted package |
| Compromised upstream dependency or model | Low, devastating | Malicious new library release |
| Website open in the browser | Medium | Tries to reach the local web UI |
| Tricked AI agent | Medium, growing | Hidden instructions push it to read `~/.ssh` |
| Person with physical access | Low | Reads the cache |
| Attacker targeting the project | Low | Account takeover, malicious PR |

## 3. Trust boundaries

```
  UNTRUSTED                    ISOLATED               TRUSTED           SEMI-TRUSTED
┌──────────────┐          ┌───────────────┐     ┌─────────────┐    ┌──────────────┐
│ files, archives────────►│ workers with  │────►│   engine    │───►│ ports: CLI,  │──► output
│ web pages    │          │ limits,       │     │ (validates  │    │ UI, MCP      │    to LLMs
│ extensions   │─────────►│ timeouts,     │     │  & applies) │    │ (AI agents)  │
│ models       │──(hash)─►│ sandbox       │     └─────────────┘    └──────────────┘
└──────────────┘          └───────────────┘
```

## 4. Threats and mitigations

### A. Malicious files

| Threat | Mitigation |
|---|---|
| Exploits in native parsers (MuPDF, Pillow, ONNX Runtime) | Isolated workers, limits, timeouts, sandbox, updated libraries. MuPDF already runs in its own process, answering in validated JSON, never pickle, with a memory cap, no core dumps and per-page timeouts; PDFs reaching its vulnerable Brotli decoder are refused (ADR-043) |
| Decompression bombs (zip, huge images, PDF streams) | Limits on real decompressed bytes; image file size and pixel count checked from the header before decoding, Pillow bomb warning made fatal (ADR-039) |
| Zip slip, symlinks, special files | Hashed names; special entries rejected |
| **XXE** in Office, FatturaPA, PEC (all XML) | `defusedxml`, external entities disabled |
| Polyglot files | Content-based type detection |
| Pathological slow documents | Per-page budget and timeout |
| Crash writing content to disk | Core dumps disabled in workers |

### B. Prompt injection aimed at downstream LLMs

| Mitigation | Detail |
|---|---|
| Invisible text removal | White-on-white, tiny fonts, off-page text, text under opaque shapes, invisible render modes: flagged `hidden` by the PDF extractor and removed with a reason; the text layer of a scanned page is never trusted, the page is read with OCR (ADR-043) |
| Deceptive characters | Zero-width characters, bidi overrides ("Trojan Source"), homoglyphs removed or flagged (also saves tokens) |
| Suspicious instruction detector | Imperative phrases addressed to an AI are **flagged**, not removed (principle 3) |
| MCP delimiting | Content wrapped and labelled as document data, not instructions |
| Agent limits | Allowed roots, fixed exclusions, no system actions |

Residual: no tool can guarantee immunity; the receiving LLM and agent are the last line of defence.

### C. Output poisoning

Example: a key clause repeated at the bottom of every page so it is removed as a footer. Mitigations: conservative legal recipes; header/footer removals of long or substantive text are flagged; removal report and preview; adversarial cases in the content-loss benchmark.

### D. AI agents via MCP

| Threat | Mitigation |
|---|---|
| Agent tricked into reading sensitive files | Allowed roots; non-disableable exclusions |
| Agent loops saturating the machine | Per-client rate limits; paginated responses |
| Personal data sent to a cloud LLM through the agent | Forced anonymization of MCP output (`legal`) |
| Agent installing or deleting | Operations not exposed (principle 10) |

### E. Local web UI and engine channel

127.0.0.1 only, random port, session token, `Host` and `Origin` checks, no CORS; engine socket owner-only in `$XDG_RUNTIME_DIR` (protects against other local users).

### F. Malicious extensions

| Threat | Mitigation |
|---|---|
| Arbitrary code | Explicit install only, permission prompt, trust tiers, company allow-lists |
| Typosquatting | Official catalog with verified names; `sugo plugins` shows publisher and tier |
| False permission declarations | Code extensions in separate workers; **on Linux the sandbox enforces declared permissions** |
| Verified extension later compromised | Badge revocation; warning when the catalog is reachable |

### G. Supply chain

| Threat | Mitigation |
|---|---|
| Malicious dependency release | Pinned versions and hashes; **14-day cooldown** before adopting new versions |
| Known vulnerabilities | `pip-audit`, OSV |
| Swapped model | Pinned revision + SHA-256 (download interception becomes irrelevant) |
| Code execution on model load | ONNX, safetensors, GGUF only |

### H. Data at rest

Owner-only permissions, ephemeral cache mode, retention, optional encryption of anonymization maps, full-disk encryption recommended, encrypted swap recommended for sensitive use.

### I. Anonymization failures

Risk: false sense of security. Mitigations: coverage statistics, review mode, never claiming 100% in UI or docs.

### J. The project itself

| Threat | Mitigation |
|---|---|
| GitHub account takeover | Passkey or hardware key, offline recovery codes |
| Malicious PR | Protected `main`, required CI, CODEOWNERS review for principles, security and invariants |
| CI secret theft | No secrets for fork PRs, actions pinned by SHA, least-privilege tokens |
| Forged release | Trusted Publishing, Sigstore attestations, reproducible builds |
| **Vulnerabilities in AI-written code** | Bandit and Semgrep on every change, invariant tests, full security review before each release |

### K. Availability

Background jobs at low CPU and I/O priority; memory budget and degradation (ARCHITECTURE §9).

## 5. Worker isolation by platform

| Platform | Isolation |
|---|---|
| **Linux** | Resource limits; **Landlock** (unprivileged kernel LSM) restricting filesystem access to the job directory and, on recent kernels, network; syscall filtering |
| Windows | Job Objects for memory and CPU; reduced integrity level (effectiveness to verify) |
| macOS | Resource limits; limited third-party sandboxing |

Minimum kernel versions per Landlock feature to verify; automatic fallback; `sugo doctor` reports the active protection level. The asymmetry is documented: Linux is best protected.

## 6. Declared residual risks

| Risk | Why it remains |
|---|---|
| Unknown vulnerabilities in native parsers | Cannot be prevented; isolation limits damage |
| Downstream prompt injection | Also depends on the receiving LLM |
| Malicious extensions on Windows and macOS | Weaker isolation than Linux |
| Personal data missed by anonymization | No automatic recognition is perfect |
| Physical access to an unlocked machine | Outside any program's control |

## 7. Security process

Private reporting via GitHub; realistic single-maintainer response times; GitHub Security Advisories and CVEs; only the latest minor supported; written and rehearsed emergency release procedure; every fixed vulnerability becomes a permanent regression test.
