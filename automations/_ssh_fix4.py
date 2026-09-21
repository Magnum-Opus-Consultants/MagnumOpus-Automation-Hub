import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

commands = [
    ('Clear stale sync state', """echo '{"running": false}' > "/var/www/Magnum Opus Consultants/Automation-Platform/automations/sync_all_state.json" """),
    ('Restart gunicorn', 'systemctl restart moc-gunicorn'),
    ('Verify', """cat "/var/www/Magnum Opus Consultants/Automation-Platform/automations/sync_all_state.json" """),
]

for label, cmd in commands:
    print(f'>>> {label}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err: print(err)

ssh.close()
print('DONE - Refresh the page and click Sync All again')
