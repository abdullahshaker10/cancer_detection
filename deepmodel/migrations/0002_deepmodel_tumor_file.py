# Generated by Django 3.1 on 2020-08-17 12:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deepmodel', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='deepmodel',
            name='tumor_file',
            field=models.FileField(default='', upload_to='DICOM/'),
        ),
    ]
