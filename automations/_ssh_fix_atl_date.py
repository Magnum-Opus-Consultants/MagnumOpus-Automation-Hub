import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

cmd = """sudo -u postgres psql -d automation_platform -c "ALTER TABLE atl_pnl ALTER COLUMN date TYPE DATE USING TO_DATE(date::TEXT, 'YYYYMM');" 2>&1"""

print('Converting atl_pnl.date from integer to DATE...')
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
print(stdout.read().decode().strip())

# Verify
cmd2 = """sudo -u postgres psql -d automation_platform -c "SELECT date FROM atl_pnl LIMIT 5;" """
stdin2, stdout2, _ = ssh.exec_command(cmd2, timeout=15)
print(stdout2.read().decode())

ssh.close()
