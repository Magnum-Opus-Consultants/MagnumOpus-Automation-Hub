"""Find and restart the web service for the automation platform."""
import paramiko

HOST = '137.184.229.140'
USER = 'root'
PASS = '2103D018bc163e1ff0415f66b57a1eb'

cmd = r'''
echo '--- services matching automation/magnum/gunicorn/django ---'
systemctl list-units --type=service --all --no-pager 2>/dev/null | grep -iE 'magnum|automation|gunicorn|django|uwsgi|django|nginx' || true
echo '--- processes ---'
ps -ef | grep -iE 'gunicorn|uwsgi|runserver|wsgi' | grep -v grep || true
echo '--- services.d ---'
ls /etc/systemd/system/ 2>/dev/null | grep -iE 'magnum|automation|gunicorn' || true
'''
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode('utf-8', errors='replace')
if err.strip():
    print('ERR:', err)
ssh.close()
