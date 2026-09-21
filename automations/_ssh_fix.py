import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

commands = [
    'cd "/var/www/Magnum Opus Consultants/Automation-Platform" && git stash && git pull',
    'systemctl restart moc-gunicorn',
    """for tbl in atl_pnl ccc_pnl ccd_pnl con_pnl dor_pnl fax_pnl hnl_pnl hou_pnl ics_pnl imp_pnl jfk_pnl lax_pnl lcl_pnl ord_pnl dfw_pnl ppg_pnl; do echo "=== $tbl ===" && sudo -u postgres psql -d automation_platform -c "DELETE FROM $tbl WHERE week = 'Week 5' AND budget_actual='Actual';"; done""",
    """sudo -u postgres psql -d automation_platform -c "SELECT date, week, value FROM atl_pnl WHERE account_name='CURRENT YEAR INCOME (LOSS)' AND budget_actual='Actual' AND date BETWEEN 202601 AND 202612 ORDER BY date, week;" """,
]

for cmd in commands:
    print(f'>>> {cmd[:80]}...')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out:
        print(out)
    if err:
        print(err)

ssh.close()
print('DONE')
