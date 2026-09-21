STATIONS_NAV = [
    ('TRN', 'turnover', 'Turnover'),
    ('ATL', 'atl', 'ATL'),
    ('CCC', 'ccc', 'CCC'),
    ('CCD', 'ccd', 'CCD'),
    ('CON', 'con', 'CON'),
    ('DOR', 'dor', 'DOR'),
    ('FAX', 'fax', 'FAX'),
    ('HNL', 'hnl', 'HNL'),
    ('HOU', 'hou', 'HOU'),
    ('ICS', 'ics', 'ICS'),
    ('IMP', 'imp', 'IMP'),
    ('JFK', 'jfk', 'JFK'),
    ('LAX', 'lax', 'LAX'),
    ('LCL', 'lcl', 'LCL'),
    ('ORD', 'ord', 'ORD'),
    ('DFW', 'dfw', 'DFW'),
    ('PPG', 'ppg', 'PPG'),
    ('CDR', 'condor_dor', 'Condor+DOR'),
    ('IOP', 'import_ops', 'Import Ops'),
    ('WIP', 'wip_accrual', 'WIP & Accrual'),
    ('CRD', 'creditor', 'Creditor'),
]


def theme(request):
    dark_mode = False
    # Page-access flags exposed to every template for sidebar visibility.
    # Default: deny. Superusers always see everything.
    access = {
        'can_data_analysis': False, 'can_emailing': False, 'can_planner': False,
        'can_sync_monitor': False, 'can_automations': False,
    }
    if request.user.is_authenticated:
        try:
            p = request.user.profile
            dark_mode = p.dark_mode
            if request.user.is_superuser:
                access = {k: True for k in access}
            else:
                for k in access:
                    access[k] = getattr(p, k, False)
        except Exception:
            pass
    return {'dark_mode': dark_mode, 'stations_nav': STATIONS_NAV, **access}
