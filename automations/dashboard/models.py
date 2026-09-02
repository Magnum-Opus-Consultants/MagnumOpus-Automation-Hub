from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class ProjectTask(models.Model):
    STATUS_CHOICES = [
        ('backlog', 'Backlog'),
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('review', 'Review'),
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
    company = models.CharField(max_length=20, choices=COMPANY_CHOICES, blank=True, default='')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='subtasks')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

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


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


class USEUContact(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Undeliverable', 'Undeliverable'),
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
