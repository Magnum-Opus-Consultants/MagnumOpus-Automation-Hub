"""Upload fill_touchpoints_from_excel.py + Book1 4.xlsx to the server, run dry-run."""
import paramiko
import os

HOST = '137.184.229.140'
USER = 'root'
PASS = '2103D018bc163e1ff0415f66b57a1eb'
REMOTE_DIR = '/var/www/Magnum Opus Consultants/Automation-Platform/automations'
VENV_PY = '/var/www/Magnum\\ Opus\\ Consultants/Automation-Platform/venv/bin/python3'

LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
FILES = ['fill_touchpoints_from_excel.py', 'Book1 4.xlsx']

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)

sftp = ssh.open_sftp()
for fname in FILES:
    local = os.path.join(LOCAL_DIR, fname)
    remote = f'{REMOTE_DIR}/{fname}'
    print(f'Uploading {fname} ...')
    sftp.put(local, remote)
    print(f'  -> {remote}')
sftp.close()

cmd = f'cd "{REMOTE_DIR}" && {VENV_PY} fill_touchpoints_from_excel.py'
print(f'\nRunning on server: {cmd}\n')
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=600)
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')
print('===== STDOUT =====')
print(out)
if err.strip():
    print('===== STDERR =====')
    print(err)
ssh.close()
