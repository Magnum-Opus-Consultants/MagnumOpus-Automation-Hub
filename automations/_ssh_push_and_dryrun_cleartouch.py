"""Upload clear_bad_last_touch.py to the server, run dry-run."""
import os

import paramiko

HOST = '137.184.229.140'
USER = 'root'
PASS = '2103D018bc163e1ff0415f66b57a1eb'
REMOTE_DIR = '/var/www/Magnum Opus Consultants/Automation-Platform/automations'
VENV_PY = '/var/www/Magnum\\ Opus\\ Consultants/Automation-Platform/venv/bin/python3'

LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
FILES = ['clear_bad_last_touch.py']

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)

sftp = ssh.open_sftp()
for fname in FILES:
    local = os.path.join(LOCAL_DIR, fname)
    remote = f'{REMOTE_DIR}/{fname}'
    print(f'Uploading {fname} ...')
    sftp.put(local, remote)
sftp.close()

cmd = f'cd "{REMOTE_DIR}" && {VENV_PY} clear_bad_last_touch.py'
print(f'\nRunning on server: {cmd}\n')
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=600)
print('===== STDOUT =====')
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode('utf-8', errors='replace')
if err.strip():
    print('===== STDERR =====')
    print(err)
ssh.close()
