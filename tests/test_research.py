import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('research_securecrt', Path(__file__).parents[1] / 'scripts' / 'research_securecrt.py')
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def test_legacy_and_modern_headings_preserve_every_record_and_source_line():
    text = '''Changes in SecureCRT 3.1 (Official)
Change:
  - A synthetic connection change.
    Wrapped continuation.
Bug fix:
  - A synthetic freeze.
All inquiries should be directed to:
not release content
'''
    releases, entries = research.parse_history(text, '3.2', 'https://example.invalid/history.txt')
    assert len(releases) == 1
    assert len(entries) == 2
    assert entries[0]['date'] is None
    assert entries[0]['section'] == 'changes'
    assert entries[0]['line'] == 3
    assert entries[0]['text'].endswith('Wrapped continuation.')
    assert entries[1]['section'] == 'bug-fixes'
    assert entries[1]['text'] == 'A synthetic freeze.'
    assert entries[0]['id'] != entries[1]['id']


def test_security_and_singular_feature_headings_are_not_swallowed():
    text = '''Changes in SecureCRT 9.7.4 (Official) -- November 3, 2026
Vulnerability Fix:
  - A synthetic packet validation change.
New Feature:
  - A synthetic serial option.
Bugs Fixes:
  - A synthetic configuration fix.
'''
    releases, entries = research.parse_history(text, '9.7', 'https://example.invalid/history.txt')
    assert releases[0]['date'] == 'November 3, 2026'
    assert [e['section'] for e in entries] == ['security-notes','new-features','bug-fixes']
    assert all('Fixes:' not in e['text'] for e in entries)


def test_nested_bullets_keep_parent_and_do_not_change_release_identity():
    text = '''Changes in SecureCRT 5.0 (Beta 5) -- Example date
New features:
  - Synthetic tab options:
    - First option.
    - Second option.
  - A separate feature.
'''
    _, entries = research.parse_history(text, '5.0', 'https://example.invalid/history.txt')
    assert len(entries) == 4
    assert entries[0]['parent_id'] is None
    assert entries[1]['parent_id'] == entries[0]['id']
    assert entries[2]['parent_id'] == entries[0]['id']
    assert entries[3]['parent_id'] is None
    assert len({x['release'] for x in entries}) == 1
