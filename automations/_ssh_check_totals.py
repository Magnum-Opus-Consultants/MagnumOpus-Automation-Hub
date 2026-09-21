import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

cmd = """sudo -u postgres psql -d automation_platform -c "SELECT week, budget_actual, COUNT(*) FROM atl_pnl GROUP BY week, budget_actual ORDER BY budget_actual, week;" """
_, stdout, _ = ssh.exec_command(cmd, timeout=15)
print('ATL week/budget counts:')
print(stdout.read().decode())

cmd2 = """sudo -u postgres psql -d automation_platform -c "SELECT date, week, budget_actual, value FROM atl_pnl WHERE account_name='CURRENT YEAR INCOME (LOSS)' AND week='Total' ORDER BY date LIMIT 15;" """
_, stdout2, _ = ssh.exec_command(cmd2, timeout=15)
print('ATL Total rows:')
print(stdout2.read().decode())

ssh.close()
