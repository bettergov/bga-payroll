# Generated by Django 2.0.2 on 2018-06-11 19:31

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0014_auto_20180611_1850'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='position',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='jobs', to='payroll.Position'),
        ),
    ]
