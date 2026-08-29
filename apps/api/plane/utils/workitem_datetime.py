# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work Item start/due date-time split & merge helpers.

The Work Item API accepts either a plain date ("2026-08-24") or an ISO
date-time ("2026-08-24T14:30"). The optional timezone-free wall-clock time is
stored in separate nullable TimeField columns (start_time/target_time) and
merged back into the combined ISO string when serializing.
"""

# Python imports
from datetime import time

# Third party imports
from rest_framework import serializers

WORKITEM_DATETIME_FIELD_PAIRS = (
    ("start_date", "start_time"),
    ("target_date", "target_time"),
)


def _parse_workitem_time(value: str, field_name: str):
    """Parse the time portion ("HH:mm" or "HH:mm:ss") of a work item date-time value."""
    parts = value.split(":")
    if len(parts) < 2 or len(parts) > 3 or not all(part.isdigit() for part in parts):
        raise serializers.ValidationError(
            {field_name: "Datetime has wrong format. Use ISO 8601 (YYYY-MM-DDTHH:mm)."}
        )
    hours, minutes = int(parts[0]), int(parts[1])
    seconds = int(parts[2]) if len(parts) == 3 else 0
    if hours > 23 or minutes > 59 or seconds > 59:
        raise serializers.ValidationError(
            {field_name: "Datetime has wrong format. Use ISO 8601 (YYYY-MM-DDTHH:mm)."}
        )
    # Work item times carry minute precision; incoming seconds are validated
    # then truncated.
    return time(hours, minutes)


def split_workitem_datetime_payload(data):
    """Normalize an incoming work item payload by splitting combined
    "YYYY-MM-DDTHH:mm" values into their date and time columns.

    - A date-only value explicitly clears the paired time column.
    - A null value clears both the date and the paired time column.
    """
    normalized = data.copy() if hasattr(data, "copy") else dict(data)
    for date_key, time_key in WORKITEM_DATETIME_FIELD_PAIRS:
        if date_key not in normalized:
            continue
        raw_value = normalized[date_key]
        if raw_value is None:
            normalized[time_key] = None
        elif isinstance(raw_value, str) and "T" in raw_value:
            date_part, _, time_part = raw_value.partition("T")
            normalized[date_key] = date_part
            normalized[time_key] = _parse_workitem_time(time_part, date_key)
        else:
            # Date-only payload: the paired time column is explicitly cleared.
            normalized[time_key] = None
    return normalized


def merge_workitem_datetime_representation(data, instance):
    """Merge the paired nullable time columns back into combined
    "YYYY-MM-DDTHH:mm" strings for API responses."""
    if instance is not None:
        for date_key, time_key in WORKITEM_DATETIME_FIELD_PAIRS:
            time_value = getattr(instance, time_key, None)
            if time_value is not None and data.get(date_key):
                data[date_key] = f"{data[date_key]}T{time_value.strftime('%H:%M')}"
    # The helper columns are never exposed directly.
    data.pop("start_time", None)
    data.pop("target_time", None)
    return data
