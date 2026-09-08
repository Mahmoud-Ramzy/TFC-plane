# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0123_issue_start_target_time"),
    ]

    operations = [
        migrations.AddField(
            model_name="issuecomment",
            name="comment_type",
            field=models.CharField(
                choices=[("TEXT", "TEXT"), ("VOICE", "VOICE")],
                default="TEXT",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="issuecomment",
            name="voice_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
