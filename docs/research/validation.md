# Research validation — 2026-11-07

- All 32 official archive families/current 9.7 fetched and validated as release histories, not HTTP-200 error pages.
- 42 source documents recorded with hashes: 32 histories and 10 public reference documents, including the older 122-page scripting guide.
- 314 release sections, 4294 bullet records, including 21 nested items (4273 top-level records).
- Section counts reconcile: 583 new-feature bullets + 830 change bullets + 2873 bug-fix bullets + 8 security-note bullets = 4294. These are document sections, not distinct feature/vulnerability counts.
- Every record has a topic navigation tag, stable source-location ID, release and original line number. Tags are keyword classifications, not evidence of semantic review or exploitability.
- 183 manually organized capability/acceptance rows; 36 regression scenarios each resolved to an actual history entry and source location.
- Three research-parser regression tests passed: legacy and singular headings, security sections and nested bullet parentage. Combined with the unchanged prototype tests: 32 passed.
- Standalone browser filter/navigation/pagination JavaScript passed a Node DOM-harness check. Headless Chromium failed to complete rendering in this cloud runtime; native browser visual validation is not claimed.
- Commercial client execution, full installed Help/API, physical Windows COM, full terminal compatibility and long-duration comparison are unverified. No application feature implementation was added during this research correction.
