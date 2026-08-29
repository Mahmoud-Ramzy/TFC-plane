# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Regression coverage: Work Item assignees may include a Guest who has been
explicitly invited to the project (a ProjectMember with the Guest role).

Guests who are only Workspace members (not ProjectMembers of the target project)
must remain non-assignable. Admin/Member assignee behavior is unchanged.
"""

from uuid import uuid4

import pytest

from plane.api.serializers.issue import IssueSerializer
from plane.app.serializers.draft import DraftIssueCreateSerializer
from plane.app.serializers.issue import IssueCreateSerializer as AppIssueCreateSerializer
from plane.db.models import (
    DraftIssueAssignee,
    Issue,
    IssueAssignee,
    Project,
    ProjectMember,
    User,
    WorkspaceMember,
)

pytestmark = [pytest.mark.unit]

# Roles: ADMIN=20, MEMBER=15, GUEST=5 (mirrors plane.app.permissions.ROLE).
GUEST = 5
MEMBER = 15
ADMIN = 20


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def project(workspace):
    """A project; the shared ``create_user`` is its owner/member."""
    return Project.objects.create(name="Assignee Project", identifier="AP", workspace=workspace)


def _make_user(workspace, project, role, tag, is_project_member):
    """Create a user with the given workspace, and optionally project, role."""
    email = f"{tag}-{uuid4().hex[:8]}@plane.so"
    user = User.objects.create(email=email, username=tag, first_name=tag)
    user.set_password("test-password")
    user.save()
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    if is_project_member:
        ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    return user


def _guest_in_project(workspace, project):
    return _make_user(workspace, project, GUEST, "guest", True)


def _workspace_only_guest(workspace, project):
    return _make_user(workspace, project, GUEST, "wguest", False)


def _member(workspace, project):
    return _make_user(workspace, project, MEMBER, "member", True)


def _admin(workspace, project):
    return _make_user(workspace, project, ADMIN, "admin", True)


def _app_context(project):
    return {"project_id": project.id, "workspace_id": project.workspace_id, "default_assignee_id": None}


def _api_context(project):
    return {"project_id": project.id, "workspace_id": project.workspace_id, "default_assignee_id": None}


def _app_create(payload, project):
    serializer = AppIssueCreateSerializer(data=payload, context=_app_context(project))
    assert serializer.is_valid(), serializer.errors
    return serializer.save()


def _api_create(payload, project):
    serializer = IssueSerializer(data=payload, context=_api_context(project))
    assert serializer.is_valid(), serializer.errors
    return serializer.save()


def _app_patch(instance, payload, project):
    serializer = AppIssueCreateSerializer(instance, data=payload, partial=True, context=_app_context(project))
    assert serializer.is_valid(), serializer.errors
    return serializer.save()


def _app_assignee_ids(issue):
    return list(IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True))


# --------------------------------------------------------------------------- #
# Guest assignee is allowed on create (app serializer = web surface)
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestGuestAssigneeOnCreate:
    def test_app_create_assigns_invited_project_guest(self, workspace, project):
        guest = _guest_in_project(workspace, project)
        issue = _app_create({"name": "WI", "assignee_ids": [guest.id]}, project)
        issue.refresh_from_db()
        assert _app_assignee_ids(issue) == [guest.id]

    def test_api_create_assigns_invited_project_guest(self, workspace, project):
        guest = _guest_in_project(workspace, project)
        issue = _api_create({"name": "WI", "assignees": [guest.id]}, project)
        issue.refresh_from_db()
        assert _app_assignee_ids(issue) == [guest.id]


# --------------------------------------------------------------------------- #
# Guest assignee is allowed on update (PATCH)
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Guest assignee is allowed on update (PATCH)
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestGuestAssigneeOnPatch:
    def test_patch_adds_invited_project_guest(self, workspace, project):
        issue = Issue.objects.create(project=project, workspace=workspace, name="WI")
        guest = _guest_in_project(workspace, project)

        _app_patch(issue, {"assignee_ids": [guest.id]}, project)
        issue.refresh_from_db()
        assert _app_assignee_ids(issue) == [guest.id]


# --------------------------------------------------------------------------- #
# A Guest who is NOT a ProjectMember of this project must NOT be assignable
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestNonProjectGuestRejected:
    def test_app_create_rejects_workspace_only_guest(self, workspace, project):
        guest = _workspace_only_guest(workspace, project)
        issue = _app_create({"name": "WI", "assignee_ids": [guest.id]}, project)
        issue.refresh_from_db()
        # A Workspace-only Guest is not a ProjectMember -> silently dropped.
        assert _app_assignee_ids(issue) == []

    def test_api_create_rejects_workspace_only_guest(self, workspace, project):
        guest = _workspace_only_guest(workspace, project)
        issue = _api_create({"name": "WI", "assignees": [guest.id]}, project)
        issue.refresh_from_db()
        assert _app_assignee_ids(issue) == []

    def test_patch_rejects_workspace_only_guest(self, workspace, project):
        issue = Issue.objects.create(project=project, workspace=workspace, name="WI")
        guest = _workspace_only_guest(workspace, project)

        _app_patch(issue, {"assignee_ids": [guest.id]}, project)
        issue.refresh_from_db()
        assert _app_assignee_ids(issue) == []


# --------------------------------------------------------------------------- #
# Admin/Member assignment behavior unchanged (regression guard)
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestAdminMemberRegression:
    def test_member_still_assignable(self, workspace, project):
        member = _member(workspace, project)
        issue = _app_create({"name": "WI", "assignee_ids": [member.id]}, project)
        issue.refresh_from_db()
        assert _app_assignee_ids(issue) == [member.id]

    def test_admin_still_assignable(self, workspace, project):
        admin = _admin(workspace, project)
        issue = _app_create({"name": "WI", "assignee_ids": [admin.id]}, project)
        issue.refresh_from_db()
        assert _app_assignee_ids(issue) == [admin.id]


# --------------------------------------------------------------------------- #
# Draft Work Item Guest assignment
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestDraftGuestAssignee:
    def test_draft_create_assigns_invited_project_guest(self, workspace, project):
        guest = _guest_in_project(workspace, project)
        serializer = DraftIssueCreateSerializer(
            data={"name": "Draft WI", "assignee_ids": [guest.id]},
            context={
                "project_id": project.id,
                "workspace_id": project.workspace_id,
            },
        )
        assert serializer.is_valid(), serializer.errors
        draft = serializer.save()

        draft.refresh_from_db()
        assert list(
            DraftIssueAssignee.objects.filter(draft_issue=draft).values_list("assignee_id", flat=True)
        ) == [guest.id]

    def test_draft_rejects_workspace_only_guest(self, workspace, project):
        guest = _workspace_only_guest(workspace, project)
        serializer = DraftIssueCreateSerializer(
            data={"name": "Draft WI", "assignee_ids": [guest.id]},
            context={
                "project_id": project.id,
                "workspace_id": project.workspace_id,
            },
        )
        assert serializer.is_valid(), serializer.errors
        draft = serializer.save()

        draft.refresh_from_db()
        assert list(
            DraftIssueAssignee.objects.filter(draft_issue=draft).values_list("assignee_id", flat=True)
        ) == []