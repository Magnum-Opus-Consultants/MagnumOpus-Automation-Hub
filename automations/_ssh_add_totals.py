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
    # Add Actual Total rows: for each (date, division, account_name),
    # take the value from the highest week number (latest snapshot = month-end total)
    cmd = f"""sudo -u postgres psql -d automation_platform -c "
        INSERT INTO {tbl} (division, account_name, value, date, date_fixed, budget_actual, week, report_date)
        SELECT DISTINCT ON (date, division, account_name)
            division, account_name, value, date, date_fixed, 'Actual', 'Total', report_date
        FROM {tbl}
        WHERE budget_actual = 'Actual'
          AND week != 'Total'
          AND (date, division, account_name) NOT IN (
              SELECT date, division, account_name FROM {tbl}
              WHERE budget_actual = 'Actual' AND week = 'Total'
          )
        ORDER BY date, division, account_name,
            CASE week
                WHEN 'Week 5' THEN 5
                WHEN 'Week 4' THEN 4
                WHEN 'Week 3' THEN 3
                WHEN 'Week 2' THEN 2
                WHEN 'Week 1' THEN 1
                ELSE 0
            END DESC;
    " 2>&1"""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    out = stdout.read().decode().strip()
    print(f'{tbl}: {out}')

# Verify ATL
cmd2 = """sudo -u postgres psql -d automation_platform -c "SELECT budget_actual, week, COUNT(*) FROM atl_pnl GROUP BY budget_actual, week ORDER BY budget_actual, week;" """
_, stdout2, _ = ssh.exec_command(cmd2, timeout=15)
print('\nATL final:')
print(stdout2.read().decode())

ssh.close()
