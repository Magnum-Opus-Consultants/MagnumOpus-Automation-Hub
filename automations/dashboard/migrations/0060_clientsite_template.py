"""A site records the template it was built as, and what the generator read
the business as.

Both are plain columns with defaults, so existing rows need no data migration:
every site created before templates existed was built on the corporate layout,
which is what the default says.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0059_clientsite_siteblock'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientsite',
            name='template',
            field=models.CharField(
                choices=[
                    ('corporate', 'Corporate — consultancy, B2B, professional services'),
                    ('service', 'Trades & services — local, on-site, quote-driven'),
                    ('product', 'Software & product — SaaS, apps, platforms'),
                    ('studio', 'Studio & creative — design, media, portfolio'),
                    ('shop', 'Retail & shop — products, ranges, opening hours'),
                    ('onepager', 'One-pager — a clean single page, nothing spare'),
                ],
                default='corporate', max_length=20),
        ),
        migrations.AddField(
            model_name='clientsite',
            name='industry',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        # The block library grew: how it works, FAQ and the trust strip. `kind`
        # has no database constraint, so this only keeps the model's choices
        # honest for the admin and for validation.
        migrations.AlterField(
            model_name='siteblock',
            name='kind',
            field=models.CharField(
                choices=[
                    ('hero', 'Hero'), ('about', 'About'), ('services', 'Services'),
                    ('features', 'Why us'), ('steps', 'How it works'),
                    ('stats', 'Numbers'), ('logos', 'Trust strip'),
                    ('gallery', 'Gallery'), ('testimonial', 'Testimonial'),
                    ('pricing', 'Pricing'), ('faq', 'FAQ'), ('cta', 'Call to action'),
                    ('contact', 'Contact'), ('text', 'Text'),
                ],
                max_length=20),
        ),
    ]
