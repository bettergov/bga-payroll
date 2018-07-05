# Generated by Django 2.0.2 on 2018-07-03 21:47

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0015_auto_20180611_1931'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployerUniverse',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
            ],
        ),
        migrations.AddField(
            model_name='employer',
            name='universe',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='employers', to='payroll.EmployerUniverse'),
        ),
        migrations.RunSQL('''
            INSERT INTO payroll_employeruniverse (name)
              SELECT * FROM (
                VALUES
                  ('Police Department'),
                  ('Fire Department')
              ) AS u
        ''', reverse_sql='DELETE FROM payroll_employeruniverse')
    ]
