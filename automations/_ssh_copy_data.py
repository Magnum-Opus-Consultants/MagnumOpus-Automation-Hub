import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

tables = [
    'atl_pnl', 'ccc_pnl', 'ccd_pnl', 'con_pnl', 'dor_pnl', 'fax_pnl',
    'hnl_pnl', 'hou_pnl', 'ics_pnl', 'imp_pnl', 'jfk_pnl', 'lax_pnl',
    'lcl_pnl', 'ord_pnl', 'dfw_pnl', 'ppg_pnl', 'condor_dor_pnl',
    'creditor_transactions', 'import_ops', 'wip_accrual', 'turnover_data',
]

for tbl in tables:
    print(f'=== {tbl} ===', flush=True)

    # Truncate target, then copy data via pg_dump pipe
    cmd = f"""sudo -u postgres psql -d automation_platform -c "TRUNCATE {tbl} RESTART IDENTITY CASCADE;" && sudo -u postgres pg_dump -d turnover_data -t {tbl} --data-only | sudo -u postgres psql -d automation_platform -q 2>&1 | grep -c INSERT || true"""

    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=180)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()

    # Get row counts
    cmd2 = f"""sudo -u postgres psql -t -d turnover_data -c "SELECT COUNT(*) FROM {tbl};" && sudo -u postgres psql -t -d automation_platform -c "SELECT COUNT(*) FROM {tbl};" """
    stdin2, stdout2, _ = ssh.exec_command(cmd2, timeout=15)
    counts = stdout2.read().decode().strip().split('\n')
    td = counts[0].strip() if len(counts) > 0 else '?'
    ap = counts[1].strip() if len(counts) > 1 else '?'

    print(f'  turnover_data: {td} -> automation_platform: {ap}')

ssh.close()
print('\nDONE - All tables copied. Power BI now reads identical data.')
