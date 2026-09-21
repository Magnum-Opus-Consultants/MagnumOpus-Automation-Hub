import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

commands = [
    # Check ATL weeks + totals in BOTH databases
    ('turnover_data ATL week counts', """sudo -u postgres psql -d turnover_data -c "SELECT budget_actual, week, COUNT(*) FROM atl_pnl GROUP BY budget_actual, week ORDER BY budget_actual, week;" """),
    ('automation_platform ATL week counts', """sudo -u postgres psql -d automation_platform -c "SELECT budget_actual, week, COUNT(*) FROM atl_pnl GROUP BY budget_actual, week ORDER BY budget_actual, week;" """),
    # Check date hierarchy columns
    ('turnover_data ATL date samples', """sudo -u postgres psql -d turnover_data -c "SELECT date, date_fixed, week, budget_actual, report_date FROM atl_pnl LIMIT 10;" """),
    ('automation_platform ATL date samples', """sudo -u postgres psql -d automation_platform -c "SELECT date, date_fixed, week, budget_actual, report_date FROM atl_pnl LIMIT 10;" """),
    # Check ATL CYI with ALL weeks including Total
    ('turnover_data ATL CYI 2026 ALL', """sudo -u postgres psql -d turnover_data -c "SELECT date, week, budget_actual, value FROM atl_pnl WHERE account_name='CURRENT YEAR INCOME (LOSS)' AND date BETWEEN 202601 AND 202612 ORDER BY budget_actual, date, week;" """),
    ('automation_platform ATL CYI 2026 ALL', """sudo -u postgres psql -d automation_platform -c "SELECT date, week, budget_actual, value FROM atl_pnl WHERE account_name='CURRENT YEAR INCOME (LOSS)' AND date BETWEEN 202601 AND 202612 ORDER BY budget_actual, date, week;" """),
]

for label, cmd in commands:
    print(f'\n=== {label} ===')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    print(stdout.read().decode())

ssh.close()
