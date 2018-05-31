# Generated by Django 2.0.2 on 2018-04-02 20:46

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0005_person_slug'),
    ]

    operations = [
        migrations.RunSQL('CREATE UNIQUE INDEX ON payroll_employer (TRIM(LOWER(name)), parent_id)'),
    ]
