"""Upload date filter changes (views.py + useu_list.html) and restart the app."""
import os
import paramiko

HOST = '137.184.229.140'
USER = 'root'
PASS = '2103D018bc163e1ff0415f66b57a1eb'
REMOTE_BASE = '/var/www/Magnum Opus Consultants/Automation-Platform'

LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
FILES = [
    ('dashboard/views.py', f'{REMOTE_BASE}/automations/dashboard/views.py'),
    ('templates/useu_list.html', f'{REMOTE_BASE}/automations/templates/useu_list.html'),
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)

sftp = ssh.open_sftp()
for local_rel, remote in FILES:
    local = os.path.join(LOCAL_DIR, local_rel.replace('/', os.sep))
    print(f'Uploading {local_rel} -> {remote}')
    sftp.put(local, remote)
sftp.close()

# Quick syntax check then restart gunicorn service so changes take effect
restart_cmd = r'''
cd "/var/www/Magnum Opus Consultants/Automation-Platform/automations"
../venv/bin/python3 -c "import ast; ast.parse(open('dashboard/views.py').read()); print('views.py syntax OK')"
systemctl restart automation-platform 2>&1 || systemctl restart gunicorn 2>&1 || echo 'no service matched; reload manually'
systemctl status automation-platform --no-pager -l 2>&1 | head -15 || true
'''
stdin, stdout, stderr = ssh.exec_command(restart_cmd, timeout=120)
print('===== OUT =====')
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode('utf-8', errors='replace')
if err.strip():
    print('===== ERR =====')
    print(err)
ssh.close()
