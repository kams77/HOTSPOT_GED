from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='web_filters',
            field=models.JSONField(blank=True, default=dict, verbose_name='catégories de sites bloquées'),
        ),
    ]
