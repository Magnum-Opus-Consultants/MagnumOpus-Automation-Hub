import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

commands = [
    ('turnover_data ATL budget_actual values', """sudo -u postgres psql -d turnover_data -c "SELECT budget_actual, COUNT(*) FROM atl_pnl GROUP BY budget_actual;" """),
    ('automation_platform ATL budget_actual values', """sudo -u postgres psql -d automation_platform -c "SELECT budget_actual, COUNT(*) FROM atl_pnl GROUP BY budget_actual;" """),
    ('turnover_data ATL total rows', """sudo -u postgres psql -d turnover_data -c "SELECT COUNT(*) FROM atl_pnl;" """),
    ('automation_platform ATL total rows', """sudo -u postgres psql -d automation_platform -c "SELECT COUNT(*) FROM atl_pnl;" """),
    ('turnover_data ATL sample Budget row', """sudo -u postgres psql -d turnover_data -c "SELECT * FROM atl_pnl WHERE budget_actual='Budget' LIMIT 3;" """),
    ('turnover_data ATL columns', """sudo -u postgres psql -d turnover_data -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='atl_pnl' ORDER BY ordinal_position;" """),
    ('automation_platform ATL columns', """sudo -u postgres psql -d automation_platform -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='atl_pnl' ORDER BY ordinal_position;" """),
]

for label, cmd in commands:
    print(f'\n=== {label} ===')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    print(stdout.read().decode())

ssh.close()
