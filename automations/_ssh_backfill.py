import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

# Run the full backfill on the server using the server's venv + Django
backfill_script = r'''
cd "/var/www/Magnum Opus Consultants/Automation-Platform/automations"
/var/www/Magnum\ Opus\ Consultants/Automation-Platform/venv/bin/python3 -c "
import os, django, base64, io, requests, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'automations.settings')
django.setup()
from django.db import connection
from psycopg2.extras import execute_values
from collections import defaultdict
from dashboard import onedrive_sync
from dashboard.scheduler import STATION_EMAIL_CONFIG, EMAIL_MAILBOX
from dashboard.views import _get_graph_token

class Tok:
    def __init__(self): self.t=_get_graph_token(); self.ts=time.time()
    def get(self):
        if time.time()-self.ts>2400: self.t=_get_graph_token(); self.ts=time.time()
        return self.t
T=Tok()

def req(url, timeout=60, retries=4):
    for i in range(retries):
        try:
            r=requests.get(url, headers={'Authorization': 'Bearer '+T.get()}, timeout=timeout)
            if r.status_code==401: T.t=_get_graph_token(); T.ts=time.time(); continue
            if r.status_code==429: time.sleep(int(r.headers.get('Retry-After','10'))); continue
            r.raise_for_status(); return r
        except (requests.ConnectionError, requests.Timeout):
            if i==retries-1: raise
            time.sleep(5*(i+1))

def fetch_all(sender, subj):
    url='https://graph.microsoft.com/v1.0/users/'+EMAIL_MAILBOX+'/messages?%24top=100&%24orderby=receivedDateTime%20desc&%24select=id,subject,receivedDateTime,from,hasAttachments'
    out=[]
    while url:
        r=req(url,30); j=r.json()
        for m in j.get('value',[]):
            if m.get('hasAttachments') and m.get('from',{}).get('emailAddress',{}).get('address','').lower()==sender.lower() and subj.lower() in m.get('subject','').lower():
                out.append(m)
        url=j.get('@odata.nextLink')
    return out

for KEY in ['atl']:
    sender, subj, parser_name, table = STATION_EMAIL_CONFIG[KEY]
    parser = getattr(onedrive_sync, parser_name)
    msgs = fetch_all(sender, subj)
    msgs.sort(key=lambda m: m['receivedDateTime'])
    print(KEY.upper()+': '+str(len(msgs))+' emails', flush=True)
    with connection.cursor() as cur:
        cur.execute('DELETE FROM '+table+\" WHERE budget_actual='Actual'\")
        print('Wiped '+str(cur.rowcount), flush=True)
    for m in msgs:
        try:
            ar=req('https://graph.microsoft.com/v1.0/users/'+EMAIL_MAILBOX+'/messages/'+m['id']+'/attachments',60)
            x=next((a for a in ar.json().get('value',[]) if a.get('name','').lower().endswith(('.xlsx','.xls'))),None)
            if not x: continue
            rows=parser(io.BytesIO(base64.b64decode(x['contentBytes'])),x['name'])
            if not rows: continue
            with connection.cursor() as cur:
                for dv,wk in set((r[3],r[6]) for r in rows):
                    cur.execute('DELETE FROM '+table+\" WHERE date=%s AND week=%s AND budget_actual='Actual'\",(dv,wk))
                execute_values(cur,'INSERT INTO '+table+' (division,account_name,value,date,date_fixed,budget_actual,week,report_date) VALUES %s',rows)
                # Total rows
                td={}
                for r in rows:
                    k=(r[0],r[1],r[3],r[5])
                    td[k]=(r[0],r[1],r[2],r[3],r[4],r[5],'Total',r[7])
                for dv in set(r[3] for r in rows):
                    cur.execute('DELETE FROM '+table+\" WHERE date=%s AND week='Total' AND budget_actual='Actual'\",(dv,))
                execute_values(cur,'INSERT INTO '+table+' (division,account_name,value,date,date_fixed,budget_actual,week,report_date) VALUES %s',list(td.values()))
        except Exception as e:
            print('  ERR: '+str(e)[:80], flush=True)
    with connection.cursor() as cur:
        cur.execute('SELECT week, COUNT(*) FROM '+table+' GROUP BY week ORDER BY week')
        print('Final weeks:', flush=True)
        for r in cur.fetchall(): print('  '+str(r), flush=True)
        cur.execute(\"SELECT date,week,value FROM \"+table+\" WHERE account_name='CURRENT YEAR INCOME (LOSS)' AND budget_actual='Actual' AND date BETWEEN 202601 AND 202612 ORDER BY date,week\")
        print('CYI 2026:', flush=True)
        for r in cur.fetchall(): print('  '+str(r), flush=True)
print('DONE')
"
'''

print('Running full ATL backfill on server... (this will take a few minutes)')
stdin, stdout, stderr = ssh.exec_command(backfill_script, timeout=600)

# Stream output
for line in iter(stdout.readline, ''):
    print(line.rstrip())
err = stderr.read().decode()
if err and 'Token refresh' not in err:
    print('STDERR:', err[:500])

ssh.close()
