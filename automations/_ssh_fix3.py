import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

commands = [
    # Pull and restart
    ('Pull & restart', 'cd "/var/www/Magnum Opus Consultants/Automation-Platform" && git stash && git pull && systemctl restart moc-gunicorn'),
    # Verify
    ('Verify commit', 'cd "/var/www/Magnum Opus Consultants/Automation-Platform" && git log --oneline -1'),
]

for label, cmd in commands:
    print(f'>>> {label}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out: print(out.strip())
    if err: print(err.strip())

ssh.close()
print('\nDONE - Now click Sync All Stations on the dashboard')
