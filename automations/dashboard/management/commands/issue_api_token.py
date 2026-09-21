"""Issue an API token for an external agent.

    manage.py issue_api_token --user Ethan --name "Claude agent"

The raw token is printed once and never stored; only its SHA-256 hash is kept.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from dashboard.models import ApiToken


class Command(BaseCommand):
    help = 'Issue an API token for a user (prints the token once).'

    def add_arguments(self, parser):
        parser.add_argument('--user', required=True, help='Django username the token acts as.')
        parser.add_argument('--name', required=True, help='Label, e.g. the agent name.')
        parser.add_argument('--scopes', default='tasks',
                            help='Comma-separated scopes, or "*" for all. '
                                 'Known: tasks, activity. Default: tasks')
        parser.add_argument('--list', action='store_true', help='List existing tokens instead.')
        parser.add_argument('--revoke', help='Revoke by prefix instead of issuing.')

    def handle(self, *args, **opts):
        if opts.get('list'):
            for t in ApiToken.objects.select_related('user'):
                state = 'active' if t.is_active else 'REVOKED'
                used = t.last_used_at.strftime('%Y-%m-%d %H:%M') if t.last_used_at else 'never'
                self.stdout.write(f'  {t.prefix}…  {t.name:<28} {t.user.username:<12} '
                                  f'{state:<8} scopes={t.scopes:<10} last_used={used}')
            return

        if opts.get('revoke'):
            n = ApiToken.objects.filter(prefix__startswith=opts['revoke']).update(is_active=False)
            self.stdout.write(self.style.SUCCESS(f'Revoked {n} token(s).'))
            return

        user = User.objects.filter(username=opts['user']).first()
        if user is None:
            raise CommandError(f'No such user: {opts["user"]}')

        rec, raw = ApiToken.issue(user, opts['name'], opts['scopes'])
        self.stdout.write(self.style.SUCCESS('API token issued - copy it now, it is not recoverable:'))
        self.stdout.write('')
        self.stdout.write(f'    {raw}')
        self.stdout.write('')
        self.stdout.write(f'  user   : {user.username}')
        self.stdout.write(f'  name   : {rec.name}')
        self.stdout.write(f'  scopes : {rec.scopes}')
