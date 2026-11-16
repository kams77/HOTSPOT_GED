"""Prépare une installation neuve : rôles, super-utilisateur, forfaits, données de démonstration.

    python manage.py bootstrap            # rôles + admin + forfaits de base
    python manage.py bootstrap --demo     # + distributeurs, revendeurs, tickets, comptes de test
Sans danger si on le relance : rien n'est créé deux fois.
"""
import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import roles, services
from core.models import Distributor, Plan, Reseller, SiteSettings, Subscriber
from radius.models import Nas

PLANS = [
    dict(name='Express 1 h', price=500, duration=60, validity=1, quota=500, down=2048, up=1024, shared=1),
    dict(name='Journée', price=1500, duration=1440, validity=1, quota=2048, down=4096, up=2048, shared=1),
    dict(name='Nuit 22h–6h', price=1000, duration=480, validity=1, quota=3072, down=10240, up=5120, shared=1,
         login_time='Al2200-0600'),
    dict(name='Semaine', price=7500, duration=10080, validity=7, quota=10240, down=6144, up=3072, shared=2),
    dict(name='Mois illimité', price=25000, duration=43200, validity=30, quota=0, down=8192, up=4096, shared=3),
    dict(name='Accès gratuit sponsorisé', price=0, duration=30, validity=1, quota=100, down=1024, up=512, shared=1,
         is_free=True),
]


class Command(BaseCommand):
    help = 'Crée les rôles, le super-utilisateur, les forfaits et (option --demo) des données de test.'

    def add_arguments(self, parser):
        parser.add_argument('--demo', action='store_true', help='Ajoute des données de démonstration.')

    @transaction.atomic
    def handle(self, *args, demo=False, **opts):
        s = SiteSettings.get()
        if not s.perms:
            s.perms = [row[:] for row in roles.DEFAULT_MATRIX]
            s.save()
        for name in roles.ROLES:
            Group.objects.get_or_create(name=name)

        User = get_user_model()
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
        if password and not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username, os.environ.get('DJANGO_SUPERUSER_EMAIL', ''), password)
            self.stdout.write(self.style.SUCCESS(f'Super-utilisateur « {username} » créé.'))

        if not Plan.objects.exists():
            for p in PLANS:
                Plan.objects.create(**p)
            self.stdout.write(self.style.SUCCESS(f'{len(PLANS)} forfaits créés.'))
        else:
            for p in Plan.objects.all():
                services.sync_plan(p)

        if demo:
            self.demo(User)
        self.stdout.write(self.style.SUCCESS('Installation prête.'))

    def demo(self, User):
        s = SiteSettings.get()
        if s.operator_wallet == 0:
            s.operator_wallet = 1_000_000
            s.save()
        Nas.objects.get_or_create(nasname='172.30.0.1', defaults=dict(
            shortname='Passerelle Docker (tests radtest)', secret='testing-secret-123', vendor='Autre (RFC 2865)',
            zone='Local'))
        d, _ = Distributor.objects.get_or_create(name='Distribution Kin-Est', defaults=dict(
            zone='Kalamu · Lemba · Limete', phone='+243 81 990 4410', wallet=300_000, share=12))
        r, _ = Reseller.objects.get_or_create(name='Kiosque Victoire', defaults=dict(
            zone='Kalamu', phone='+243 81 234 5678', distributor=d, balance=80_000, commission=10))
        if r.user is None:
            u = User.objects.filter(username='kiosque').first() or User.objects.create_user('kiosque', '', 'kiosque12345')
            u.groups.add(Group.objects.get(name='Revendeur'))
            r.user = u
            r.save()
        for login, role in (('operateur', 'Opérateur réseau'), ('caisse', 'Caissier')):
            if not User.objects.filter(username=login).exists():
                u = User.objects.create_user(login, '', f'{login}12345', is_staff=True)
                u.groups.add(Group.objects.get(name=role))
        express = Plan.objects.filter(name='Express 1 h').first() or Plan.objects.first()
        if not r.vouchers.exists():
            services.generate_batch(express, 20, None, 8, r)
        if not Subscriber.objects.filter(username='test').exists():
            sub = services.create_subscriber(express, Subscriber.Source.MANUAL, 'bootstrap', username='test',
                                             password='test1234', phone='+243 81 000 0001')
            sub.expires_at = timezone.now() + timedelta(days=30)
            sub.save()
        self.stdout.write(self.style.SUCCESS(
            'Démo : comptes console operateur / operateur12345, caisse / caisse12345, kiosque / kiosque12345 ; '
            'client RADIUS test / test1234.'))
