"""Clear USEUContact.last_touch values that are not a valid touchpoint number.

The `last_touch` field is supposed to hold a touchpoint number (1-10) or be empty.
An earlier backfill accidentally stored date strings (like '04-03-2026') in this
field, which the UI then rendered as "TP04-03-2026". This script finds those rows
and clears the field back to empty.

Usage (on server, from the automations/ directory):
    # dry-run (default, no writes)
    ../venv/bin/python3 clear_bad_last_touch.py
    # actually apply
    ../venv/bin/python3 clear_bad_last_touch.py --apply
"""
import argparse
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'automations.settings')
django.setup()

from dashboard.models import USEUContact  # noqa: E402


VALID = {str(n) for n in range(1, 11)}


def is_bad(val):
    if val is None:
        return False
    s = str(val).strip()
    if s == '':
        return False
    return s not in VALID


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Actually write changes (default dry-run)')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    bad_rows = []
    total = 0
    for c in USEUContact.objects.all().iterator():
        total += 1
        if is_bad(c.last_touch):
            bad_rows.append(c)

    print(f'Scanned {total} USEUContact rows.')
    print(f'Rows with bad last_touch (not empty, not 1-10): {len(bad_rows)}')

    if bad_rows:
        print('\nSample (first 10):')
        for c in bad_rows[:10]:
            print(f'  id={c.id}  org={c.org_name!r}  last_touch={c.last_touch!r}')

    if not args.apply:
        print('\nDRY-RUN. No changes written. Re-run with --apply to clear.')
        return

    print('\nClearing bad last_touch values ...')
    written = 0
    for c in bad_rows:
        c.last_touch = ''
        c.save(update_fields=['last_touch'])
        written += 1
    print(f'Done. Cleared {written} rows.')


if __name__ == '__main__':
    main()
