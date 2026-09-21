from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0036_touchpointtemplate_signature_image_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='useucontact',
            name='moved_to_hubspot_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
