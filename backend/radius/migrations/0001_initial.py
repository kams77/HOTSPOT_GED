import django.db.models.functions.datetime
from django.db import migrations, models


def attr_fields(name_field):
    return [
        ('id', models.AutoField(primary_key=True, serialize=False)),
        ('attribute', models.TextField(default='')),
        ('op', models.CharField(default=':=', max_length=2)),
        ('value', models.TextField(default='')),
        (name_field, models.TextField(db_index=True, default='')),
    ]


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(name='RadCheck', fields=attr_fields('username'),
                               options={'db_table': 'radcheck', 'verbose_name': 'contrôle utilisateur (radcheck)'}),
        migrations.CreateModel(name='RadReply', fields=attr_fields('username'),
                               options={'db_table': 'radreply', 'verbose_name': 'réponse utilisateur (radreply)'}),
        migrations.CreateModel(name='RadGroupCheck', fields=attr_fields('groupname'),
                               options={'db_table': 'radgroupcheck', 'verbose_name': 'contrôle de groupe (radgroupcheck)'}),
        migrations.CreateModel(name='RadGroupReply', fields=attr_fields('groupname'),
                               options={'db_table': 'radgroupreply', 'verbose_name': 'réponse de groupe (radgroupreply)'}),
        migrations.CreateModel(
            name='RadUserGroup',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('username', models.TextField(db_index=True, default='')),
                ('groupname', models.TextField(default='')),
                ('priority', models.IntegerField(default=0)),
            ],
            options={'db_table': 'radusergroup', 'verbose_name': 'groupe utilisateur (radusergroup)'},
        ),
        migrations.CreateModel(
            name='RadAcct',
            fields=[
                ('radacctid', models.BigAutoField(primary_key=True, serialize=False)),
                ('acctsessionid', models.TextField()),
                ('acctuniqueid', models.TextField(unique=True)),
                ('username', models.TextField(blank=True, null=True)),
                ('realm', models.TextField(blank=True, null=True)),
                ('nasipaddress', models.GenericIPAddressField()),
                ('nasportid', models.TextField(blank=True, null=True)),
                ('nasporttype', models.TextField(blank=True, null=True)),
                ('acctstarttime', models.DateTimeField(blank=True, null=True)),
                ('acctupdatetime', models.DateTimeField(blank=True, null=True)),
                ('acctstoptime', models.DateTimeField(blank=True, null=True)),
                ('acctinterval', models.BigIntegerField(blank=True, null=True)),
                ('acctsessiontime', models.BigIntegerField(blank=True, null=True)),
                ('acctauthentic', models.TextField(blank=True, null=True)),
                ('connectinfo_start', models.TextField(blank=True, null=True)),
                ('connectinfo_stop', models.TextField(blank=True, null=True)),
                ('acctinputoctets', models.BigIntegerField(blank=True, null=True)),
                ('acctoutputoctets', models.BigIntegerField(blank=True, null=True)),
                ('calledstationid', models.TextField(blank=True, null=True)),
                ('callingstationid', models.TextField(blank=True, null=True)),
                ('acctterminatecause', models.TextField(blank=True, null=True)),
                ('servicetype', models.TextField(blank=True, null=True)),
                ('framedprotocol', models.TextField(blank=True, null=True)),
                ('framedipaddress', models.GenericIPAddressField(blank=True, null=True)),
                ('framedipv6address', models.GenericIPAddressField(blank=True, null=True)),
                ('framedipv6prefix', models.TextField(blank=True, null=True)),
                ('framedinterfaceid', models.TextField(blank=True, null=True)),
                ('delegatedipv6prefix', models.TextField(blank=True, null=True)),
                ('class_attr', models.TextField(blank=True, db_column='class', null=True)),
            ],
            options={
                'db_table': 'radacct',
                'verbose_name': 'session (radacct)',
                'indexes': [
                    models.Index(fields=['username'], name='radacct_username_idx'),
                    models.Index(fields=['acctstarttime'], name='radacct_start_idx'),
                    models.Index(fields=['acctstoptime'], name='radacct_stop_idx'),
                    models.Index(fields=['nasipaddress'], name='radacct_nas_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='RadPostAuth',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('username', models.TextField()),
                ('password', models.TextField(blank=True, db_column='pass', null=True)),
                ('reply', models.TextField(blank=True, null=True)),
                ('calledstationid', models.TextField(blank=True, null=True)),
                ('callingstationid', models.TextField(blank=True, null=True)),
                ('authdate', models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ('class_attr', models.TextField(blank=True, db_column='class', null=True)),
            ],
            options={'db_table': 'radpostauth', 'verbose_name': 'tentative de connexion (radpostauth)'},
        ),
        migrations.CreateModel(
            name='Nas',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('nasname', models.TextField(db_index=True, verbose_name='adresse IP')),
                ('shortname', models.TextField(verbose_name='nom')),
                ('type', models.TextField(default='other')),
                ('ports', models.IntegerField(blank=True, null=True)),
                ('secret', models.TextField(verbose_name='secret partagé')),
                ('server', models.TextField(blank=True, null=True)),
                ('community', models.TextField(blank=True, null=True)),
                ('description', models.TextField(blank=True, default='RADIUS Client', null=True)),
                ('require_ma', models.TextField(default='auto')),
                ('limit_proxy_state', models.TextField(default='auto')),
                ('vendor', models.CharField(blank=True, default='', max_length=60, verbose_name='matériel')),
                ('zone', models.CharField(blank=True, default='', max_length=80)),
                ('online', models.BooleanField(default=False)),
                ('last_seen', models.DateTimeField(blank=True, null=True)),
            ],
            options={'db_table': 'nas', 'verbose_name': 'routeur (NAS)', 'verbose_name_plural': 'routeurs (NAS)'},
        ),
    ]
