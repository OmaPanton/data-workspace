# Generated by Django 2.2.4 on 2019-09-14 17:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0009_auto_20190914_1306'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='applicationinstance',
            index=models.Index(fields=['created_date'], name='app_applica_created_29c0c8_idx'),
        ),
    ]
