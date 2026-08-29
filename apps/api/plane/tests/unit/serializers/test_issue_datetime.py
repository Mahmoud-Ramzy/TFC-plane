# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import date, time

import pytest

from plane.api.serializers.issue import IssueExpandSerializer, IssueSerializer
from plane.app.serializers.issue import (
    IssueCreateSerializer as AppIssueCreateSerializer,
    IssueDetailSerializer as AppIssueDetailSerializer,
    IssueSerializer as AppIssueSerializer,
)
from plane.db.models import Issue, IssueVersion, Project

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project(workspace):
    """A project scoped to the shared test workspace."""
    return Project.objects.create(
        name="Datetime Project",
        identifier="DTP",
        workspace=workspace,
    )


@pytest.fixture
def issue(project):
    """A persisted work item without any dates."""
    return Issue.objects.create(project=project, name="Datetime issue")


def _serialize_and_save(payload, instance=None, project=None):
    """Run the serializer exactly like the API layer would and persist."""
    if instance is None:
        serializer = IssueSerializer(
            data=payload,
            context={
                "project_id": project.id,
                "workspace_id": project.workspace_id,
                "default_assignee_id": None,
            },
        )
        assert serializer.is_valid(), serializer.errors
        return serializer.save(project=project)

    serializer = IssueSerializer(instance, data=payload, partial=True)
    assert serializer.is_valid(), serializer.errors
    return serializer.save()


@pytest.mark.django_db
class TestWorkItemDateTimeInput:
    def test_datetime_input_stores_separate_date_and_time(self, project):
        """Rule: "2026-08-24T14:30" -> start_date=date, start_time=time."""
        result = _serialize_and_save(
            {"name": "WI", "start_date": "2026-08-24T14:30"},
            project=project,
        )
        result.refresh_from_db()
        assert result.start_date == date(2026, 8, 24)
        assert result.start_time == time(14, 30)
        assert result.target_date is None
        assert result.target_time is None

    def test_seconds_are_normalized_to_minutes(self, project):
        """Rule: seconds are accepted but stored as HH:mm."""
        result = _serialize_and_save(
            {"name": "WI", "start_date": "2026-08-24T14:30:45"},
            project=project,
        )
        result.refresh_from_db()
        assert result.start_time == time(14, 30)

    def test_target_date_pair_behaves_identically(self, project):
        """Rule: target_date/target_time mirror the start_date/start_time behavior."""
        result = _serialize_and_save(
            {"name": "WI", "target_date": "2026-08-26T09:15"},
            project=project,
        )
        result.refresh_from_db()
        assert result.target_date == date(2026, 8, 26)
        assert result.target_time == time(9, 15)


@pytest.mark.django_db
class TestWorkItemDateTimeClearing:
    def test_date_only_input_clears_existing_start_time(self, issue):
        """Rule: sending only a date must NOT preserve an old time."""
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(8, 0)
        issue.save()

        _serialize_and_save({"start_date": "2026-08-25"}, instance=issue)
        issue.refresh_from_db()

        assert issue.start_date == date(2026, 8, 25)
        assert issue.start_time is None

    def test_null_clears_both_start_fields(self, issue):
        """Rule: null clears both the date and its paired time."""
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(8, 0)
        issue.save()

        _serialize_and_save({"start_date": None}, instance=issue)
        issue.refresh_from_db()

        assert issue.start_date is None
        assert issue.start_time is None

    def test_date_only_input_clears_existing_target_time(self, issue):
        """Rule: identical clearing semantics for the due-date pair."""
        issue.target_date = date(2026, 8, 24)
        issue.target_time = time(17, 45)
        issue.save()

        _serialize_and_save({"target_date": "2026-08-26"}, instance=issue)
        issue.refresh_from_db()

        assert issue.target_date == date(2026, 8, 26)
        assert issue.target_time is None

    def test_null_clears_both_target_fields(self, issue):
        issue.target_date = date(2026, 8, 24)
        issue.target_time = time(17, 45)
        issue.save()

        _serialize_and_save({"target_date": None}, instance=issue)
        issue.refresh_from_db()

        assert issue.target_date is None
        assert issue.target_time is None

    def test_unrelated_patch_preserves_times(self, issue):
        """Partial updates that do not touch dates keep stored times intact."""
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(8, 0)
        issue.save()

        _serialize_and_save({"name": "Renamed"}, instance=issue)
        issue.refresh_from_db()

        assert issue.name == "Renamed"
        assert issue.start_date == date(2026, 8, 24)
        assert issue.start_time == time(8, 0)


@pytest.mark.django_db
class TestWorkItemDateTimeValidation:
    def _build_serializer(self, issue, payload):
        return IssueSerializer(issue, data=payload, partial=True)

    def test_full_datetime_comparison_when_both_have_times_same_day(self, issue):
        """Same-day ordering is enforced using the times when both are set."""
        issue.target_date = date(2026, 8, 24)
        issue.target_time = time(16, 0)
        issue.save()

        serializer = self._build_serializer(issue, {"start_date": "2026-08-24T16:30"})
        assert not serializer.is_valid()

    def test_equal_datetimes_on_same_day_are_valid(self, issue):
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(16, 0)
        issue.save()

        serializer = self._build_serializer(issue, {"target_date": "2026-08-24T16:00"})
        assert serializer.is_valid(), serializer.errors

    def test_date_only_comparison_stays_backward_compatible_invalid(self, issue):
        """No times involved: original start > target rejection still applies."""
        serializer = self._build_serializer(
            issue,
            {"start_date": "2026-08-25", "target_date": "2026-08-24"},
        )
        assert not serializer.is_valid()
        assert serializer.errors == {"non_field_errors": ["Start date cannot exceed target date"]}

    def test_date_only_comparison_allows_equal_dates(self, issue):
        serializer = self._build_serializer(
            issue,
            {"start_date": "2026-08-24", "target_date": "2026-08-24"},
        )
        assert serializer.is_valid(), serializer.errors

    def test_mixed_precision_falls_back_to_date_only_comparison(self, issue):
        """Start carries a time, target is date-only: compare dates only."""
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(23, 0)
        issue.save()

        # A naive datetime comparison would reject the same calendar day,
        # but date-only semantics allow start_day == target_day.
        serializer = self._build_serializer(issue, {"target_date": "2026-08-24"})
        assert serializer.is_valid(), serializer.errors

    def test_partial_patch_uses_persisted_values_for_validation(self, issue):
        """Validation sees persisted values for keys absent from the PATCH."""
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(18, 0)
        issue.target_date = date(2026, 8, 25)
        issue.target_time = time(9, 0)
        issue.save()

        # Moving the due datetime before the persisted start datetime must fail.
        serializer = self._build_serializer(issue, {"target_date": "2026-08-24T07:00"})
        assert not serializer.is_valid()

        # Clearing the target time drops the comparison to date-only: now valid.
        serializer = self._build_serializer(issue, {"target_date": "2026-08-25"})
        assert serializer.is_valid(), serializer.errors

    def test_invalid_time_component_raises_field_error(self, issue):
        serializer = self._build_serializer(issue, {"start_date": "2026-08-24T25:00"})
        assert not serializer.is_valid()
        assert "start_date" in serializer.errors

    def test_garbage_time_component_raises_field_error(self, issue):
        serializer = self._build_serializer(issue, {"start_date": "2026-08-24Tabc"})
        assert not serializer.is_valid()
        assert "start_date" in serializer.errors

    def test_plain_invalid_date_still_rejected_by_datefield(self, issue):
        serializer = self._build_serializer(issue, {"start_date": "24-08-2026"})
        assert not serializer.is_valid()
        assert "start_date" in serializer.errors


@pytest.mark.django_db
class TestWorkItemDateTimeRepresentation:
    def test_representation_merges_date_and_time(self, issue):
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(9, 15)
        issue.target_date = date(2026, 8, 27)
        issue.target_time = time(18, 45)
        issue.save()

        data = IssueSerializer(issue).data

        assert data["start_date"] == "2026-08-24T09:15"
        assert data["target_date"] == "2026-08-27T18:45"

    def test_representation_keeps_date_only_when_no_time(self, issue):
        issue.start_date = date(2026, 8, 24)
        issue.target_date = date(2026, 8, 27)
        issue.save()

        data = IssueSerializer(issue).data

        assert data["start_date"] == "2026-08-24"
        assert data["target_date"] == "2026-08-27"

    def test_raw_time_columns_are_not_exposed(self, issue):
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(9, 15)
        issue.save()

        data = IssueSerializer(issue).data
        expand_data = IssueExpandSerializer(issue).data

        assert "start_time" not in data
        assert "target_time" not in data
        assert "start_time" not in expand_data
        assert "target_time" not in expand_data
        assert expand_data["start_date"] == "2026-08-24T09:15"


@pytest.mark.django_db
class TestIssueVersionPreservesTimes:
    def test_log_issue_version_persists_times(self, issue, create_user):
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(11, 30)
        issue.target_date = date(2026, 8, 28)
        issue.target_time = time(20, 10)
        issue.save()

        IssueVersion.log_issue_version(issue, create_user)

        version = IssueVersion.objects.filter(issue=issue).latest("created_at")
        assert version.start_date == date(2026, 8, 24)
        assert version.start_time == time(11, 30)
        assert version.target_date == date(2026, 8, 28)
        assert version.target_time == time(20, 10)

    def test_create_issue_version_carries_times(self, issue, create_user):
        from plane.bgtasks.issue_version_sync import create_issue_version

        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(7, 5)
        issue.target_date = date(2026, 8, 29)
        issue.target_time = time(22, 40)
        issue.save()
        # Audit fields are managed outside ORM defaults; set them directly.
        Issue.objects.filter(pk=issue.pk).update(created_by=create_user, updated_by=create_user)
        issue.refresh_from_db()

        related_data = {
            "cycle_issues": {},
            "assignees": {},
            "labels": {},
            "modules": {},
            "activities": {},
        }
        draft_version = create_issue_version(issue, related_data)

        assert draft_version is not None
        assert draft_version.start_time == time(7, 5)
        assert draft_version.target_time == time(22, 40)


# ---------------------------------------------------------------------------
# App serializer path (the actual web UI surface)
# ---------------------------------------------------------------------------


def _app_create(payload, project):
    serializer = AppIssueCreateSerializer(
        data=payload,
        context={
            "project_id": project.id,
            "workspace_id": project.workspace_id,
            "default_assignee_id": None,
        },
    )
    assert serializer.is_valid(), serializer.errors
    return serializer.save()


def _app_patch(instance, payload):
    serializer = AppIssueCreateSerializer(instance, data=payload, partial=True)
    assert serializer.is_valid(), serializer.errors
    return serializer.save()


@pytest.mark.django_db
class TestAppIssueCreateSerializerDateTime:
    def test_create_with_start_datetime_stores_pair(self, project):
        result = _app_create({"name": "WI", "start_date": "2026-08-24T09:15"}, project=project)
        result.refresh_from_db()
        assert result.start_date == date(2026, 8, 24)
        assert result.start_time == time(9, 15)

    def test_create_with_target_datetime_stores_pair(self, project):
        result = _app_create({"name": "WI", "target_date": "2026-08-26T18:45"}, project=project)
        result.refresh_from_db()
        assert result.target_date == date(2026, 8, 26)
        assert result.target_time == time(18, 45)

    def test_update_existing_issue_with_datetime(self, issue):
        issue.target_date = date(2026, 8, 24)
        issue.target_time = time(14, 30)
        issue.save()

        _app_patch(issue, {"start_date": "2026-08-24T09:15"})
        issue.refresh_from_db()
        assert (issue.start_date, issue.start_time) == (date(2026, 8, 24), time(9, 15))

    def test_same_day_ordering_enforced_with_times(self, issue):
        issue.target_date = date(2026, 8, 24)
        issue.target_time = time(14, 30)
        issue.save()

        serializer = AppIssueCreateSerializer(issue, data={"start_date": "2026-08-24T16:00"}, partial=True)
        assert not serializer.is_valid()

    def test_date_only_input_clears_existing_time(self, issue):
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(8, 0)
        issue.save()

        _app_patch(issue, {"start_date": "2026-08-25"})
        issue.refresh_from_db()
        assert issue.start_date == date(2026, 8, 25) and issue.start_time is None

    def test_null_clears_both_fields(self, issue):
        issue.target_date = date(2026, 8, 24)
        issue.target_time = time(17, 0)
        issue.save()

        _app_patch(issue, {"target_date": None})
        issue.refresh_from_db()
        assert issue.target_date is None and issue.target_time is None

    def test_unrelated_patch_preserves_times(self, issue):
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(8, 0)
        issue.save()

        _app_patch(issue, {"name": "Renamed"})
        issue.refresh_from_db()
        assert issue.name == "Renamed" and issue.start_time == time(8, 0)

    def test_date_only_backward_compat_invalid_ordering(self, issue):
        serializer = AppIssueCreateSerializer(
            issue,
            data={"start_date": "2026-08-25", "target_date": "2026-08-24"},
            partial=True,
        )
        assert not serializer.is_valid()
        assert serializer.errors == {"non_field_errors": ["Start date cannot exceed target date"]}


@pytest.mark.django_db
class TestAppIssueRepresentation:
    def test_read_serializer_merges_and_hides_raw_columns(self, issue):
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(11, 20)
        issue.target_date = date(2026, 8, 27)
        issue.target_time = time(19, 55)
        issue.save()

        data = AppIssueSerializer(issue).data

        assert data["start_date"] == "2026-08-24T11:20"
        assert data["target_date"] == "2026-08-27T19:55"
        assert "start_time" not in data and "target_time" not in data

    def test_detail_serializer_inherits_merge(self, issue):
        issue.start_date = date(2026, 8, 24)
        issue.start_time = time(6, 30)
        issue.save()

        detail_data = AppIssueDetailSerializer(issue).data
        assert detail_data["start_date"] == "2026-08-24T06:30"

    def test_create_serializer_response_merges(self, project):
        # Mirror the real view flow: render through the SAME serializer
        # instance that performed validation/creation (it owns initial_data).
        serializer = AppIssueCreateSerializer(
            data={"name": "WI", "start_date": "2026-08-24T21:10"},
            context={
                "project_id": project.id,
                "workspace_id": project.workspace_id,
                "default_assignee_id": None,
            },
        )
        assert serializer.is_valid(), serializer.errors
        result = serializer.save()

        data = serializer.data
        assert result.start_date == date(2026, 8, 24)
        assert result.start_time == time(21, 10)
        assert data["start_date"] == "2026-08-24T21:10"
        assert "start_time" not in data
