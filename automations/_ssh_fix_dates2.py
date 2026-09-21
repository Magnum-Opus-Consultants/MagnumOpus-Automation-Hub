import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('137.184.229.140', username='root', password='2103D018bc163e1ff0415f66b57a1eb', timeout=15)

tables = [
    'atl_pnl', 'ccc_pnl', 'ccd_pnl', 'con_pnl', 'dor_pnl', 'fax_pnl',
    'hnl_pnl', 'hou_pnl', 'ics_pnl', 'imp_pnl', 'jfk_pnl', 'lax_pnl',
    'lcl_pnl', 'ord_pnl', 'dfw_pnl', 'ppg_pnl',
]

for tbl in tables:
    for db in ['automation_platform', 'turnover_data']:
        # Handle multiple formats: "01 April 2024", "2025-02-01", empty strings, NULLs
        cmd = f"""sudo -u postgres psql -d {db} -c "
            ALTER TABLE {tbl} ALTER COLUMN date_fixed TYPE DATE USING
                CASE
                    WHEN date_fixed IS NULL OR TRIM(date_fixed) = '' THEN NULL
                    WHEN date_fixed ~ '^\\\\d{{4}}-\\\\d{{2}}-\\\\d{{2}}' THEN date_fixed::DATE
                    WHEN date_fixed ~ '^\\\\d{{2}} ' THEN TO_DATE(date_fixed, 'DD Month YYYY')
                    ELSE NULL
                END;
        " 2>&1"""
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
        out = stdout.read().decode().strip()
        status = 'OK' if 'ALTER TABLE' in out else out[:100]
        print(f'{db}.{tbl}: {status}')

ssh.close()
print('\nDONE')
