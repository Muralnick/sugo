# ADR-053: Wider secret exclusions for the MCP server

**Status:** Proposed  
**Date:** 2026-10-31  
**Deciders:** project author  
**Implements:** THREAT_MODEL D, principle 7, ROADMAP v0.1 "light Office and XML reader" (prerequisite)  
**Updates:** ADR-049 (fixed exclusions)  
**Adds error code:** `CONTENT_EXCLUDED`

## Context

ADR-049 refuses, through `sugo mcp`, a short list of folders and files that hold keys and passwords. Today the risk behind a missing entry is small: Sugo recognises a file by its content and reads only PDF, PNG, JPEG and WEBP, so a credentials file is refused as unsupported whatever its name.

ADR-054 adds Office and XML. Many files that hold secrets are XML (FileZilla's saved sites, `NuGet.Config`, Maven's `settings.xml`, Windows `unattend.xml`, Azure `.publishsettings`, Group Policy `Groups.xml`), and a prompt-injected agent could ask for them. The list must therefore grow **before** the reader lands, and a name list alone is not enough: the same secrets can sit in an XML file with an innocent name.

The exclusions still apply only to agents. A person who runs `sugo FILE` chose that file.

## Decision

### Matching

- As in ADR-049: case-insensitive, on the resolved path, never configurable, `PATH_EXCLUDED` on a match, and a root inside an excluded location is refused at start.
- A **folder** entry matches any component of the path; a **file** entry or pattern matches any component too (so a folder with that name is also refused).
- New: a **path sequence** such as `.config/gh` matches those components one after the other anywhere in the path. It is used where one name alone is too common (`gh`, `protect`, `chrome`).
- The lists live in `sugo.core.constants`, as before. A test checks every entry below.

### Lists

Entries kept from ADR-049 are in plain text, new ones in **bold**.

| Kind | Entries |
|---|---|
| Folders | `.ssh`, `.gnupg`, `.aws`, `.azure`, `.kube`, `.docker`, `.password-store`, `keyrings`, **`.git`**, **`.terraform.d`**, **`.bitcoin`**, **`.ethereum`**, **`.electrum`**, **`.mozilla`**, **`.thunderbird`**, **`thunderbird`**, **`bravesoftware`**, **`chromium`**, **`filezilla`** |
| Path sequences: tools | **`.config/gh`**, **`.config/gcloud`**, **`.config/rclone`**, **`.config/hub`**, **`.m2/settings.xml`**, **`.m2/settings-security.xml`**, **`.gradle/gradle.properties`**, **`.subversion/auth`** |
| Path sequences: Windows | **`microsoft/credentials`**, **`microsoft/protect`**, **`microsoft/crypto`**, **`microsoft/vault`**, **`microsoft/systemcertificates`** |
| Path sequences: browsers | **`google/chrome`**, **`microsoft/edge`**, **`.config/google-chrome`**, **`.config/microsoft-edge`**, **`mozilla/firefox`**, **`application support/firefox`** |
| Files | `.netrc`, `.pgpass`, `.env`, **`_netrc`**, **`pgpass.conf`**, **`.git-credentials`**, **`.npmrc`**, **`.pypirc`**, **`.yarnrc`**, **`.yarnrc.yml`**, **`.my.cnf`**, **`.boto`**, **`.s3cfg`**, **`.vault-token`**, **`.htpasswd`**, **`.histfile`**, **`consolehost_history.txt`**, **`wallet.dat`**, **`nuget.config`**, **`sitemanager.xml`**, **`recentservers.xml`**, **`filezilla.xml`**, **`unattend.xml`**, **`autounattend.xml`**, **`groups.xml`**, **`web.config`**, **`app.config`**, **`login data`**, **`web data`**, **`cookies`**, **`logins.json`**, **`key3.db`**, **`key4.db`**, **`cookies.sqlite`**, **`signons.sqlite`** |
| Patterns | `id_rsa*`, `id_dsa*`, `id_ecdsa*`, `id_ed25519*`, `.env.*`, `*.kdbx`, `*.pem`, **`*.kdb`**, **`*.key`**, **`*.p8`**, **`*.p12`**, **`*.pfx`**, **`*.jks`**, **`*.keystore`**, **`*.ppk`**, **`*.ovpn`**, **`*.tfstate`**, **`*.tfstate.*`**, **`*.publishsettings`**, **`credentials*`**, **`secrets.*`**, **`*_history`** |

`*_history` covers `.bash_history`, `.zsh_history`, `.python_history`, `.psql_history`, `.mysql_history` and `.node_repl_history`. Browser entries cover Chrome, Edge, Brave, Chromium and Firefox on Windows, macOS and Linux, and Thunderbird's mail profiles.

### Content check (MCP only)

Before anything reaches the agent, the server refuses a document with **`CONTENT_EXCLUDED`** (exit code `SECURITY`) when:

- in a generic XML file, an element or attribute name, without its namespace prefix, casefolded and with `-`, `_` and `.` removed, is one of: `password`, `passwd`, `pwd`, `cpassword`, `passphrase`, `secret`, `clientsecret`, `sharedsecret`, `apikey`, `accesskey`, `secretkey`, `privatekey`, `accesstoken`, `refreshtoken`, `authtoken`, `apitoken`, `bearertoken`, `connectionstring`; or
- the document's text contains the end of a private key header, `PRIVATE KEY-----` (PEM) or `PRIVATE KEY BLOCK-----` (OpenPGP), in any kind of document, and in XML attribute values too. The match ignores case and tolerates what OCR and layout do to it: white space or a line break before the dashes, dashes read as en or em dashes, and at least three of them.

Only names and the PEM marker are looked at, never other values, and the message names neither the element nor the file. The name check covers generic XML only: the part names inside DOCX, XLSX and PPTX are fixed by the standard and say nothing about the content; it lands with the XML reader (ADR-054).

The PEM marker is checked now, case-insensitively, on the whole text `convert_document` would return (Markdown or chunks), for **every** kind of document: a private key pasted in a PDF, photographed in a screenshot or typed in an Office file never reaches the agent. The check runs before any part is returned, so every part of such a document is refused alike. `estimate_savings` returns only counts and is not affected.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Names only, no content check | An XML file with an innocent name, or a copy of a config file, would pass |
| Look for secrets in every value (entropy, token formats) | Many false positives on invoices and IDs, slower, and values would have to be inspected and kept in memory longer |
| Bare `token` and `key` as excluded names | Common in linguistic corpora (TEI) and ordinary data |
| Folder names alone for `gh`, `protect`, `chrome` | Would refuse ordinary project folders; path sequences are precise |
| Letting the user add or remove entries | A prompt-injected agent cannot edit the list, but a mistaken config could weaken it; additions may come with policies after v0.1 |

## Consequences

- New stable error code `CONTENT_EXCLUDED`.
- Some legitimate files are refused to agents: a document named `credentials.docx` or `secrets.pdf`, a project's `web.config`, anything inside a `.git` folder, an XML schema that defines a `password` element. The person can still convert them with the CLI.
- Agents usually have their own file access; these exclusions protect what goes through Sugo and keep Sugo from being the easy path. They do not replace the agent's own permissions.
- Residual: a secret in a file with an unlisted name and in a format other than XML (a DOCX with a password typed in a table) still reaches the agent. Detecting that needs content classification, considered with the `legal` features (ADR-014).
