from __future__ import annotations

import pytest

from app.core.auth import resolve_role_from_groups
from app.models.admin import RoleEnum


@pytest.mark.parametrize(
    ("raw_groups", "expected"),
    [
        ("armonia-owner", RoleEnum.OWNER),
        ("armonia-assistant", RoleEnum.ASSISTANT),
        ("armonia-admin", RoleEnum.ADMIN),
        # Authelia emits comma-separated groups; unrelated LLDAP groups are ignored
        ("users,armonia-assistant,family", RoleEnum.ASSISTANT),
        # Whitespace and case from the proxy must not break matching
        ("  Users , ARMONIA-Owner ", RoleEnum.OWNER),
    ],
)
def test_resolve_role_maps_lldap_groups_to_roles(raw_groups: str, expected: RoleEnum):
    assert resolve_role_from_groups(raw_groups) is expected


@pytest.mark.parametrize(
    "raw_groups",
    [
        "armonia-owner,armonia-assistant",
        "armonia-assistant,armonia-owner",
        "armonia-admin,armonia-owner,armonia-assistant",
    ],
)
def test_resolve_role_picks_highest_privilege_regardless_of_order(raw_groups: str):
    assert resolve_role_from_groups(raw_groups) is RoleEnum.OWNER


def test_resolve_role_prefers_admin_over_assistant():
    assert resolve_role_from_groups("armonia-assistant,armonia-admin") is RoleEnum.ADMIN


@pytest.mark.parametrize(
    "raw_groups",
    [None, "", "   ", "users,admins", "armonia", "armonia-owners", "not-armonia-owner"],
)
def test_resolve_role_returns_none_without_an_exact_armonia_group(raw_groups: str | None):
    assert resolve_role_from_groups(raw_groups) is None
