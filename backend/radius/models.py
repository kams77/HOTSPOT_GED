"""Tables FreeRADIUS (schéma PostgreSQL officiel de FreeRADIUS 3.2).

Django crée ces tables par migration ; FreeRADIUS les lit et les écrit
directement via le module rlm_sql. Les noms de tables et de colonnes sont
en minuscules, comme dans le schéma officiel.
"""
from django.db import models
from django.db.models.functions import Now


class _AttrRow(models.Model):
    id = models.AutoField(primary_key=True)
    attribute = models.TextField(default='')
    op = models.CharField(max_length=2, default=':=')
    value = models.TextField(default='')

    class Meta:
        abstract = True

    def __str__(self):
        return f'{self.attribute} {self.op} {self.value}'


class RadCheck(_AttrRow):
    username = models.TextField(default='', db_index=True)

    class Meta:
        db_table = 'radcheck'
        verbose_name = 'contrôle utilisateur (radcheck)'


class RadReply(_AttrRow):
    username = models.TextField(default='', db_index=True)

    class Meta:
        db_table = 'radreply'
        verbose_name = 'réponse utilisateur (radreply)'


class RadGroupCheck(_AttrRow):
    groupname = models.TextField(default='', db_index=True)

    class Meta:
        db_table = 'radgroupcheck'
        verbose_name = 'contrôle de groupe (radgroupcheck)'


class RadGroupReply(_AttrRow):
    groupname = models.TextField(default='', db_index=True)

    class Meta:
        db_table = 'radgroupreply'
        verbose_name = 'réponse de groupe (radgroupreply)'


class RadUserGroup(models.Model):
    id = models.AutoField(primary_key=True)
    username = models.TextField(default='', db_index=True)
    groupname = models.TextField(default='')
    priority = models.IntegerField(default=0)

    class Meta:
        db_table = 'radusergroup'
        verbose_name = 'groupe utilisateur (radusergroup)'

    def __str__(self):
        return f'{self.username} → {self.groupname}'


class RadAcct(models.Model):
    radacctid = models.BigAutoField(primary_key=True)
    acctsessionid = models.TextField()
    acctuniqueid = models.TextField(unique=True)
    username = models.TextField(null=True, blank=True)
    realm = models.TextField(null=True, blank=True)
    nasipaddress = models.GenericIPAddressField()
    nasportid = models.TextField(null=True, blank=True)
    nasporttype = models.TextField(null=True, blank=True)
    acctstarttime = models.DateTimeField(null=True, blank=True)
    acctupdatetime = models.DateTimeField(null=True, blank=True)
    acctstoptime = models.DateTimeField(null=True, blank=True)
    acctinterval = models.BigIntegerField(null=True, blank=True)
    acctsessiontime = models.BigIntegerField(null=True, blank=True)
    acctauthentic = models.TextField(null=True, blank=True)
    connectinfo_start = models.TextField(null=True, blank=True)
    connectinfo_stop = models.TextField(null=True, blank=True)
    acctinputoctets = models.BigIntegerField(null=True, blank=True)
    acctoutputoctets = models.BigIntegerField(null=True, blank=True)
    calledstationid = models.TextField(null=True, blank=True)
    callingstationid = models.TextField(null=True, blank=True)
    acctterminatecause = models.TextField(null=True, blank=True)
    servicetype = models.TextField(null=True, blank=True)
    framedprotocol = models.TextField(null=True, blank=True)
    framedipaddress = models.GenericIPAddressField(null=True, blank=True)
    framedipv6address = models.GenericIPAddressField(null=True, blank=True)
    framedipv6prefix = models.TextField(null=True, blank=True)
    framedinterfaceid = models.TextField(null=True, blank=True)
    delegatedipv6prefix = models.TextField(null=True, blank=True)
    class_attr = models.TextField(db_column='class', null=True, blank=True)

    class Meta:
        db_table = 'radacct'
        verbose_name = 'session (radacct)'
        indexes = [
            models.Index(fields=['username'], name='radacct_username_idx'),
            models.Index(fields=['acctstarttime'], name='radacct_start_idx'),
            models.Index(fields=['acctstoptime'], name='radacct_stop_idx'),
            models.Index(fields=['nasipaddress'], name='radacct_nas_idx'),
        ]

    def __str__(self):
        return f'{self.username} @ {self.nasipaddress}'


class RadPostAuth(models.Model):
    id = models.BigAutoField(primary_key=True)
    username = models.TextField()
    # « pass » est un mot réservé Python : on renomme le champ.
    password = models.TextField(db_column='pass', null=True, blank=True)
    reply = models.TextField(null=True, blank=True)
    calledstationid = models.TextField(null=True, blank=True)
    callingstationid = models.TextField(null=True, blank=True)
    authdate = models.DateTimeField(db_default=Now())
    class_attr = models.TextField(db_column='class', null=True, blank=True)

    class Meta:
        db_table = 'radpostauth'
        verbose_name = 'tentative de connexion (radpostauth)'


class Nas(models.Model):
    """Routeur / point d'accès autorisé à interroger le serveur RADIUS."""
    id = models.AutoField(primary_key=True)
    nasname = models.TextField('adresse IP', db_index=True)
    shortname = models.TextField('nom')
    type = models.TextField(default='other')
    ports = models.IntegerField(null=True, blank=True)
    secret = models.TextField('secret partagé')
    server = models.TextField(null=True, blank=True)
    community = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True, default='RADIUS Client')
    require_ma = models.TextField(default='auto')
    limit_proxy_state = models.TextField(default='auto')
    # Colonnes propres à HotSpot Pro (ignorées par FreeRADIUS)
    vendor = models.CharField('matériel', max_length=60, blank=True, default='')
    zone = models.CharField(max_length=80, blank=True, default='')
    online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'nas'
        verbose_name = 'routeur (NAS)'
        verbose_name_plural = 'routeurs (NAS)'

    def __str__(self):
        return f'{self.shortname} ({self.nasname})'
