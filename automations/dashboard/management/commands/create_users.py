"""
Create user accounts for the platform.

Usage:
    python manage.py create_users
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


USERS = [
    {
        'username': 'waldo',
        'email': 'waldogaybba@moc-pty.com',
        'first_name': 'Waldo',
        'last_name': 'Gaybba',
        'password': 'Moc@2026!',
    },
    {
        'username': 'louis',
        'email': 'louislewies@gmail.com',
        'first_name': 'Louis',
        'last_name': 'Lewies',
        'password': 'Moc@2026!',
    },
]


class Command(BaseCommand):
    help = 'Create user accounts for Waldo and Louis'

    def handle(self, *args, **options):
        for u in USERS:
            user, created = User.objects.get_or_create(
                username=u['username'],
                defaults={
                    'email': u['email'],
                    'first_name': u['first_name'],
                    'last_name': u['last_name'],
                    'is_staff': True,
                },
            )
            if created:
                user.set_password(u['password'])
                user.save()
                self.stdout.write(self.style.SUCCESS(
                    f'Created user: {u["username"]} ({u["email"]}) — password: {u["password"]}'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'User already exists: {u["username"]} ({u["email"]})'
                ))
