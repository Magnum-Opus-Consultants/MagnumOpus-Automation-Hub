import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

tables = [
    'atl_pnl', 'ccc_pnl', 'ccd_pnl', 'con_pnl', 'dor_pnl', 'fax_pnl',
    'hnl_pnl', 'hou_pnl', 'ics_pnl', 'imp_pnl', 'jfk_pnl', 'lax_pnl',
    'lcl_pnl', 'ord_pnl', 'dfw_pnl', 'ppg_pnl', 'condor_dor_pnl',
    'creditor_transactions', 'wip_accrual', 'turnover_data',
]

sql_parts = " UNION ALL ".join([
    f"SELECT '{t}' as tbl, (SELECT COUNT(*) FROM turnover_data.public.{t}) as td, (SELECT COUNT(*) FROM automation_platform.public.{t}) as ap"
    for t in tables
])

# Can't cross-database query in postgres. Do it separately.
for t in tables:
    cmd = f"""sudo -u postgres psql -t -d turnover_data -c "SELECT COUNT(*) FROM {t};" """
    _, stdout, _ = ssh.exec_command(cmd, timeout=10)
    td = stdout.read().decode().strip()

    cmd2 = f"""sudo -u postgres psql -t -d automation_platform -c "SELECT COUNT(*) FROM {t};" """
    _, stdout2, _ = ssh.exec_command(cmd2, timeout=10)
    ap = stdout2.read().decode().strip()

    match = "OK" if td == ap else "MISMATCH"
    print(f'{t:25s} turnover={td:>8s}  automation={ap:>8s}  {match}')

ssh.close()
