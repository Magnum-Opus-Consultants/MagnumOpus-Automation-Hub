#!/usr/bin/env python3
"""Sync all PNL stations except CONDOR+DOR using Django's sync functions"""

import os
import sys
import django

# Add the automations directory to the path
sys.path.insert(0, '/var/www/Magnum Opus Consultants/Automation-Platform/automations')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'automations.settings')

# Setup Django
django.setup()

from dashboard.onedrive_sync import (
    sync_ppg_data, sync_dor_data, sync_con_data,
    sync_atl_data, sync_ccc_data, sync_ccd_data,
    sync_fax_data, sync_hnl_data, sync_hou_data,
    sync_ics_data, sync_imp_data, sync_jfk_data,
    sync_lax_data, sync_lcl_data, sync_ord_data,
    sync_dfw_data
)

# List of stations to sync (excluding CONDOR+DOR)
stations = [
    ('PPG', sync_ppg_data),
    ('DOR', sync_dor_data),
    ('CON', sync_con_data),
    ('ATL', sync_atl_data),
    ('CCC', sync_ccc_data),
    ('CCD', sync_ccd_data),
    ('FAX', sync_fax_data),
    ('HNL', sync_hnl_data),
    ('HOU', sync_hou_data),
    ('ICS', sync_ics_data),
    ('IMP', sync_imp_data),
    ('JFK', sync_jfk_data),
    ('LAX', sync_lax_data),
    ('LCL', sync_lcl_data),
    ('ORD', sync_ord_data),
    ('DFW', sync_dfw_data),
]

print("="*80)
print("SYNCING ALL PNL STATIONS (Except CONDOR+DOR)")
print("="*80)

results = {}

for station_name, sync_func in stations:
    print(f"\n{'='*80}")
    print(f"Syncing {station_name}...")
    print(f"{'='*80}")

    try:
        result = sync_func()
        results[station_name] = result
        print(f"✓ {station_name}: {result}")
    except Exception as e:
        results[station_name] = f"ERROR: {str(e)}"
        print(f"✗ {station_name}: ERROR - {str(e)}")

print(f"\n{'='*80}")
print("SYNC SUMMARY")
print(f"{'='*80}")

for station_name, result in results.items():
    status = "✓" if not str(result).startswith("ERROR") else "✗"
    print(f"{status} {station_name}: {result}")

print(f"\n{'='*80}")
print("SYNC COMPLETE")
print(f"{'='*80}")
