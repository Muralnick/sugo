# ADR-027: Backup and disaster recovery

**Status:** Accepted  
**Date:** 2026-10-27  
**Deciders:** project author

## Context

The author is sensitive to security and continuity; precious data (registry, maps, audit) must survive failures; the project itself must survive account or machine loss.

## Decision

Recovery paths for power loss, corruption, failed upgrades, full disks, crashes, lost machines and ransomware. Optional automatic encrypted backups of precious data with rotation; clear warning that a lost passphrase is unrecoverable; 3-2-1 guidance. Project continuity: 2FA/passkey, offline recovery codes, mirror repository, Trusted Publishing, keyless signing, in-repo decisions, lockfile.

## Alternatives considered

| Alternative | Why not |
|---|---|
| No built-in backups | Users rarely back up application data on their own |

## Consequences

- Backup restore is part of the test suite.
