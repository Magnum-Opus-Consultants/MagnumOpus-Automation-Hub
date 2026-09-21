"""Rebuild customer_spend_summary view — uses shared dynamic logic from load_data.py."""
import os, sys

# Setup Django so load_data can use django.db.connection
os.environ['DJANGO_SETTINGS_MODULE'] = 'automations.settings'
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'automations'))
import django
django.setup()

from data.up_down_trader.load_data import rebuild_summary_view

years = rebuild_summary_view()
if years:
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("SELECT * FROM customer_spend_summary LIMIT 1")
        cols = [desc[0] for desc in cur.description]
    print(f"\nTotal: {len(cols)} columns")
    print("Headers:")
    for i, c in enumerate(cols, 1):
        print(f"  {i}. {c}")
