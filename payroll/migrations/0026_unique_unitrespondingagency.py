# Generated by Django 2.0.2 on 2019-03-04 22:25

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0025_rename_education_taxonomy'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='unitrespondingagency',
            unique_together={('unit', 'reporting_year')},
        ),
    ]
