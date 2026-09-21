import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

commands = [
    ('automation_platform ATL weeks', """sudo -u postgres psql -d automation_platform -c "SELECT week, COUNT(*) FROM atl_pnl GROUP BY week ORDER BY week;" """),
    ('automation_platform ATL CYI 2026', """sudo -u postgres psql -d automation_platform -c "SELECT date, week, value FROM atl_pnl WHERE account_name='CURRENT YEAR INCOME (LOSS)' AND budget_actual='Actual' AND date BETWEEN 202601 AND 202612 ORDER BY date, week;" """),
    ('turnover_data ATL CYI 2026', """sudo -u postgres psql -d turnover_data -c "SELECT date, week, value FROM atl_pnl WHERE account_name='CURRENT YEAR INCOME (LOSS)' AND budget_actual='Actual' AND date BETWEEN 202601 AND 202612 ORDER BY date, week;" """),
]

for label, cmd in commands:
    print(f'\n=== {label} ===')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    print(stdout.read().decode())

ssh.close()
