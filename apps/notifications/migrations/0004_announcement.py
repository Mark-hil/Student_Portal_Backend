# Generated manually for Announcement model

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_smslog'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Announcement',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=255)),
                ('content', models.TextField()),
                ('category', models.CharField(choices=[('general', 'General Notice'), ('academic', 'Academic Circular'), ('examination', 'Examination Notice'), ('financial', 'Bursary & Fee Deadline'), ('emergency', 'Urgent Campus Alert')], db_index=True, default='general', max_length=30)),
                ('target_audience', models.CharField(choices=[('all', 'All Campus Accounts'), ('students', 'Students Only'), ('faculty', 'Lecturers & Faculty'), ('staff', 'Administrative Staff')], db_index=True, default='all', max_length=30)),
                ('author_name', models.CharField(blank=True, max_length=150)),
                ('author_role', models.CharField(blank=True, max_length=50)),
                ('is_pinned', models.BooleanField(db_index=True, default=False)),
                ('is_published', models.BooleanField(db_index=True, default=True)),
                ('attachment_url', models.URLField(blank=True)),
                ('attachment_name', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='announcements', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'announcements',
                'ordering': ['-is_pinned', '-created_at'],
                'indexes': [
                    models.Index(fields=['is_published', 'target_audience', 'created_at'], name='announcemen_is_publ_56f8a4_idx'),
                    models.Index(fields=['category', 'is_published'], name='announcemen_categor_60f878_idx'),
                ],
            },
        ),
    ]
