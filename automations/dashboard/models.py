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
    COMPANY_CHOICES = [
        ('magnum_opus', 'Magnum Opus'),
        ('food_safety', 'Food Safety Agency'),
        ('eclick', 'Eclick'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='backlog')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    company = models.CharField(max_length=20, choices=COMPANY_CHOICES, blank=True, default='')
    project_name = models.CharField(max_length=100, blank=True, default='')
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
    # Page-level access flags. Superusers bypass these.
    can_data_analysis = models.BooleanField(default=False)
    can_emailing = models.BooleanField(default=False)
    can_planner = models.BooleanField(default=False)
    can_sync_monitor = models.BooleanField(default=False)
    can_automations = models.BooleanField(default=False)

    class Meta:
        db_table = 'user_profile'

    def __str__(self):
        return self.user.username

    def has_page(self, key):
        """Check if this profile's user can access a page key."""
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
        ('Inactive', 'Inactive'),
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
    moved_to_hubspot_at = models.DateTimeField(null=True, blank=True, db_index=True)
    opted_out_at = models.DateTimeField(null=True, blank=True, db_index=True)

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
