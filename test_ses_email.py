import os
from dotenv import load_dotenv
load_dotenv()
"""Quick test: send one email via AWS SES to verify connectivity."""
import boto3
from botocore.exceptions import ClientError

AWS_ACCESS_KEY = os.getenv('AWS_SES_ACCESS_KEY_ID', '')
AWS_SECRET_KEY = os.getenv('AWS_SES_SECRET_ACCESS_KEY', '')
AWS_REGION = 'eu-west-1'

SENDER = 'ethan.sevenster@moc-pty.com'
RECIPIENT = 'ethan.sevenster@moc-pty.com'
SUBJECT = 'AWS SES Test - Automation Platform'
BODY_TEXT = 'This is a test email sent from the Automation Platform via AWS SES.'
BODY_HTML = '<h2>AWS SES Test</h2><p>This is a test email sent from the <b>Automation Platform</b> via AWS SES.</p>'

client = boto3.client(
    'ses',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
)

try:
    response = client.send_email(
        Source=SENDER,
        Destination={'ToAddresses': [RECIPIENT]},
        Message={
            'Subject': {'Data': SUBJECT, 'Charset': 'UTF-8'},
            'Body': {
                'Text': {'Data': BODY_TEXT, 'Charset': 'UTF-8'},
                'Html': {'Data': BODY_HTML, 'Charset': 'UTF-8'},
            },
        },
    )
    print(f"SUCCESS! Message ID: {response['MessageId']}")
except ClientError as e:
    error = e.response['Error']
    print(f"FAILED: {error['Code']} - {error['Message']}")
except Exception as e:
    print(f"ERROR: {e}")
