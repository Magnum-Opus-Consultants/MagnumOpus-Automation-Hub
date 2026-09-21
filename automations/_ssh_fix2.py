import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

commands = [
    # Check if turnover_data has Total rows for ATL
    """sudo -u postgres psql -d turnover_data -c "SELECT week, COUNT(*) FROM atl_pnl GROUP BY week ORDER BY week;" """,
    # Check automation_platform
    """sudo -u postgres psql -d automation_platform -c "SELECT week, COUNT(*) FROM atl_pnl GROUP BY week ORDER BY week;" """,
]

labels = ['turnover_data ATL week counts:', 'automation_platform ATL week counts:']
for label, cmd in zip(labels, commands):
    print(f'\n=== {label} ===')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    print(stdout.read().decode())

ssh.close()
