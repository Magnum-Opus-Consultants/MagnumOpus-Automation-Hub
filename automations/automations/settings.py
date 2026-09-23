from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-key')
DEBUG = os.getenv('DJANGO_DEBUG', 'False') == 'True'
ALLOWED_HOSTS = ['workspace.moc-pty.com', '137.184.229.140', '*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'automations.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dashboard.context_processors.theme',
            ],
        },
    },
]

WSGI_APPLICATION = 'automations.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'automation_platform',
        'USER': 'powerbi',
        'PASSWORD': 'MOC_PowerBI_2026_S3cure',
        'HOST': '127.0.0.1',
        'PORT': '5432',
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

LOGIN_URL = '/login/'

# Test mode: override all outgoing touchpoint emails to this address
# Set to None or remove to send to real recipients
TEST_EMAIL_OVERRIDE = None

# AWS SES settings
AWS_SES_ACCESS_KEY_ID = os.getenv('AWS_SES_ACCESS_KEY_ID', '')
AWS_SES_SECRET_ACCESS_KEY = os.getenv('AWS_SES_SECRET_ACCESS_KEY', '')
AWS_SES_REGION = 'eu-west-1'
AWS_SES_FROM_EMAIL = 'waldogaybba@moc-pty.com'

GOOGLE_DRIVE_FOLDER_ID = '1xPGTc8320el4HXmZ3tNsHcavGtZ4asIY'
GOOGLE_CLIENT_SECRET_FILE = str(BASE_DIR.parent / 'Turn over GABE tuesday update' / 'client_secret_929057555993-c86mkjhf08suobk6olcca6sgmudeg8l0.apps.googleusercontent.com.json')
GOOGLE_TOKEN_FILE = str(BASE_DIR / 'token.json')

# OneDrive settings
ONEDRIVE_CLIENT_ID = '43fbe5a9-6b5b-4c81-9067-7aff9ac3ed5a'
ONEDRIVE_TENANT_ID = 'b1504b1d-d096-409a-a0f0-6cc546dde993'
ONEDRIVE_CLIENT_SECRET = os.getenv('ONEDRIVE_CLIENT_SECRET', '')

# ── Copywriting for generated client sites ──────────────────────────────────
# Google AI Studio, free tier. Optional: with no key the site generator falls
# back to its industry content packs, which need no network at all.
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
# Ordered best-first. Override to pin a model or to change the fallback order
# without a deploy.
GEMINI_MODELS = os.getenv('GEMINI_MODELS', '')

# ── AWA data services (CargoWise -> Excel -> SharePoint) ────────────────────
# The report scripts stay on disk where they already are; this platform runs
# them and records what happened. Paths are overridable so a workstation can
# point at a checkout instead of the server's install.
AWA_ROOT = os.getenv('AWA_ROOT', '/opt/awa-data-services')
AWA_ENV_FILE = os.getenv('AWA_ENV_FILE', '/etc/awa-data-services/transit_report.env')
# Blank means: use the virtualenv beside the scripts, which is where their
# openpyxl lives. Set it only to override that.
AWA_PYTHON = os.getenv('AWA_PYTHON', '')
AWA_REPORT_TIMEOUT = int(os.getenv('AWA_REPORT_TIMEOUT', '1500'))
AWA_NOTIFY_TO = os.getenv('AWA_NOTIFY_TO', 'Ethan.Sevenster@moc-pty.com')
PLATFORM_BASE_URL = os.getenv('PLATFORM_BASE_URL', 'https://workspace.moc-pty.com')

# ── CargoWise (WiseGrid) OData ──────────────────────────────────────────────
# Read by dashboard/cargowise.py for the reports this platform pulls itself,
# rather than hands to a script on disk. Credentials come from the environment
# only: with none set the scheduled pull logs that it is not configured and
# does nothing, which is the right behaviour on a machine that should not be
# talking to CargoWise at all.
CW_BASE_URL = os.getenv('CW_BASE_URL', 'https://www-isbint.wisegrid.net')
CW_MODULE = os.getenv('CW_MODULE', 'TWD')
CW_ODATA_MODEL = os.getenv('CW_ODATA_MODEL', 'TransitWarehouse')
CW_USERNAME = os.getenv('CW_USERNAME', '')
CW_PASSWORD = os.getenv('CW_PASSWORD', '')
CW_DEPARTMENT_CODE = os.getenv('CW_DEPARTMENT_CODE', 'BRN')
# Branches the unbooked-cargo pull covers, and the gate-in floor that the saved
# grid view "AWA LAX UNBOOKED CARGO CLEANUP" uses.
RC_PULL_BRANCHES = os.getenv('RC_PULL_BRANCHES', 'DOR,CON')
RC_PULL_GATE_FROM = os.getenv('RC_PULL_GATE_FROM', '2026-08-03')

# ── Up Management Report ────────────────────────────────────────────────────
# Off. This report goes to upper management, so the weekly send stays disabled
# until it is turned on deliberately and a recipient list is set. Generating
# and downloading the PDF works regardless; only the automatic email is gated.
UP_REPORT_AUTOSEND = os.getenv('UP_REPORT_AUTOSEND', 'false')
UP_REPORT_TO = os.getenv('UP_REPORT_TO', '')
ONEDRIVE_REDIRECT_URI = 'http://localhost:8000/onedrive/callback'
# Delegated scopes for the OneDrive file sync only. Mail.Read / Mail.Send are
# registered as *Application* permissions and are used by the separate app-only
# flow (acquire_token_for_client with '.default') — asking for them here requests
# delegated versions that were never consented, which forces an admin-approval
# prompt and blocks the sign-in. Both scopes below are delegated and already
# granted with "Admin consent required: No".
ONEDRIVE_SCOPES = ['Files.Read.All', 'Files.ReadWrite.All']
ONEDRIVE_FOLDER_PATH = '/Automation Platform/Turn Over Automation Report'
ONEDRIVE_PPG_FOLDER_PATH = '/Automation Platform/PPG Financial Analysis Report'
ONEDRIVE_DOR_FOLDER_PATH = '/Automation Platform/DOR Financial Analysis Report'
ONEDRIVE_CON_FOLDER_PATH = '/Automation Platform/CON Financial Analysis Report'
ONEDRIVE_ATL_FOLDER_PATH = '/Automation Platform/ATL Financial Analysis Report'
ONEDRIVE_HNL_FOLDER_PATH = '/Automation Platform/HNL Financial Analysis Report'
ONEDRIVE_JFK_FOLDER_PATH = '/Automation Platform/JFK Financial Analysis Report'
ONEDRIVE_CCC_FOLDER_PATH = '/Automation Platform/CCC Financial Analysis Report'
ONEDRIVE_CCD_FOLDER_PATH = '/Automation Platform/CCD Financial Analysis Report'
ONEDRIVE_FAX_FOLDER_PATH = '/Automation Platform/FAX Financial Analysis Report'
ONEDRIVE_IMP_FOLDER_PATH = '/Automation Platform/IMP Financial Analysis Report'
ONEDRIVE_HOU_FOLDER_PATH = '/Automation Platform/HOU Financial Analysis Report'
ONEDRIVE_ICS_FOLDER_PATH = '/Automation Platform/ICS  Financial Analysis Report'
ONEDRIVE_LAX_FOLDER_PATH = '/Automation Platform/LAX Financial Analysis Report'
ONEDRIVE_LCL_FOLDER_PATH = '/Automation Platform/LCL Financial Analysis Report'
ONEDRIVE_ORD_FOLDER_PATH = '/Automation Platform/ORD Financial Analysis Report'
ONEDRIVE_DFW_FOLDER_PATH = '/Automation Platform/DFW Financial Analysis Report'
ONEDRIVE_IMPORT_OPS_FOLDER_PATH = '/Automation Platform/Import Operational Report MOC'
ONEDRIVE_WIP_ACCRUAL_FOLDER_PATH = '/Automation Platform/Wip And Accrual Report'
ONEDRIVE_CONDOR_DOR_FOLDER_PATH = '/Automation Platform/Condor + Dor PNL'
ONEDRIVE_TFS_FOLDER_PATH = '/Automation Platform/TFS Weekly Data'
ONEDRIVE_TOKEN_FILE = str(BASE_DIR / 'onedrive_token.json')
LAST_SYNC_FILE = str(BASE_DIR / 'last_sync.json')
TURNOVER_LAST_SYNC_FILE = str(BASE_DIR / 'last_sync.json')
CREDITOR_LAST_SYNC_FILE = str(BASE_DIR / 'creditor_last_sync.json')
PPG_LAST_SYNC_FILE = str(BASE_DIR / 'ppg_last_sync.json')
DOR_LAST_SYNC_FILE = str(BASE_DIR / 'dor_last_sync.json')
CON_LAST_SYNC_FILE = str(BASE_DIR / 'con_last_sync.json')
ATL_LAST_SYNC_FILE = str(BASE_DIR / 'atl_last_sync.json')
HNL_LAST_SYNC_FILE = str(BASE_DIR / 'hnl_last_sync.json')
JFK_LAST_SYNC_FILE = str(BASE_DIR / 'jfk_last_sync.json')
CCC_LAST_SYNC_FILE = str(BASE_DIR / 'ccc_last_sync.json')
CCD_LAST_SYNC_FILE = str(BASE_DIR / 'ccd_last_sync.json')
FAX_LAST_SYNC_FILE = str(BASE_DIR / 'fax_last_sync.json')
IMP_LAST_SYNC_FILE = str(BASE_DIR / 'imp_last_sync.json')
HOU_LAST_SYNC_FILE = str(BASE_DIR / 'hou_last_sync.json')
ICS_LAST_SYNC_FILE = str(BASE_DIR / 'ics_last_sync.json')
LAX_LAST_SYNC_FILE = str(BASE_DIR / 'lax_last_sync.json')
LCL_LAST_SYNC_FILE = str(BASE_DIR / 'lcl_last_sync.json')
ORD_LAST_SYNC_FILE = str(BASE_DIR / 'ord_last_sync.json')
DFW_LAST_SYNC_FILE = str(BASE_DIR / 'dfw_last_sync.json')
CONDOR_DOR_LAST_SYNC_FILE = str(BASE_DIR / 'condor_dor_last_sync.json')
IMPORT_OPS_LAST_SYNC_FILE = str(BASE_DIR / 'import_ops_last_sync.json')
WIP_ACCRUAL_LAST_SYNC_FILE = str(BASE_DIR / 'wip_accrual_last_sync.json')
TFS_LAST_SYNC_FILE = str(BASE_DIR / 'tfs_last_sync.json')
SYNC_HEALTH_FILE = str(BASE_DIR / 'sync_health.json')
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
