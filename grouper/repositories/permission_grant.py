from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import or_

from grouper.entities.group_edge import GROUP_EDGE_ROLES
from grouper.entities.permission_grant import (
    GroupPermissionGrant,
    PermissionGrant,
    ServiceAccountPermissionGrant,
)
from grouper.models.base.constants import OBJ_TYPES
from grouper.models.group import Group
from grouper.models.group_edge import GroupEdge
from grouper.models.permission import Permission
from grouper.models.permission_map import PermissionMap
from grouper.models.service_account import ServiceAccount
from grouper.models.service_account_permission_map import ServiceAccountPermissionMap
from grouper.models.user import User
from grouper.repositories.interfaces import PermissionGrantRepository

if TYPE_CHECKING:
    from grouper.graph import GroupGraph
    from grouper.models.base.session import Session
    from typing import List


class GraphPermissionGrantRepository(PermissionGrantRepository):
    """Graph-aware storage layer for permission grants."""

    def __init__(self, graph, repository):
        # type: (GroupGraph, PermissionGrantRepository) -> None
        self.graph = graph
        self.repository = repository

    def group_grants_for_permission(self, name):
        # type: (str) -> List[GroupPermissionGrant]
        return self.repository.group_grants_for_permission(name)

    def permission_grants_for_user(self, name):
        # type: (str) -> List[PermissionGrant]
        user_details = self.graph.get_user_details(name)
        permissions = []
        for permission_data in user_details["permissions"]:
            permission = PermissionGrant(
                name=permission_data["permission"], argument=permission_data["argument"]
            )
            permissions.append(permission)
        return permissions

    def service_account_grants_for_permission(self, name):
        # type: (str) -> List[ServiceAccountPermissionGrant]
        return self.repository.service_account_grants_for_permission(name)

    def user_has_permission(self, user, permission):
        # type: (str, str) -> bool
        for user_permission in self.permission_grants_for_user(user):
            if permission == user_permission.name:
                return True
        return False


class SQLPermissionGrantRepository(PermissionGrantRepository):
    """SQL storage layer for permission grants."""

    def __init__(self, session):
        # type: (Session) -> None
        self.session = session

    def group_grants_for_permission(self, name):
        # type: (str) -> List[GroupPermissionGrant]
        permission = Permission.get(self.session, name=name)
        if not permission or not permission.enabled:
            return []
        grants = (
            self.session.query(Group.groupname, PermissionMap.argument)
            .filter(
                PermissionMap.permission_id == permission.id,
                Group.id == PermissionMap.group_id,
                Group.enabled == True,
            )
            .order_by(Group.groupname, PermissionMap.argument)
            .all()
        )
        return [GroupPermissionGrant(g.groupname, name, g.argument) for g in grants]

    def permission_grants_for_user(self, name):
        # type: (str) -> List[PermissionGrant]
        now = datetime.utcnow()
        user = User.get(self.session, name=name)
        if not user or user.role_user or user.is_service_account or not user.enabled:
            return []

        # Get the groups of which this user is a direct member.
        groups = (
            self.session.query(Group.id)
            .join(GroupEdge, Group.id == GroupEdge.group_id)
            .join(User, User.id == GroupEdge.member_pk)
            .filter(
                Group.enabled == True,
                User.id == user.id,
                GroupEdge.active == True,
                GroupEdge.member_type == OBJ_TYPES["User"],
                GroupEdge._role != GROUP_EDGE_ROLES.index("np-owner"),
                or_(GroupEdge.expiration > now, GroupEdge.expiration == None),
            )
            .distinct()
        )
        group_ids = [g.id for g in groups]

        # If the user was not a member of any group, we can return early.
        if not group_ids:
            return []

        # Now, get the parent groups of those groups and so forth until we run out of levels of the
        # tree.  Use a set of seen group_ids to avoid querying the same group twice if a user is a
        # member of it via multiple paths.
        seen_group_ids = set(group_ids)
        while group_ids:
            parent_groups = (
                self.session.query(Group.id)
                .join(GroupEdge, Group.id == GroupEdge.group_id)
                .filter(
                    GroupEdge.member_pk.in_(group_ids),
                    Group.enabled == True,
                    GroupEdge.active == True,
                    GroupEdge.member_type == OBJ_TYPES["Group"],
                    GroupEdge._role != GROUP_EDGE_ROLES.index("np-owner"),
                    or_(GroupEdge.expiration > now, GroupEdge.expiration == None),
                )
                .distinct()
            )
            group_ids = [g.id for g in parent_groups if g.id not in seen_group_ids]
            seen_group_ids.update(group_ids)

        # Return the permission grants.
        group_permission_grants = (
            self.session.query(Permission.name, PermissionMap.argument)
            .filter(
                Permission.id == PermissionMap.permission_id,
                PermissionMap.group_id.in_(seen_group_ids),
            )
            .all()
        )
        return [PermissionGrant(g.name, g.argument) for g in group_permission_grants]

    def service_account_grants_for_permission(self, name):
        # type: (str) -> List[ServiceAccountPermissionGrant]
        permission = Permission.get(self.session, name=name)
        if not permission or not permission.enabled:
            return []
        grants = (
            self.session.query(User.username, ServiceAccountPermissionMap.argument)
            .filter(
                ServiceAccountPermissionMap.permission_id == permission.id,
                ServiceAccount.id == ServiceAccountPermissionMap.service_account_id,
                User.id == ServiceAccount.user_id,
                User.enabled == True,
            )
            .order_by(User.username, ServiceAccountPermissionMap.argument)
            .all()
        )
        return [ServiceAccountPermissionGrant(g.username, name, g.argument) for g in grants]

    def user_has_permission(self, user, permission):
        # type: (str, str) -> bool
        for user_permission in self.permission_grants_for_user(user):
            if permission == user_permission.name:
                return True
        return False
