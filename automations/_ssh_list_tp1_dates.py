"""List distinct tp1_sent_on values and their counts."""
import paramiko

HOST = '137.184.229.140'
USER = 'root'
PASS = '2103D018bc163e1ff0415f66b57a1eb'

script = r'''
cd "/var/www/Magnum Opus Consultants/Automation-Platform/automations"
../venv/bin/python3 -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'automations.settings')
django.setup()
from dashboard.models import USEUContact
from collections import Counter
c = Counter()
for v in USEUContact.objects.exclude(tp1_sent_on='').values_list('tp1_sent_on', flat=True):
    c[v.strip()] += 1
print('Distinct tp1_sent_on values:')
for v, n in sorted(c.items(), key=lambda x: -x[1]):
    print(f'  {v!r}: {n}')
print(f'Total with tp1_sent_on: {sum(c.values())}')
"
'''

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)
stdin, stdout, stderr = ssh.exec_command(script, timeout=600)
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode('utf-8', errors='replace')
if err.strip():
    print('STDERR:', err)
ssh.close()
