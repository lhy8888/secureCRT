# Historical 0.1 setup validation — 2026-11-07

This is the earlier setup record. Current results and research access status are in [0.4.1 validation](validation-0.4.1.md); the policy-403 observation below was specific to the earlier run.

- Linux x86_64 cloud instance; Python 3.12.14; Rust 1.97.0.
- `bash /workspace/setup-cloud.sh`: completed with exit 0 after adding explicit Python package discovery.
- `python -m pytest -q`: **29 passed**, 1.16 seconds in final setup-script run.
- SSH: actual loopback encrypted connections, host-key rejection, authentication rejection, handshake deadline, 8 concurrent sessions over 3 rounds.
- Serial: Unix PTY bidirectional stream, short-write error, real worker → Qt terminal integration and worker stop.
- UI/config: offscreen startup, UTF-8 fragmentation, ANSI behavior, clipboard protection, bounded input, atomic profile persistence, malformed files rejected, parser-error shutdown.
- Parser: 1,000,000-character unfinished OSC/DCS/APC/PM/SOS inputs, oversized CSI, non-ASCII CSI digits; retained sequence state <=128 characters, recovery verified.
- Dependency audit: pip-audit, PyPI service, 20 pinned distributions, no known vulnerabilities reported. This does not establish absence of undiscovered vulnerabilities or replace application security review.
- `pip check`: no broken requirements.
- Craft Anything: source commit 9f4c3c209b3c8877ec7db2241c6ac295cf8b83ab, CLI 0.4.0 built with locked Cargo dependencies; doctor exit 0; MCP self-test answered; an owned synthetic ELF recognized as x86_64/Linux. See craft-doctor.txt and craft-triage.json.
- A Codex agent_cli backend was configured. No end-to-end AI rebuild or model-authentication test was performed; the desktop Craft Anything GUI was not built.
- The official SecureCRT history URL and GitHub API returned policy 403 before draft changes; these operations remain unverified. Required domains are saved in the draft, not applied or published by the agent.
- Windows CI and packaging scripts are present but have not executed on Windows. No signed or unsigned Windows executable was produced in this Linux environment.
- No physical COM hardware, long-duration soak, SecureCRT 9.7.4 side-by-side benchmark, external audit, publication or fresh-task restoration has been verified.
- Code remains in the workspace without a Git commit or push. Source archive is a portable copy of this implementation, not a Windows executable.
