import hashlib
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class ProjectTask(models.Model):
    STATUS_CHOICES = [
        ('backlog', 'Backlog'),
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        # Distinct from plain in-progress: the work has stopped pending an
        # answer from us, which is a different report line and a different
        # conversation from work that is simply underway.
        ('in_progress_guidance', 'In Progress (Guidance Required)'),
        ('review', 'Review'),
        ('review_pending', 'Completed (Review Pending)'),
        ('discrepancy', 'Completed (Data Discrepancy Addressing)'),
        ('on_hold', 'On Hold'),
        ('cancelled', 'Cancelled'),
        ('done', 'Done'),
    ]
    PRIORITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]

    # These three columns exist in dashboard_projecttask but were never declared
    # here (they were added to the database outside migrations), which made
    # ProjectTask.objects.create(company=..., start_time=..., end_time=...) in
    # views.py raise TypeError and get_company_display() raise AttributeError.
    # Declared here so model and table agree; migration 0044 syncs Django's
    # state only, since the columns are already present.
    COMPANY_CHOICES = [
        ('magnum_opus', 'Magnum Opus Consultants'),
        ('food_safety', 'Food Safety Agency'),
        ('eclick', 'E-Click'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='backlog')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    project_name = models.CharField(max_length=100, blank=True, default='')
    # ClickUp-style hierarchy: a project holds lists, a list holds tasks, a task
    # holds subtasks. Kept as a label on the task (like project_name) rather
    # than its own table, so the two levels stay consistent.
    list_name = models.CharField(max_length=100, blank=True, default='')
    company = models.CharField(max_length=20, choices=COMPANY_CHOICES, blank=True, default='')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='subtasks')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    # A running timer, ClickUp-style. Set when somebody starts the clock and
    # cleared when they stop it, at which point the elapsed time is added to
    # actual_hours. Stored rather than held in the browser so the clock keeps
    # running across a reload, a different machine, or a closed laptop.
    timer_started_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the running timer was started. Null means not running.')

    # Time tracking. Kept as hours rather than minutes because that is how the
    # work is quoted and reviewed; null means "not estimated / not logged yet",
    # which is different from a genuine 0.
    estimated_hours = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    actual_hours = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    # What kind of work this is, which decides who has to sign it off. Quoted
    # work needs nobody; anything touching the quality management system needs
    # QMS involved before it ships. This is the field that stops "we just added
    # it while we were in there" becoming an audit finding.
    DEVELOPMENT_CHOICES = [
        ('original_quoted', 'Original / Quoted Development'),
        ('new_development', 'New Development'),
        ('new_development_qms', 'New Development - QMS must be involved'),
        ('new_development_qms_change', 'New Development - QMS Change'),
        ('new_quoted_development', 'New Development / Quoted Development'),
        ('ongoing_development', 'Ongoing Development'),
    ]
    development_status = models.CharField(
        max_length=32, choices=DEVELOPMENT_CHOICES, blank=True, default='')

    # Which stream the work belongs to. The management report splits every
    # client's delivery into WEB, APP and API and shows completed against
    # outstanding for each, and nothing recorded which was which.
    STREAM_CHOICES = [
        ('web', 'WEB'),
        ('app', 'APP'),
        ('api', 'API'),
        ('support', 'Support'),
        ('internal', 'Internal / Admin'),
    ]
    stream = models.CharField(max_length=12, choices=STREAM_CHOICES,
                              blank=True, default='')
    assigned_users = models.ManyToManyField(
        User, blank=True, related_name='assigned_tasks')
    # Set the first time the task reaches a done state, so cycle time can be
    # measured without trusting updated_at, which moves on every edit.
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    @property
    def duration_days(self):
        """Calendar days the task spans, inclusive. None if not scheduled."""
        if not self.start_date or not self.end_date:
            return None
        return abs((self.end_date - self.start_date).days) + 1

    def __str__(self):
        return self.title


class PowerBIEmbed(models.Model):
    page_name = models.CharField(max_length=50, unique=True)
    embed_url = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'powerbi_embed'

    def __str__(self):
        return self.page_name


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    dark_mode = models.BooleanField(default=False)
    # Legacy per-page access flags (columns already exist in the DB as NOT NULL).
    # Declared here so the auto-create signal can insert valid defaults.
    can_data_analysis = models.BooleanField(default=False)
    can_sync_monitor = models.BooleanField(default=False)
    can_emailing = models.BooleanField(default=False)
    can_planner = models.BooleanField(default=False)
    can_automations = models.BooleanField(default=False)

    class Meta:
        db_table = 'user_profile'

    def __str__(self):
        return self.user.username

    def has_page(self, key):
        """Check if this profile's user can access a page key.

        Used by templates/base.html and context_processors.py on the server.
        """
        if self.user.is_superuser:
            return True
        return getattr(self, f'can_{key}', False)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


class USEUContact(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Undeliverable', 'Undeliverable'),
        ('Inactive', 'Inactive'),
        ('Lost', 'Lost'),
        ('Move to HubSpot', 'Move to HubSpot'),
    ]

    title = models.CharField(max_length=255, blank=True, default='')
    org_name = models.CharField(max_length=500, blank=True, default='')
    default = models.CharField(max_length=10, blank=True, default='')
    contact_name = models.CharField(max_length=255, blank=True, default='')
    mode = models.CharField(max_length=50, blank=True, default='')
    attach = models.CharField(max_length=50, blank=True, default='')
    job_title = models.CharField(max_length=255, blank=True, default='')
    address = models.CharField(max_length=500, blank=True, default='')
    branch = models.CharField(max_length=50, blank=True, default='')
    unloco = models.CharField(max_length=50, blank=True, default='')
    city = models.CharField(max_length=255, blank=True, default='')
    phone = models.CharField(max_length=100, blank=True, default='')
    fax = models.CharField(max_length=100, blank=True, default='')
    email = models.CharField(max_length=255, blank=True, default='')
    sales_rep = models.CharField(max_length=100, blank=True, default='')
    touchpoint_1 = models.CharField(max_length=50, blank=True, default='')
    touchpoint_2 = models.CharField(max_length=50, blank=True, default='')
    touchpoint_3 = models.CharField(max_length=50, blank=True, default='')
    touchpoint_4 = models.CharField(max_length=50, blank=True, default='')
    touchpoint_5 = models.CharField(max_length=50, blank=True, default='')
    touchpoint_6 = models.CharField(max_length=50, blank=True, default='')
    touchpoint_7 = models.CharField(max_length=50, blank=True, default='')
    touchpoint_8 = models.CharField(max_length=50, blank=True, default='')
    touchpoint_9 = models.CharField(max_length=50, blank=True, default='')
    touchpoint_10 = models.CharField(max_length=50, blank=True, default='')
    last_touch = models.CharField(max_length=50, blank=True, default='')
    journey_status = models.CharField(max_length=50, blank=True, default='Active')
    tp1_sent_on = models.CharField(max_length=50, blank=True, default='')
    tp2_sent_on = models.CharField(max_length=50, blank=True, default='')
    tp3_sent_on = models.CharField(max_length=50, blank=True, default='')
    tp4_sent_on = models.CharField(max_length=50, blank=True, default='')
    tp5_sent_on = models.CharField(max_length=50, blank=True, default='')
    tp6_sent_on = models.CharField(max_length=50, blank=True, default='')
    tp7_sent_on = models.CharField(max_length=50, blank=True, default='')
    tp8_sent_on = models.CharField(max_length=50, blank=True, default='')
    tp9_sent_on = models.CharField(max_length=50, blank=True, default='')
    tp10_sent_on = models.CharField(max_length=50, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    # Present in production via server migrations 0037 / 0041.
    moved_to_hubspot_at = models.DateTimeField(null=True, blank=True, db_index=True)
    opted_out_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deal_lost_reason = models.CharField(max_length=500, blank=True, default='')
    tp1_processing_id = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'useu_contacts'
        ordering = ['id']

    def __str__(self):
        return self.org_name


class TouchpointTemplate(models.Model):
    """Email template for each touchpoint (1-10). One template per touchpoint number."""
    touchpoint_number = models.IntegerField(unique=True)
    subject = models.CharField(max_length=500, default='')
    body = models.TextField(default='')
    body_html = models.TextField(default='', blank=True)
    signature = models.TextField(default='', blank=True)
    attachment = models.FileField(upload_to='touchpoint_attachments/', blank=True, null=True)
    signature_image = models.FileField(upload_to='touchpoint_signatures/', blank=True, null=True,
                                       help_text='Inline signature image (referenced via cid:signature_tpN).')
    days_after_previous = models.IntegerField(default=7, help_text='Days after previous touchpoint to send this one')
    scheduled_date = models.DateField(null=True, blank=True, help_text='Fixed date to automatically send this touchpoint')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'touchpoint_templates'
        ordering = ['touchpoint_number']

    def __str__(self):
        return f'Touchpoint {self.touchpoint_number}'


class ImportOps(models.Model):
    shipment_id = models.CharField(max_length=500, blank=True, default='')
    shipment_direction = models.CharField(max_length=500, blank=True, default='')
    report_date = models.CharField(max_length=500, blank=True, default='')
    trans = models.CharField(max_length=500, blank=True, default='')
    customs_info = models.CharField(max_length=500, blank=True, default='')
    mode = models.CharField(max_length=500, blank=True, default='')
    origin = models.CharField(max_length=500, blank=True, default='')
    origin_country = models.CharField(max_length=500, blank=True, default='')
    destination = models.CharField(max_length=500, blank=True, default='')
    destination_country = models.CharField(max_length=500, blank=True, default='')
    consignor_code = models.CharField(max_length=500, blank=True, default='')
    consignor_name = models.CharField(max_length=500, blank=True, default='')
    consignee_code = models.CharField(max_length=500, blank=True, default='')
    consignee_name = models.CharField(max_length=500, blank=True, default='')
    house_ref = models.CharField(max_length=500, blank=True, default='')
    incoterm = models.CharField(max_length=500, blank=True, default='')
    additional_terms = models.CharField(max_length=500, blank=True, default='')
    ppd_ccx = models.CharField(max_length=500, blank=True, default='')
    goods_description = models.CharField(max_length=500, blank=True, default='')
    origin_etd = models.CharField(max_length=500, blank=True, default='')
    destination_eta = models.CharField(max_length=500, blank=True, default='')
    weight = models.CharField(max_length=500, blank=True, default='')
    weight_unit = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        db_table = 'import_ops'
        managed = False

    def __str__(self):
        return self.shipment_id


class WipAccrual(models.Model):
    type = models.CharField(max_length=500, blank=True, default='')
    branch = models.CharField(max_length=500, blank=True, default='')
    dept = models.CharField(max_length=500, blank=True, default='')
    charge_code = models.CharField(max_length=500, blank=True, default='')
    job = models.CharField(max_length=500, blank=True, default='')
    local_ref = models.CharField(max_length=500, blank=True, default='')
    wip = models.CharField(max_length=500, blank=True, default='')
    accrual = models.CharField(max_length=500, blank=True, default='')
    net_total = models.CharField(max_length=500, blank=True, default='')
    added = models.CharField(max_length=500, blank=True, default='')
    age = models.CharField(max_length=500, blank=True, default='')
    debtor_creditor = models.CharField(max_length=500, blank=True, default='')
    stat = models.CharField(max_length=500, blank=True, default='')
    job_branch = models.CharField(max_length=500, blank=True, default='')
    controlling_agent = models.CharField(max_length=500, blank=True, default='')
    controlling_customer = models.CharField(max_length=500, blank=True, default='')
    management_group = models.CharField(max_length=500, blank=True, default='')
    exp_group = models.CharField(max_length=500, blank=True, default='')
    orig = models.CharField(max_length=500, blank=True, default='')
    eta = models.CharField(max_length=500, blank=True, default='')
    etd = models.CharField(max_length=500, blank=True, default='')
    posted_by = models.CharField(max_length=500, blank=True, default='')
    posted_by_fullname = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        db_table = 'wip_accrual'
        managed = False

    def __str__(self):
        return self.job


class TurnoverData(models.Model):
    debtor = models.CharField(max_length=100)
    debtor_name = models.CharField(max_length=255)
    value = models.DecimalField(max_digits=15, decimal_places=2)
    date = models.DateField()
    date_fixed = models.CharField(max_length=20)
    branch = models.CharField(max_length=50)

    class Meta:
        db_table = 'turnover_data'
        managed = False

    def __str__(self):
        return f"{self.debtor} - {self.branch}"


class EmailSendLog(models.Model):
    """Records every touchpoint email dispatch for auditing and delivery tracking."""
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('bounced', 'Bounced'),
        ('complained', 'Complained'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
        ('dry_run', 'Dry Run'),
    ]
    PROVIDER_CHOICES = [
        ('ses', 'AWS SES'),
        ('graph', 'Microsoft Graph'),
        ('dry_run', 'Dry Run'),
    ]

    contact = models.ForeignKey('USEUContact', null=True, blank=True, on_delete=models.SET_NULL, related_name='email_logs')
    to_address = models.EmailField()
    from_address = models.EmailField(blank=True, default='')
    touchpoint_number = models.IntegerField(null=True, blank=True)
    subject = models.CharField(max_length=998, blank=True, default='')
    provider = models.CharField(max_length=16, choices=PROVIDER_CHOICES, default='ses')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='sent')
    message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    error_message = models.TextField(blank=True, default='')
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    status_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'email_send_log'
        ordering = ['-sent_at']
        indexes = [models.Index(fields=['to_address', 'sent_at'])]

    def __str__(self):
        return f"{self.to_address} TP{self.touchpoint_number} {self.status}"


# ── Documentation: Company → System → Documents ─────────────────────────────────
class DocCompany(models.Model):
    name = models.CharField(max_length=200, unique=True)
    # Branding + profile
    logo = models.TextField(blank=True, default='')          # base64 data URL
    brand_color = models.CharField(max_length=9, blank=True, default='')  # hex e.g. #2563EB
    industry = models.CharField(max_length=120, blank=True, default='')
    website = models.CharField(max_length=200, blank=True, default='')
    contact_name = models.CharField(max_length=120, blank=True, default='')
    contact_email = models.CharField(max_length=200, blank=True, default='')
    contact_phone = models.CharField(max_length=60, blank=True, default='')
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'doc_company'
        ordering = ['name']

    def __str__(self):
        return self.name


class DocSystem(models.Model):
    company = models.ForeignKey(DocCompany, on_delete=models.CASCADE, related_name='systems')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'doc_system'
        ordering = ['name']
        unique_together = ('company', 'name')

    def __str__(self):
        return f'{self.company.name} / {self.name}'


class DocFolder(models.Model):
    system = models.ForeignKey(DocSystem, on_delete=models.CASCADE, related_name='folders')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'doc_folder'
        ordering = ['name']

    def __str__(self):
        return self.name


def _doc_upload_path(instance, filename):
    return f'documentation/{instance.system.company_id}/{instance.system_id}/{filename}'


class DocDocument(models.Model):
    system = models.ForeignKey(DocSystem, on_delete=models.CASCADE, related_name='documents')
    folder = models.ForeignKey(DocFolder, null=True, blank=True, on_delete=models.CASCADE, related_name='files')
    name = models.CharField(max_length=300)
    file = models.FileField(upload_to=_doc_upload_path)
    size = models.BigIntegerField(default=0)
    content_type = models.CharField(max_length=150, blank=True, default='')
    uploaded_by = models.CharField(max_length=150, blank=True, default='')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'doc_document'
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.name


class ServerRecord(models.Model):
    """A server the user can fully edit from the UI (seeded from the static inventory)."""
    name = models.CharField(max_length=200)
    company = models.CharField(max_length=120, blank=True, default='')
    group = models.CharField(max_length=120, blank=True, default='')
    ip = models.CharField(max_length=100, blank=True, default='')
    host = models.CharField(max_length=200, blank=True, default='')   # host:port used for the status check
    port = models.IntegerField(null=True, blank=True)
    hostname = models.CharField(max_length=200, blank=True, default='')
    os = models.CharField(max_length=200, blank=True, default='')
    provider = models.CharField(max_length=200, blank=True, default='')
    cpu = models.CharField(max_length=200, blank=True, default='')
    ram = models.CharField(max_length=200, blank=True, default='')
    disk = models.CharField(max_length=300, blank=True, default='')
    access = models.CharField(max_length=400, blank=True, default='')
    netbird_ip = models.CharField(max_length=100, blank=True, default='')
    lan_ip = models.CharField(max_length=100, blank=True, default='')
    netbird_url = models.CharField(max_length=300, blank=True, default='')
    ssh_user = models.CharField(max_length=100, blank=True, default='')
    ssh_ip = models.CharField(max_length=100, blank=True, default='')
    ssh_key = models.CharField(max_length=200, blank=True, default='')
    password = models.CharField(max_length=300, blank=True, default='')
    scanned_at = models.DateTimeField(null=True, blank=True)
    runtimes = models.TextField(blank=True, default='')     # newline-separated
    services = models.TextField(blank=True, default='')
    databases = models.TextField(blank=True, default='')
    domains = models.TextField(blank=True, default='')
    notes = models.TextField(blank=True, default='')
    order = models.IntegerField(default=0)

    class Meta:
        db_table = 'server_record'
        ordering = ['order', 'id']

    def __str__(self):
        return self.name


# ── Domains ────────────────────────────────────────────────────────────────────
class Domain(models.Model):
    """A domain name the business owns, with registrar/DNS/SSL renewal tracking.

    ServerRecord.domains is a free-text field kept for the existing server
    detail view; this is the structured record that drives the Domains module
    (expiry countdowns, ownership, which server it points at).
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('parked', 'Parked'),
        ('redirect', 'Redirect'),
        ('transferring', 'Transferring'),
        ('expired', 'Expired'),
    ]
    ENV_CHOICES = [
        ('production', 'Production'),
        ('staging', 'Staging'),
        ('internal', 'Internal'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=253, unique=True)          # e.g. moc-pty.com
    company = models.CharField(max_length=120, blank=True, default='')
    environment = models.CharField(max_length=20, choices=ENV_CHOICES, default='production')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    registrar = models.CharField(max_length=200, blank=True, default='')
    dns_provider = models.CharField(max_length=200, blank=True, default='')
    nameservers = models.TextField(blank=True, default='')        # newline-separated
    primary_url = models.CharField(max_length=400, blank=True, default='')

    # Which server this domain resolves to (optional).
    server = models.ForeignKey(
        ServerRecord, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='domain_records',
    )

    registered_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    ssl_expires_on = models.DateField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)

    notes = models.TextField(blank=True, default='')
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'domain_record'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def days_until(self, field='expires_on'):
        """Days until the given date field, or None when it isn't set."""
        from datetime import date
        value = getattr(self, field, None)
        if not value:
            return None
        return (value - date.today()).days


# ── Repositories ───────────────────────────────────────────────────────────────
class Repository(models.Model):
    """A code repository, tracked so the platform can show its recent history.

    History is read live from `local_path` with git (no credentials needed and
    nothing is cached), so a repo with no local checkout still records where it
    lives but returns an empty history.
    """
    PROVIDER_CHOICES = [
        ('github', 'GitHub'),
        ('gitlab', 'GitLab'),
        ('bitbucket', 'Bitbucket'),
        ('azure', 'Azure DevOps'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=200)
    company = models.CharField(max_length=120, blank=True, default='')
    description = models.TextField(blank=True, default='')

    local_path = models.CharField(max_length=500, blank=True, default='')
    remote_url = models.CharField(max_length=500, blank=True, default='')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='github')
    default_branch = models.CharField(max_length=100, blank=True, default='')

    server = models.ForeignKey(
        ServerRecord, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='repositories',
    )

    notes = models.TextField(blank=True, default='')
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'repository_record'
        ordering = ['order', 'name']
        verbose_name_plural = 'repositories'

    def __str__(self):
        return self.name


class RepoDoc(models.Model):
    """A page of documentation, written and kept here.

    Documentation lives in this database rather than in the repository it
    describes. The repository is somebody else's to push to - often a client's
    - and requiring a commit to fix a typo means the typo stays. Writing it
    here also means a project with no repository access at all still gets
    documented.

    Where a repository does carry README/docs, those are still read and shown;
    a page written here with the same `path` is treated as the newer version
    and wins, so the platform can hold corrections to documentation it does not
    own.
    """
    repository = models.ForeignKey(
        Repository, on_delete=models.CASCADE, related_name='docs')
    path = models.CharField(
        max_length=200,
        help_text="Identifier within the repo, e.g. 'docs/02-the-data-model.md'")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default='', help_text="Markdown")
    order = models.IntegerField(default=0)

    updated_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='repo_docs_edited')
    # Kept as text so the page still names its author after the account goes.
    updated_by_name = models.CharField(max_length=150, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'repository_doc'
        ordering = ['order', 'path']
        unique_together = [('repository', 'path')]

    def __str__(self):
        return f'{self.repository.name}: {self.title}'


class Activity(models.Model):
    """One thing somebody did, in a sentence: "Ethan added task 'K9 Report'".

    A shared record of what happened on the platform, readable by people in the
    activity feed and by an agent through the API gateway. The point is that
    both see the same events: an agent asked "what did Ethan do today" answers
    from this table rather than from guesswork, and a person can check the same
    list and see the agent's own actions in it.

    ## Why the text is stored, not rebuilt

    `actor_name` and `object_label` are plain text copied at the time. The task
    they refer to may be renamed or deleted tomorrow, and the account may be
    removed - but "Ethan deleted task 'K9 Report'" has to keep saying that. A
    feed that rewrites its own history as rows change is not a record of
    anything.

    `object_id` is still kept, so an entry can link through when the thing does
    still exist.
    """
    VERBS = [
        ('created', 'created'),
        ('updated', 'updated'),
        ('completed', 'completed'),
        ('reopened', 'reopened'),
        ('deleted', 'deleted'),
        ('sent', 'sent'),
        ('imported', 'imported'),
    ]
    SOURCES = [
        ('web', 'In the platform'),
        ('api', 'Through the API'),
        ('system', 'Automatic'),
    ]

    actor = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='activity')
    actor_name = models.CharField(max_length=150, blank=True, default='')

    verb = models.CharField(max_length=20, choices=VERBS)
    object_type = models.CharField(
        max_length=40, help_text="task, repository, document, list, …")
    object_id = models.IntegerField(null=True, blank=True)
    object_label = models.CharField(max_length=300, blank=True, default='')

    # Free context: "moved to Done", "in project APS System".
    detail = models.CharField(max_length=300, blank=True, default='')
    project = models.CharField(max_length=200, blank=True, default='')

    source = models.CharField(max_length=10, choices=SOURCES, default='web')
    # Which API token acted, when one did - so an agent's work is attributable
    # to the agent and not just to the user the token borrows.
    via = models.CharField(max_length=120, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'activity_entry'
        ordering = ['-created_at']
        verbose_name_plural = 'activity'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['actor', '-created_at']),
            models.Index(fields=['object_type', 'object_id']),
        ]

    def __str__(self):
        return self.sentence()

    def sentence(self):
        """The entry as a line of English, which is how it is always read."""
        who = self.actor_name or 'Someone'
        what = f'{self.object_type} "{self.object_label}"' if self.object_label \
            else self.object_type
        line = f'{who} {self.verb} {what}'
        if self.detail:
            line += f' — {self.detail}'
        return line


class ApiToken(models.Model):
    """A bearer token letting an external agent act as one user over the API.

    The token is only ever shown once, at creation: what is stored is a SHA-256
    hash, so a database leak does not hand over working credentials. `prefix`
    is the first 8 characters kept in clear text purely so a token can be
    identified in a list without being reversible.
    """
    name = models.CharField(max_length=120)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_tokens')
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    prefix = models.CharField(max_length=12)
    scopes = models.CharField(
        max_length=200, default='tasks',
        help_text='Comma-separated module keys this token may reach.',
    )
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'api_token'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.prefix}…)'

    @staticmethod
    def hash_token(raw):
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @classmethod
    def issue(cls, user, name, scopes='tasks'):
        """Create a token and return (instance, raw_token). The raw is not stored."""
        raw = 'mocp_' + secrets.token_urlsafe(32)
        rec = cls.objects.create(
            name=name, user=user, token_hash=cls.hash_token(raw),
            prefix=raw[:12], scopes=scopes,
        )
        return rec, raw

    def allows(self, scope):
        parts = [s.strip() for s in (self.scopes or '').split(',') if s.strip()]
        return '*' in parts or scope in parts


class ClientRequest(models.Model):
    """A set of questions sent to a client, and the answers they send back.

    The client answers over a tokenised public link - no login - so `token`
    must stay unguessable; it is the only thing protecting the form.
    """
    KIND_CHOICES = [
        ('software', 'Software'),
        ('website', 'Website'),
        ('reports', 'Reports'),
        ('project', 'Project'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('answered', 'Answered'),
    ]

    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='project')
    client_name = models.CharField(max_length=200)
    client_email = models.EmailField()
    intro = models.TextField(
        blank=True, default='',
        help_text='Short note shown above the questions.',
    )
    # A plain list of question strings, in the order they are asked.
    questions = models.JSONField(default=list)
    # {question_text: answer_text} as submitted by the client.
    answers = models.JSONField(default=dict, blank=True)

    token = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notify_email = models.EmailField(
        blank=True, default='',
        help_text='Where the completed answers are sent. Defaults to the creator.',
    )
    # Everyone else who should receive the reply. Kept as a list so recipients
    # can be added later without touching the primary address.
    cc_emails = models.JSONField(default=list, blank=True)
    # Free-text label used when kind == 'other', so the client still sees a
    # meaningful subject instead of the word "Other".
    kind_other = models.CharField(max_length=80, blank=True, default='')

    created_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='client_requests',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'client_request'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} → {self.client_name}'

    @staticmethod
    def new_token():
        return secrets.token_urlsafe(24)

    @property
    def answered_count(self):
        return sum(1 for q in self.questions if (self.answers or {}).get(q, '').strip())

    @property
    def kind_label(self):
        """What to call this to the client - the custom label wins for 'other'."""
        if self.kind == 'other' and self.kind_other.strip():
            return self.kind_other.strip()
        return self.get_kind_display()

    @property
    def all_recipients(self):
        """Primary address first, then extras, de-duplicated case-insensitively."""
        out, seen = [], set()
        for addr in [self.notify_email, *(self.cc_emails or [])]:
            addr = (addr or '').strip()
            if addr and addr.lower() not in seen:
                seen.add(addr.lower())
                out.append(addr)
        return out


class Workspace(models.Model):
    """The level above projects: Workspace → Project → List → Task → Subtask.

    Deleting a workspace never deletes work - its projects fall back to the
    default workspace, because `project_name` on the task is what actually
    holds a task in a project.
    """
    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=20, blank=True, default='')
    # An emoji or short glyph shown in the rail, and optionally a logo image.
    # Two separate things on purpose: an icon needs no hosting, a logo does.
    icon = models.CharField(max_length=8, blank=True, default='')
    logo_url = models.URLField(max_length=500, blank=True, default='')
    order = models.IntegerField(default=0)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workspace'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @classmethod
    def default(cls):
        ws = cls.objects.filter(is_default=True).first()
        if ws is None:
            ws, _ = cls.objects.get_or_create(
                name='Project Tracker', defaults={'is_default': True, 'order': 0})
            if not ws.is_default:
                ws.is_default = True
                ws.save(update_fields=['is_default'])
        return ws


class ProjectMeta(models.Model):
    """A project: who it is for, where it stands, and who is on it.

    This used to hold only decoration - a colour and an icon - because a
    project was nothing more than the `project_name` string on its tasks. That
    left nothing to report: no client to send a report to, no status to report,
    no dates to measure against. The name is still the join key, so no existing
    task or list had to change.
    """
    # The states carried over from the E-Click tracker. The qualified ones
    # matter: "completed, review pending" and "completed, addressing a data
    # discrepancy" are the difference between work being done and work being
    # accepted, and collapsing them to "completed" is how a project looks
    # finished on a report while somebody is still arguing about the numbers.
    STATUS_CHOICES = [
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('in_progress_guidance', 'In Progress (Guidance Required)'),
        ('completed_review_pending', 'Completed (Review Pending)'),
        ('completed_discrepancy', 'Completed (Data Discrepancy Addressing)'),
        ('completed', 'Completed'),
        ('on_hold', 'On Hold'),
        ('cancelled', 'Cancelled'),
    ]
    PRIORITY_CHOICES = [
        ('urgent', 'Urgent'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]

    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=20, blank=True, default='')
    # An emoji or short glyph shown in the rail, and optionally a logo image.
    # Two separate things on purpose: an icon needs no hosting, a logo does.
    icon = models.CharField(max_length=8, blank=True, default='')
    logo_url = models.URLField(max_length=500, blank=True, default='')

    # Who it is for. A project without a client cannot be reported on to
    # anyone, which is why every report in the reference app starts here.
    client = models.CharField(max_length=200, blank=True, default='')
    client_email = models.EmailField(blank=True, default='')
    client_contact = models.CharField(max_length=200, blank=True, default='')

    status = models.CharField(max_length=32, choices=STATUS_CHOICES,
                              default='planned')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES,
                                default='medium')
    description = models.TextField(blank=True, default='')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    # What was quoted, so a report can put actual hours against something.
    quoted_hours = models.DecimalField(max_digits=8, decimal_places=2,
                                       null=True, blank=True)
    # The template asks for the sprint against each client, so it lives on the
    # project rather than being inferred from dates.
    sprint = models.CharField(max_length=80, blank=True, default='')
    # Operational rather than delivery work. The tracker holds a "Weekly
    # Reports" project of 401 rows that is five automated report syncs
    # repeated daily - real work, but not client delivery, and counting it
    # made the management report claim 405 open tasks and 404 overdue.
    # Marked projects are excluded from delivery reporting and from the Gantt.
    is_automated = models.BooleanField(
        default=False,
        help_text='Automated or operational work, not client delivery')
    assigned_users = models.ManyToManyField(
        User, blank=True, related_name='assigned_projects')
    workspace = models.ForeignKey(
        Workspace, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='projects',
    )
    order = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'project_meta'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class ProjectList(models.Model):
    """A named list, either inside a project or directly in a workspace.

    Lists are otherwise just the `list_name` label on tasks, which means an
    empty list cannot exist. Declaring it here lets one be created up front and
    filled later, instead of forcing a throwaway first task.

    `project_name` is blank for a list that hangs straight off a workspace -
    not every list belongs to a project, the same way it works in ClickUp.
    """
    project_name = models.CharField(max_length=100, blank=True, default='')
    workspace = models.ForeignKey(
        Workspace, null=True, blank=True,
        on_delete=models.CASCADE, related_name='lists',
    )
    name = models.CharField(max_length=100)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'project_list'
        ordering = ['order', 'name']
        unique_together = [('project_name', 'workspace', 'name')]

    def __str__(self):
        return f'{self.project_name or (self.workspace.name if self.workspace else "-")} / {self.name}'


class WorkspaceMember(models.Model):
    """Who may see a workspace, and what they may do in it.

    Access is granted at the workspace level rather than per project: a project
    is just a label on its tasks, so there is no durable row to hang a grant on.
    Everything inside a workspace follows the workspace grant.
    """
    ROLE_CHOICES = [
        ('viewer', 'Viewer'),          # read only
        ('member', 'Member'),          # create and edit tasks
        ('manager', 'Manager'),        # plus manage projects, lists and members
    ]

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='workspace_memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')

    added_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='workspace_grants_made')
    added_at = models.DateTimeField(auto_now_add=True)
    # When the "you have been added" email actually went out. Null means it has
    # not been sent, so it can be retried without guessing.
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'workspace_member'
        ordering = ['workspace__name', 'user__username']
        unique_together = [('workspace', 'user')]

    def __str__(self):
        return f'{self.user.username} @ {self.workspace.name} ({self.role})'

    def can_edit(self):
        return self.role in ('member', 'manager')

    def can_manage(self):
        return self.role == 'manager'


class HandbookArticle(models.Model):
    """A written page in the handbook - a rule, a policy, a how-to.

    Separate from DocDocument, which is a file upload. Onboarding rules need to
    be written and edited in place, not attached as a PDF nobody opens.
    """
    CATEGORY_CHOICES = [
        ('getting_started', 'Getting started'),
        ('access', 'Access & accounts'),
        ('rules', 'Rules & expectations'),
        ('how_to', 'How-to guides'),
        ('systems', 'Systems & architecture'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=200)
    category = models.CharField(
        max_length=32, choices=CATEGORY_CHOICES, default='getting_started')
    summary = models.CharField(
        max_length=300, blank=True, default='',
        help_text='One line shown in the list, before anyone opens it.')
    body = models.TextField(
        blank=True, default='',
        help_text='Plain text. Blank lines separate paragraphs; "- " starts a bullet.')

    # Pinned articles lead the list - the things a new starter must read first.
    is_pinned = models.BooleanField(default=False)
    for_new_starters = models.BooleanField(
        default=False,
        help_text='Include in the checklist a new joiner is handed.')
    order = models.IntegerField(default=0)

    updated_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='handbook_edits')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'handbook_article'
        ordering = ['-is_pinned', 'order', 'title']

    def __str__(self):
        return self.title


# Client uploads are kept OUT of MEDIA_ROOT on purpose: nginx serves /media/ as
# a public alias, so anything landing there is readable by URL and served with
# its own content type. These files arrive from unauthenticated strangers, so
# they live somewhere nginx does not map and are only ever handed out by an
# authenticated Django view, as an attachment.
client_upload_storage = FileSystemStorage(
    location=str(settings.BASE_DIR / 'private_media' / 'client-uploads'))


def _client_upload_path(instance, filename):
    """A generated name - the client's filename is never trusted on disk."""
    ext = Path(filename).suffix.lower()[:12]
    return f'{instance.request_id or 0}/{uuid.uuid4().hex}{ext}'


class ClientRequestAttachment(models.Model):
    """Something a client attached to their reply: a file or a reference link.

    Either kind can be pinned to one question or left against the request as a
    whole, which is how people actually answer - "here's the logo" belongs to
    the branding question, "here's our drive" belongs to everything.
    """
    KIND_CHOICES = [
        ('file', 'File'),
        ('link', 'Link'),
    ]

    request = models.ForeignKey(
        ClientRequest, on_delete=models.CASCADE, related_name='attachments')
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)

    # Blank means it belongs to the whole request rather than one question.
    question = models.CharField(max_length=500, blank=True, default='')
    label = models.CharField(max_length=300, blank=True, default='')

    # Links
    url = models.URLField(max_length=1000, blank=True, default='')

    # Files
    file = models.FileField(
        upload_to=_client_upload_path, storage=client_upload_storage,
        blank=True, null=True)
    original_name = models.CharField(max_length=300, blank=True, default='')
    size = models.BigIntegerField(default=0)
    content_type = models.CharField(max_length=150, blank=True, default='')

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'client_request_attachment'
        ordering = ['uploaded_at']

    def __str__(self):
        return f'{self.kind}: {self.label or self.original_name or self.url}'

    @property
    def display_name(self):
        return self.label or self.original_name or self.url or 'Attachment'


class ClientSite(models.Model):
    """A generated website for a client.

    The page is data, not markup: a site is a palette, a font pair and an
    ordered list of blocks. Rendering happens on publish, so a block can be
    reordered or reworded without anyone touching HTML.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]
    # Each palette is a full set, so a site cannot end up with a colour that
    # clashes with its own text.
    PALETTE_CHOICES = [
        ('slate', 'Slate — professional, cool grey'),
        ('ocean', 'Ocean — blue, corporate'),
        ('forest', 'Forest — green, calm'),
        ('sunset', 'Sunset — warm orange'),
        ('plum', 'Plum — purple, creative'),
        ('mono', 'Mono — black and white'),
    ]
    FONT_CHOICES = [
        ('modern', 'Modern — Inter'),
        ('classic', 'Classic — Playfair + Source Sans'),
        ('technical', 'Technical — IBM Plex'),
        ('friendly', 'Friendly — Poppins + Karla'),
    ]
    # The page shape. Listed here rather than imported from site_builder so
    # loading the models never depends on the generator being importable.
    TEMPLATE_CHOICES = [
        ('corporate', 'Corporate — consultancy, B2B, professional services'),
        ('service', 'Trades & services — local, on-site, quote-driven'),
        ('product', 'Software & product — SaaS, apps, platforms'),
        ('studio', 'Studio & creative — design, media, portfolio'),
        ('shop', 'Retail & shop — products, ranges, opening hours'),
        ('onepager', 'One-pager — a clean single page, nothing spare'),
    ]

    # Where it came from, when it was generated from a reply.
    request = models.ForeignKey(
        ClientRequest, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='sites')

    client_name = models.CharField(max_length=200)
    site_name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    tagline = models.CharField(max_length=300, blank=True, default='')
    logo_url = models.URLField(max_length=500, blank=True, default='')

    palette = models.CharField(max_length=20, choices=PALETTE_CHOICES, default='slate')
    font = models.CharField(max_length=20, choices=FONT_CHOICES, default='modern')
    template = models.CharField(max_length=20, choices=TEMPLATE_CHOICES,
                                default='corporate')
    # Which content pack was used, so a reviewer can see what the generator
    # read the business as before judging the copy.
    industry = models.CharField(max_length=40, blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    # Filled on publish so the UI can show a real link and the host it is on.
    published_url = models.URLField(max_length=500, blank=True, default='')
    published_ip = models.CharField(max_length=64, blank=True, default='')
    published_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='client_sites')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'client_site'
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.site_name} ({self.slug})'


class SiteBlock(models.Model):
    """One section of a page: a heading and a hero, a list of services, a form.

    `content` is a JSON bag whose shape depends on `kind`. The block library in
    site_builder.py owns those shapes - the model deliberately does not, so a
    new block type needs no migration.
    """
    KIND_CHOICES = [
        ('hero', 'Hero'),
        ('about', 'About'),
        ('services', 'Services'),
        ('features', 'Why us'),
        ('steps', 'How it works'),
        ('stats', 'Numbers'),
        ('logos', 'Trust strip'),
        ('gallery', 'Gallery'),
        ('testimonial', 'Testimonial'),
        ('pricing', 'Pricing'),
        ('faq', 'FAQ'),
        ('cta', 'Call to action'),
        ('contact', 'Contact'),
        ('text', 'Text'),
    ]

    site = models.ForeignKey(ClientSite, on_delete=models.CASCADE, related_name='blocks')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    order = models.IntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    content = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'site_block'
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.site.slug} / {self.kind} #{self.order}'

class AwaReportRun(models.Model):
    """One execution of one AWA data-services report.

    The reports themselves stay where they are - fifteen standalone scripts on
    the same server, pulling CargoWise views into Excel and uploading them to
    SharePoint. What moves onto the platform is the orchestration and the
    visibility: which ran, when each last succeeded, how many rows it pulled
    and, when it failed, what went wrong in a sentence someone can act on.

    That replaces a JSON file on disk that only the script could read, so the
    state is queryable, has history, and can be shown on a page.
    """
    OUTCOMES = [
        ('ok', 'Updated'),
        ('failed', 'Failed'),
        ('skipped', 'Not scheduled today'),
    ]

    # The script filename, which is the stable identity across renames of the
    # friendly label.
    script = models.CharField(max_length=100, db_index=True)
    name = models.CharField(max_length=200)
    outcome = models.CharField(max_length=12, choices=OUTCOMES)
    # Rows pulled, read off the script's own output. Null when it failed before
    # it got that far, or when the script does not report a count.
    rows = models.IntegerField(null=True, blank=True)
    # One sentence, not a stack trace: this is what appears on the page and in
    # the status email.
    error = models.TextField(blank=True, default='')
    # The tail of stdout/stderr, for when the sentence is not enough.
    log_tail = models.TextField(blank=True, default='')
    duration_seconds = models.FloatField(null=True, blank=True)
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Which batch this belonged to, so a whole run can be shown together.
    batch = models.CharField(max_length=40, blank=True, default='', db_index=True)
    triggered_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='awa_report_runs')

    class Meta:
        db_table = 'awa_report_run'
        ordering = ['-started_at', 'script']
        indexes = [models.Index(fields=['script', '-started_at'])]

    def __str__(self):
        return f'{self.script} {self.outcome} at {self.started_at:%Y-%m-%d %H:%M}'


class AwaReportState(models.Model):
    """The current position of each report: last success, last attempt.

    Derivable from AwaReportRun with a window function, but kept as its own row
    because the page reads it on every load and the run table grows for ever.
    """
    script = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    # Days of the week it runs, as a comma list of 0-6 with Monday as 0. Blank
    # means every day, which is what most of them do.
    run_days = models.CharField(max_length=20, blank=True, default='')
    is_enabled = models.BooleanField(default=True)

    last_outcome = models.CharField(max_length=12, blank=True, default='')
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    # The row count from the last successful pull, which is what you want to
    # see when today's run failed.
    last_rows = models.IntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True, default='')
    consecutive_failures = models.IntegerField(default=0)

    class Meta:
        db_table = 'awa_report_state'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.last_outcome or "no runs"})'

    @property
    def runs_today(self):
        """Whether this report is scheduled for today."""
        if not self.run_days:
            return True
        from django.utils import timezone
        return str(timezone.now().weekday()) in self.run_days.split(',')

class TaskComment(models.Model):
    """A conversation on a task, with replies.

    One model rather than the reference app's two: a ProjectTask is its own
    subtask parent here, so a comment on a subtask is a comment on a task.

    `is_admin_response` is kept because it is what makes the thread readable at
    a glance - it marks the answer to a question rather than another question.
    """
    task = models.ForeignKey('ProjectTask', on_delete=models.CASCADE,
                             related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name='task_comments')
    body = models.TextField()
    is_admin_response = models.BooleanField(default=False)
    parent = models.ForeignKey('self', null=True, blank=True,
                               on_delete=models.CASCADE, related_name='replies')
    # Whether the client is allowed to see this. Internal notes and what we say
    # to the client cannot live in the same thread without this.
    is_internal = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'task_comment'
        ordering = ['created_at']
        indexes = [models.Index(fields=['task', 'created_at'])]

    def __str__(self):
        return f'{self.user} on {self.task_id}: {self.body[:40]}'


class TaskActivity(models.Model):
    """What changed, when, and who changed it.

    Covers both task and project history: a project-level entry has no task.
    Written by the API rather than by signals, so an entry always knows which
    action a person took rather than only which column moved.
    """
    KIND_CHOICES = [
        ('created', 'Created'),
        ('status', 'Status changed'),
        ('priority', 'Priority changed'),
        ('assigned', 'Assignment changed'),
        ('dates', 'Dates changed'),
        ('hours', 'Hours changed'),
        ('development', 'Development type changed'),
        ('comment', 'Comment added'),
        ('edited', 'Edited'),
        ('deleted', 'Deleted'),
        ('report', 'Report sent'),
    ]

    project_name = models.CharField(max_length=100, blank=True, default='',
                                    db_index=True)
    task = models.ForeignKey('ProjectTask', null=True, blank=True,
                             on_delete=models.CASCADE, related_name='activity')
    user = models.ForeignKey(User, null=True, blank=True,
                             on_delete=models.SET_NULL,
                             related_name='task_activity')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    field = models.CharField(max_length=40, blank=True, default='')
    old_value = models.CharField(max_length=300, blank=True, default='')
    new_value = models.CharField(max_length=300, blank=True, default='')
    note = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'task_activity'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['project_name', '-created_at'])]

    def __str__(self):
        return f'{self.kind} {self.field} {self.old_value}->{self.new_value}'

    @property
    def summary(self):
        """One line, for a feed."""
        who = self.user.get_full_name() or self.user.username if self.user else 'Someone'
        if self.kind == 'comment':
            return f'{who} commented'
        if self.kind == 'created':
            return f'{who} created it'
        if self.kind == 'report':
            return f'{who} sent a report{f" to {self.new_value}" if self.new_value else ""}'
        if self.old_value and self.new_value:
            return f'{who} changed {self.field or self.kind} from {self.old_value} to {self.new_value}'
        if self.new_value:
            return f'{who} set {self.field or self.kind} to {self.new_value}'
        return f'{who} {self.get_kind_display().lower()}'


class SentReport(models.Model):
    """Every report that went out: to whom, what was in it, whether it sent.

    The reference app keeps this and it is the part that makes reporting
    auditable rather than anecdotal - "we told them on the 12th" is a claim
    until there is a row with the payload in it.
    """
    REPORT_TYPES = [
        ('general', 'General report'),
        ('project', 'Project report'),
        ('client', 'Client report'),
        ('weekly', 'Weekly report'),
        ('complete', 'Complete report'),
    ]
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('partial', 'Partially sent'),
        ('failed', 'Failed'),
    ]

    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    title = models.CharField(max_length=200, blank=True, default='')
    sent_by = models.ForeignKey(User, null=True, blank=True,
                                on_delete=models.SET_NULL,
                                related_name='sent_reports')
    recipients = models.TextField(blank=True, default='',
                                  help_text='Comma-separated addresses')
    custom_message = models.TextField(blank=True, default='')
    # The figures as they were at the moment of sending. Recomputing them later
    # gives different numbers, so a report you are asked to stand behind has to
    # keep its own copy.
    payload = models.JSONField(default=dict, blank=True)
    project_name = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default='sent')
    error = models.TextField(blank=True, default='')
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'sent_report'
        ordering = ['-sent_at']

    def __str__(self):
        return f'{self.get_report_type_display()} to {self.recipients} on {self.sent_at:%Y-%m-%d}'

    @property
    def recipient_list(self):
        return [a.strip() for a in (self.recipients or '').split(',') if a.strip()]

# ══════════════════════════════════════════════════════════════════════════════
# The weekly management report
# ══════════════════════════════════════════════════════════════════════════════

class ServiceAgreement(models.Model):
    """What we have committed to a client: response times, hosting, renewal.

    Servers and domains are already tracked, but never against a client with a
    promise attached. "SLA, hosting and service requirements" on a management
    report means someone can be asked whether we are meeting them, and that
    needs the commitment written down next to the client it was made to.
    """
    TIERS = [
        ('standard', 'Standard'),
        ('priority', 'Priority'),
        ('critical', 'Critical / 24-7'),
        ('adhoc', 'Ad hoc / time and materials'),
    ]

    client = models.CharField(max_length=200, db_index=True)
    project_name = models.CharField(max_length=100, blank=True, default='')
    tier = models.CharField(max_length=20, choices=TIERS, default='standard')
    # Hours, because that is how these are agreed and how they are breached.
    response_hours = models.IntegerField(null=True, blank=True)
    resolution_hours = models.IntegerField(null=True, blank=True)
    support_window = models.CharField(
        max_length=120, blank=True, default='',
        help_text='e.g. Weekdays 08:00-17:00 SAST')

    hosting_provider = models.CharField(max_length=120, blank=True, default='')
    hosting_notes = models.TextField(blank=True, default='')
    environment_url = models.URLField(max_length=500, blank=True, default='')
    backup_schedule = models.CharField(max_length=120, blank=True, default='')
    renewal_date = models.DateField(null=True, blank=True)
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2,
                                      null=True, blank=True)
    # Section 4 of the template: the financial row per client.
    next_deliverable = models.CharField(max_length=255, blank=True, default='')
    next_invoice_date = models.DateField(null=True, blank=True)
    hosting_capacity = models.CharField(
        max_length=120, blank=True, default='',
        help_text='e.g. 4 vCPU / 8 GB, 62% used')
    is_reconciled = models.BooleanField(
        default=False, help_text='Management only')
    owner = models.ForeignKey(User, null=True, blank=True,
                              on_delete=models.SET_NULL,
                              related_name='service_agreements')
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'service_agreement'
        ordering = ['client', 'project_name']

    def __str__(self):
        return f'{self.client} ({self.get_tier_display()})'

    @property
    def renews_in_days(self):
        if not self.renewal_date:
            return None
        from django.utils import timezone
        return (self.renewal_date - timezone.localdate()).days


class SupportTicket(models.Model):
    """A client raising something that needs attention now.

    Distinct from a task: a task is planned work, a ticket arrived unplanned
    and is measured against an SLA. Keeping them in one table would make both
    the capacity figure and the SLA figure wrong.
    """
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('acknowledged', 'Acknowledged'),
        ('in_progress', 'In Progress'),
        ('waiting_client', 'Waiting on Client'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]
    PRIORITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    SOURCES = [
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('meeting', 'Meeting'),
        ('portal', 'Portal'),
        ('monitoring', 'Monitoring alert'),
        ('other', 'Other'),
    ]

    reference = models.CharField(max_length=40, blank=True, default='',
                                 help_text='Ours, or theirs')
    client = models.CharField(max_length=200, db_index=True)
    project_name = models.CharField(max_length=100, blank=True, default='')
    subject = models.CharField(max_length=255)
    detail = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='open', db_index=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES,
                                default='medium')
    source = models.CharField(max_length=20, choices=SOURCES, default='email')
    owner = models.ForeignKey(User, null=True, blank=True,
                              on_delete=models.SET_NULL,
                              related_name='support_tickets')
    opened_at = models.DateTimeField(db_index=True)
    # Computed from the agreement when one exists, so a breach is visible
    # without recalculating it on every report.
    response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Where the technical record lives, which the brief asks for explicitly.
    devops_url = models.URLField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'support_ticket'
        ordering = ['-opened_at']
        indexes = [models.Index(fields=['status', '-opened_at'])]

    def __str__(self):
        return f'{self.reference or self.pk}: {self.subject[:50]}'

    @property
    def is_open(self):
        return self.status not in ('resolved', 'closed')

    @property
    def response_breached(self):
        from django.utils import timezone
        if not self.response_due_at:
            return False
        end = self.first_response_at or timezone.now()
        return end > self.response_due_at

    @property
    def resolution_breached(self):
        from django.utils import timezone
        if not self.resolution_due_at:
            return False
        end = self.resolved_at or timezone.now()
        return end > self.resolution_due_at

    @property
    def age_days(self):
        from django.utils import timezone
        end = self.resolved_at or timezone.now()
        return (end - self.opened_at).days


class RiskItem(models.Model):
    """A risk, a piece of technical debt, or a dependency we are exposed to.

    One model with a kind rather than three tables: they are reported in the
    same section, reviewed in the same meeting, and the only thing that differs
    is the word used for them.
    """
    KINDS = [
        ('risk', 'Risk'),
        ('technical_debt', 'Technical debt'),
        ('dependency', 'Dependency'),
        ('assumption', 'Assumption'),
    ]
    SEVERITY = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    LIKELIHOOD = [
        ('almost_certain', 'Almost certain'),
        ('likely', 'Likely'),
        ('possible', 'Possible'),
        ('unlikely', 'Unlikely'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('mitigating', 'Being mitigated'),
        ('accepted', 'Accepted'),
        ('closed', 'Closed'),
    ]

    kind = models.CharField(max_length=20, choices=KINDS, default='risk')
    title = models.CharField(max_length=255)
    detail = models.TextField(blank=True, default='')
    project_name = models.CharField(max_length=100, blank=True, default='',
                                    db_index=True)
    client = models.CharField(max_length=200, blank=True, default='')
    severity = models.CharField(max_length=10, choices=SEVERITY, default='medium')
    likelihood = models.CharField(max_length=20, choices=LIKELIHOOD,
                                  default='possible')
    impact = models.TextField(blank=True, default='')
    mitigation = models.TextField(blank=True, default='')
    # The template names this column, and it is not the same as the review
    # date: it is how long the fix is expected to take.
    resolution_time = models.CharField(max_length=80, blank=True, default='')
    owner = models.ForeignKey(User, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name='risks')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='open', db_index=True)
    # When it should next be looked at, which is what stops a risk register
    # becoming a list nobody revisits.
    review_date = models.DateField(null=True, blank=True)
    devops_url = models.URLField(max_length=500, blank=True, default='')
    raised_by = models.ForeignKey(User, null=True, blank=True,
                                  on_delete=models.SET_NULL,
                                  related_name='raised_risks')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'risk_item'
        ordering = ['-severity', '-created_at']

    def __str__(self):
        return f'[{self.get_kind_display()}] {self.title[:50]}'

    @property
    def is_open(self):
        return self.status in ('open', 'mitigating')

    @property
    def review_overdue(self):
        from django.utils import timezone
        return bool(self.review_date and self.review_date < timezone.localdate()
                    and self.is_open)

    @property
    def score(self):
        """A crude ranking so the worst thing appears first.

        Deliberately crude: a five-by-five matrix invites arguing about whether
        something is a three or a four instead of doing something about it.
        """
        sev = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}
        lik = {'almost_certain': 4, 'likely': 3, 'possible': 2, 'unlikely': 1}
        return sev.get(self.severity, 2) * lik.get(self.likelihood, 2)


class WeeklyFocus(models.Model):
    """What a project or person is meant to get done this week.

    The brief asks for "team capacity and weekly priorities". Capacity comes
    from hours on tasks; priorities have to be stated by someone, which is what
    this is - and stating them one week at a time is what makes the next
    report able to ask whether they happened.
    """
    week_start = models.DateField(db_index=True, help_text='The Monday')
    title = models.CharField(max_length=255)
    project_name = models.CharField(max_length=100, blank=True, default='')
    client = models.CharField(max_length=200, blank=True, default='')
    owner = models.ForeignKey(User, null=True, blank=True,
                              on_delete=models.SET_NULL,
                              related_name='weekly_focus')
    order = models.IntegerField(default=0)
    is_done = models.BooleanField(default=False)
    carried_over = models.BooleanField(
        default=False,
        help_text='Was a priority last week and did not get done')
    # "Plan for Next Week" in the template carries a due date and a named
    # responsibility, not just a title.
    due_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'weekly_focus'
        ordering = ['week_start', 'order', 'id']
        indexes = [models.Index(fields=['week_start', 'order'])]

    def __str__(self):
        return f'{self.week_start}: {self.title[:50]}'


class ManagementAction(models.Model):
    """A commitment made in a management review, with someone answerable.

    This is the part of the brief that is not reporting. An action has an
    owner, a due date, a confirmation that the owner has seen it, and a
    close-out - so the next report can say what was agreed, whether it was
    acknowledged, and whether it happened, rather than restating the same
    concern every week.
    """
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('acknowledged', 'Acknowledged'),
        ('in_progress', 'In Progress'),
        ('blocked', 'Blocked'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ]

    title = models.CharField(max_length=255)
    detail = models.TextField(blank=True, default='')
    week_start = models.DateField(db_index=True)
    project_name = models.CharField(max_length=100, blank=True, default='')
    client = models.CharField(max_length=200, blank=True, default='')
    owner = models.ForeignKey(User, null=True, blank=True,
                              on_delete=models.SET_NULL,
                              related_name='management_actions')
    raised_by = models.ForeignKey(User, null=True, blank=True,
                                  on_delete=models.SET_NULL,
                                  related_name='raised_actions')
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='open', db_index=True)

    # Needs a management decision rather than just doing.
    needs_decision = models.BooleanField(default=False)
    decision = models.TextField(blank=True, default='')
    decided_at = models.DateTimeField(null=True, blank=True)

    # The execution loop the brief asks for: the owner is told, the owner
    # confirms, and the item is closed out.
    notified_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # How many times this has appeared on a report without moving. The number
    # that makes an accountability conversation concrete.
    times_reported = models.IntegerField(default=0)

    devops_url = models.URLField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'management_action'
        ordering = ['due_date', '-created_at']
        indexes = [models.Index(fields=['status', 'due_date'])]

    def __str__(self):
        return f'{self.title[:50]} ({self.get_status_display()})'

    @property
    def is_open(self):
        return self.status not in ('done', 'cancelled')

    @property
    def is_overdue(self):
        from django.utils import timezone
        return bool(self.due_date and self.due_date < timezone.localdate()
                    and self.is_open)

    @property
    def awaiting_acknowledgement(self):
        return bool(self.notified_at and not self.acknowledged_at
                    and self.is_open)


class ManagementReport(models.Model):
    """One week's report, kept as it was published.

    Regenerating last week's report today would show this week's numbers, so
    the published figures are stored. Management asked for a reliable weekly
    view; a view that changes after the meeting is not one.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('sent', 'Sent'),
    ]

    week_start = models.DateField(db_index=True, help_text='The Monday')
    title = models.CharField(max_length=200, blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    # What the person compiling it wants management to read first.
    summary = models.TextField(blank=True, default='')
    # The template's oversight line. A judgement, so it can only be entered -
    # but management asked for it every week, so it belongs on the report
    # rather than in someone's head.
    MORALE_CHOICES = [
        ('depleted', 'Depleted'),
        ('inefficient', 'Inefficient'),
        ('cruising', 'Cruising'),
        ('momentum', 'Maintaining Momentum'),
        ('visionary', 'Pro-Active & Visionary Mindset'),
    ]
    staff_morale = models.CharField(max_length=20, choices=MORALE_CHOICES,
                                    blank=True, default='')
    morale_note = models.CharField(max_length=300, blank=True, default='')
    issue_number = models.CharField(max_length=20, blank=True, default='')
    report_version = models.CharField(max_length=10, blank=True, default='V3')
    developed_by = models.CharField(max_length=120, blank=True, default='')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default='draft')
    prepared_by = models.ForeignKey(User, null=True, blank=True,
                                    on_delete=models.SET_NULL,
                                    related_name='management_reports')
    recipients = models.TextField(blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'management_report'
        ordering = ['-week_start']
        unique_together = [('week_start',)]

    def __str__(self):
        return f'Management report for week of {self.week_start}'

class StaffFocus(models.Model):
    """What share of a person's week goes to a client.

    The template's focus matrix: people across the top, clients down the side,
    percentages in the cells, totals both ways. Stored rather than only
    derived, because it is a statement of intent - what someone is *meant* to
    be spending their week on - and the report is more useful when it can show
    that against what the hours actually say.
    """
    week_start = models.DateField(db_index=True)
    person = models.ForeignKey(User, on_delete=models.CASCADE,
                               related_name='staff_focus')
    # A client or an internal bucket such as "Admin & Structure", which the
    # template lists alongside the clients.
    bucket = models.CharField(max_length=200,
                              help_text='Client name, or an internal bucket')
    planned_pct = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    note = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        db_table = 'staff_focus'
        ordering = ['week_start', 'bucket']
        unique_together = [('week_start', 'person', 'bucket')]

    def __str__(self):
        return f'{self.week_start} {self.person}: {self.bucket} {self.planned_pct}%'


class CompanyFocus(models.Model):
    """The company's intended split per client, against what got done.

    Section 3's second table. Split goal is the target share of company effort;
    the done and outstanding counts come from the tracker, so the only thing
    entered here is the goal and the commentary.
    """
    week_start = models.DateField(db_index=True)
    bucket = models.CharField(max_length=200)
    split_goal_pct = models.DecimalField(max_digits=5, decimal_places=1,
                                         default=0)
    support_pct = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    due_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, default='')
    order = models.IntegerField(default=0)

    class Meta:
        db_table = 'company_focus'
        ordering = ['week_start', 'order', 'bucket']
        unique_together = [('week_start', 'bucket')]

    def __str__(self):
        return f'{self.week_start} {self.bucket}: {self.split_goal_pct}%'


class ClientWeekNote(models.Model):
    """The per-client card in section 1: sprint, comments, and the tickets line.

    Most of that card is computed - completed and outstanding per stream come
    from the tasks. What cannot be computed is the commentary and the "last
    report update" date, which is what this holds.
    """
    week_start = models.DateField(db_index=True)
    client = models.CharField(max_length=200)
    sprint = models.CharField(max_length=80, blank=True, default='')
    project_due_date = models.DateField(null=True, blank=True)
    comments = models.TextField(blank=True, default='')
    last_report_update = models.DateField(null=True, blank=True)
    # Section 5: what is planned for this client next week, and who owns it.
    next_week_note = models.TextField(blank=True, default='')
    next_week_due = models.DateField(null=True, blank=True)
    next_week_owner = models.ForeignKey(User, null=True, blank=True,
                                        on_delete=models.SET_NULL,
                                        related_name='client_week_notes')
    order = models.IntegerField(default=0)

    class Meta:
        db_table = 'client_week_note'
        ordering = ['week_start', 'order', 'client']
        unique_together = [('week_start', 'client')]

    def __str__(self):
        return f'{self.week_start} {self.client}'


class PricingImport(models.Model):
    """One load of the pricing workbook, so a reload is traceable and undoable.

    The source is a CargoWise export that somebody downloads and drops in.
    Keeping the import as a row - rather than just replacing the data - means
    the page can say where its figures came from and when, and a bad load can
    be rolled back by deleting one object.
    """
    filename = models.CharField(max_length=400)
    # Size and modified time together are enough to notice the same file being
    # loaded twice, without hashing 22 MB.
    file_size = models.BigIntegerField(default=0)
    file_modified = models.DateTimeField(null=True, blank=True)
    loaded_at = models.DateTimeField(auto_now_add=True)
    loaded_by = models.ForeignKey(User, null=True, blank=True,
                                  on_delete=models.SET_NULL,
                                  related_name='pricing_imports')
    quote_rows = models.IntegerField(default=0)
    turnover_rows = models.IntegerField(default=0)
    skipped_rows = models.IntegerField(default=0)
    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(
        default=True,
        help_text='The load the report reads. Only one is active at a time.')

    class Meta:
        db_table = 'pricing_import'
        ordering = ['-loaded_at']

    def __str__(self):
        return f'{self.filename} ({self.loaded_at:%Y-%m-%d})'

    @property
    def total_rows(self):
        return self.quote_rows + self.turnover_rows


class PricingRow(models.Model):
    """One row of the pricing workbook.

    The workbook is two tables stacked in one sheet, exactly as the analyst
    built it: quote rows from the CargoWise pricing export on top, then the
    turnover analysis rows appended underneath. `block` keeps that distinction
    explicit instead of leaving it to be guessed from which columns are blank -
    the turnover rows only carry client, month, branch and income.

    Columns the workbook holds purely to make pivot tables work are not stored,
    because every one of them is a restatement of a column that is:

        Airfreight / Seafreight   -> transport_mode
        Import / Export / Domestic-> direction
        AU/NZ / ROW               -> au_nz_row
        Not Converted             -> the opposite of converted
        Assigned To Names         -> assigned_to, through the same lookup

    Storing them as well would mean two places to keep in step, and the first
    time they disagreed nobody would know which one the report had used.
    """
    QUOTE = 'quote'
    TURNOVER = 'turnover'
    BLOCK_CHOICES = [(QUOTE, 'Pricing quote'), (TURNOVER, 'Turnover analysis')]

    source = models.ForeignKey(PricingImport, on_delete=models.CASCADE,
                               related_name='rows')
    block = models.CharField(max_length=10, choices=BLOCK_CHOICES,
                             default=QUOTE)
    row_number = models.IntegerField(
        default=0, help_text='Row in the source sheet, for tracing a figure back.')

    # ── Who ──
    client = models.CharField(max_length=60, blank=True, default='')
    client_name = models.CharField(max_length=255, blank=True, default='')
    branch = models.CharField(max_length=40, blank=True, default='')

    # ── When. month_label is the workbook's own "January 2024"; month_start is
    #    the same thing as a date, which is what you can actually sort and
    #    filter on. month_sort is the analyst's running month index, kept
    #    because their pivots are built on it. ──
    month_label = models.CharField(max_length=30, blank=True, default='')
    month_start = models.DateField(null=True, blank=True)
    year = models.IntegerField(null=True, blank=True)
    quarter = models.CharField(max_length=4, blank=True, default='')
    month_sort = models.IntegerField(null=True, blank=True)

    # ── The quote itself (quote block only) ──
    quote_no = models.BigIntegerField(null=True, blank=True)
    booking_no = models.CharField(max_length=60, blank=True, default='')
    quote_status = models.TextField(blank=True, default='')
    created_time = models.DateTimeField(null=True, blank=True)
    booked = models.DateTimeField(null=True, blank=True)
    # Booked minus created, in days. The workbook works this out in the query;
    # it is stored because it is the whole point of the report.
    conversion_days = models.FloatField(null=True, blank=True)
    converted = models.BooleanField(default=False)
    missed_opportunity = models.BooleanField(default=False)

    # ── Freight ──
    transport_mode = models.CharField(max_length=20, blank=True, default='')
    mode = models.CharField(max_length=20, blank=True, default='')
    weight = models.FloatField(null=True, blank=True)
    weight_unit = models.CharField(max_length=8, blank=True, default='')
    volume = models.FloatField(null=True, blank=True)
    volume_unit = models.CharField(max_length=8, blank=True, default='')
    chargeable = models.FloatField(null=True, blank=True)

    # ── Lanes ──
    origin = models.CharField(max_length=20, blank=True, default='')
    destination = models.CharField(max_length=20, blank=True, default='')
    origin_country = models.CharField(max_length=8, blank=True, default='')
    destination_country = models.CharField(max_length=8, blank=True, default='')
    incoterm = models.CharField(max_length=20, blank=True, default='')
    direction = models.CharField(max_length=12, blank=True, default='',
                                 help_text='Import, Export or Domestic.')
    au_nz_row = models.CharField(max_length=8, blank=True, default='',
                                 help_text='AU/NZ or ROW, by destination.')

    # ── People ──
    assigned_to = models.CharField(max_length=20, blank=True, default='')
    assigned_to_name = models.CharField(max_length=120, blank=True, default='')
    created_by = models.CharField(max_length=120, blank=True, default='')

    # ── Money (turnover block only) ──
    total_income = models.DecimalField(max_digits=14, decimal_places=2,
                                       null=True, blank=True)

    # ── The analyst's duplicate detection, carried over as-is ──
    duplicate_flag = models.CharField(max_length=12, blank=True, default='',
                                      help_text='Unique or Duplicate.')
    duplicate_pickup = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'pricing_row'
        indexes = [
            # The four ways the page actually slices it.
            models.Index(fields=['source', 'block']),
            models.Index(fields=['source', 'month_start']),
            models.Index(fields=['source', 'branch']),
            models.Index(fields=['source', 'client']),
        ]

    def __str__(self):
        return f'{self.block} {self.client} {self.month_label}'
