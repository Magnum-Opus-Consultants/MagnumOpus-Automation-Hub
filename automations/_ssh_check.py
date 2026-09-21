import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

commands = [
    # Check turnover_data DB (the one Power BI reads, that works correctly)
    """sudo -u postgres psql -d turnover_data -c "SELECT DISTINCT week FROM atl_pnl ORDER BY week;" """,
    """sudo -u postgres psql -d turnover_data -c "SELECT date, week, value FROM atl_pnl WHERE account_name='CURRENT YEAR INCOME (LOSS)' AND budget_actual='Actual' ORDER BY date, week;" """,
    # Check automation_platform DB (what we're fixing)
    """sudo -u postgres psql -d automation_platform -c "SELECT DISTINCT week FROM atl_pnl ORDER BY week;" """,
    """sudo -u postgres psql -d automation_platform -c "SELECT date, week, value FROM atl_pnl WHERE account_name='CURRENT YEAR INCOME (LOSS)' AND budget_actual='Actual' ORDER BY date, week;" """,
]

labels = ['turnover_data WEEKS:', 'turnover_data ATL CYI:', 'automation_platform WEEKS:', 'automation_platform ATL CYI:']
for label, cmd in zip(labels, commands):
    print(f'\n=== {label} ===')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    print(stdout.read().decode())

ssh.close()
