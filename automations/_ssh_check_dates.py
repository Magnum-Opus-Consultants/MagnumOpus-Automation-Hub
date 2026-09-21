import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

cmd = """sudo -u postgres psql -d automation_platform -c "SELECT DISTINCT date_fixed FROM atl_pnl ORDER BY date_fixed LIMIT 20;" """
_, stdout, _ = ssh.exec_command(cmd, timeout=15)
print('ATL date_fixed samples:')
print(stdout.read().decode())

ssh.close()
