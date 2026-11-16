"""Tests : python manage.py test (fonctionne aussi avec SQLite, sans Docker)."""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from radius.models import RadAcct, RadCheck, RadGroupCheck, RadGroupReply, RadUserGroup

from . import roles, services
from .models import Payment, Plan, Reseller, Subscriber, Voucher


class RadiusSyncTests(TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(name='Jour', price=1500, duration=60, validity=1, quota=500, shared=2)

    def test_plan_creates_group_attributes(self):
        g = self.plan.group
        self.assertTrue(RadGroupCheck.objects.filter(groupname=g, attribute='Simultaneous-Use', value='2').exists())
        self.assertTrue(RadGroupReply.objects.filter(groupname=g, attribute='WISPr-Bandwidth-Max-Down').exists())

    def test_subscriber_sync_and_suspend(self):
        sub = services.create_subscriber(self.plan, Subscriber.Source.MANUAL, 'test', username='alice', password='secret12')
        self.assertTrue(RadCheck.objects.filter(username='alice', attribute='Cleartext-Password', value='secret12').exists())
        self.assertTrue(RadCheck.objects.filter(username='alice', attribute='Max-All-Session', value='3600').exists())
        self.assertTrue(RadUserGroup.objects.filter(username='alice', groupname=self.plan.group).exists())
        services.set_status(sub, Subscriber.Status.SUSPENDED, 'test')
        self.assertTrue(RadCheck.objects.filter(username='alice', attribute='Auth-Type', value='Reject').exists())
        sub.delete()
        self.assertFalse(RadCheck.objects.filter(username='alice').exists())

    def test_renew_keeps_remaining_time(self):
        sub = services.create_subscriber(self.plan, Subscriber.Source.MANUAL, 'test', username='bob')
        RadAcct.objects.create(acctsessionid='s1', acctuniqueid='u1', username='bob', nasipaddress='10.0.0.1',
                               acctsessiontime=600, acctinputoctets=1000, acctoutputoctets=2000,
                               acctstarttime=timezone.now(), acctstoptime=timezone.now())
        services.renew_subscriber(sub, self.plan, 'test', pay='Espèces')
        sub.refresh_from_db()
        # 600 s utilisées + 3000 s restantes reportées → offset 3600, puis +3600 du nouveau forfait
        self.assertEqual(sub.time_offset, 3600)
        self.assertTrue(RadCheck.objects.filter(username='bob', attribute='Max-All-Session', value='7200').exists())
        self.assertEqual(Payment.objects.filter(subscriber=sub, status='success').count(), 1)


class VoucherTests(TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(name='Express', price=500, duration=60)
        self.reseller = Reseller.objects.create(name='Kiosque', balance=10_000, commission=10)

    def test_batch_debits_reseller_and_sale_then_redeem(self):
        services.generate_batch(self.plan, 10, None, 8, self.reseller)
        self.reseller.refresh_from_db()
        self.assertEqual(self.reseller.balance, 10_000 - 4_500)
        v = services.sell_voucher(self.reseller, self.plan, '', 'test')
        self.assertEqual(v.status, Voucher.Status.SOLD)
        sub = services.redeem_voucher(v.code[:4] + '-' + v.code[4:].lower())
        self.assertEqual(sub.username, v.code)
        v.refresh_from_db()
        self.assertEqual(v.status, Voucher.Status.USED)
        self.assertEqual(services.redeem_voucher(v.code), sub)  # reconnexion

    def test_insufficient_balance(self):
        with self.assertRaises(services.ServiceError):
            services.generate_batch(self.plan, 100, None, 8, self.reseller)


class PaymentTests(TestCase):
    def test_confirm_creates_then_renews(self):
        plan = Plan.objects.create(name='Jour', price=1500, duration=1440)
        p = Payment.objects.create(ref='PAY-1', phone='+243 81 234 5678', operator='M-Pesa', plan=plan, amount=1500)
        sub = services.confirm_payment(p, 'test')
        self.assertEqual(sub.username, '812345678')
        p2 = Payment.objects.create(ref='PAY-2', phone='0812345678', operator='M-Pesa', plan=plan, amount=1500)
        self.assertEqual(services.confirm_payment(p2, 'test').pk, sub.pk)


class ApiTests(TestCase):
    def setUp(self):
        for name in roles.ROLES:
            Group.objects.get_or_create(name=name)
        User = get_user_model()
        self.admin = User.objects.create_superuser('admin', '', 'admin12345')
        self.cashier = User.objects.create_user('caisse', '', 'caisse12345')
        self.cashier.groups.add(Group.objects.get(name='Caissier'))
        self.plan = Plan.objects.create(name='Jour', price=1500, duration=60)

    def post(self, url, data):
        return self.client.post(url, json.dumps(data), content_type='application/json')

    def test_state_and_create_user(self):
        self.client.force_login(self.admin)
        r = self.client.get('/api/console/state/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('plans', r.json())
        r = self.post('/api/subscribers/create/', {'username': 'carole', 'plan': self.plan.id, 'phone': '', 'mac': ''})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Subscriber.objects.filter(username='carole').exists())

    def test_cashier_cannot_change_plans(self):
        self.client.force_login(self.cashier)
        r = self.post(f'/api/plans/{self.plan.id}/update/', {'name': 'X', 'price': 1, 'duration': 1, 'validity': 1,
                                                             'quota': 0, 'down': 64, 'up': 64, 'shared': 1})
        self.assertEqual(r.status_code, 403)

    def test_expire_task(self):
        sub = services.create_subscriber(self.plan, Subscriber.Source.MANUAL, 'test', username='dan')
        Subscriber.objects.filter(pk=sub.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        from .tasks import expire_subscribers
        self.assertEqual(expire_subscribers(), 1)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscriber.Status.EXPIRED)
