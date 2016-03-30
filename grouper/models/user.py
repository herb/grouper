import re
from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, or_, asc
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.sql import label, literal

from grouper.constants import PERMISSION_GRANT, PERMISSION_CREATE, MAX_NAME_LENGTH, PERMISSION_VALIDATION, PERMISSION_ADMIN, GROUP_ADMIN, USER_ADMIN
from grouper.models.audit import Audit
from grouper.models.counter import Counter
from grouper.models.group_edge import APPROVER_ROLE_INDICIES, GROUP_EDGE_ROLES, OWNER_ROLE_INDICES
from grouper.models.model_base import Model
from grouper.models.permission import Permission
from grouper.models.permission_map import PermissionMap
from grouper.models.public_key import PublicKey
from grouper.models.user_metadata import UserMetadata
from grouper.plugin import get_plugins
import grouper.models.group
import grouper.models.request


class User(Model):

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(length=MAX_NAME_LENGTH), unique=True, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    role_user = Column(Boolean, default=False, nullable=False)
    tokens = relationship("UserToken", back_populates="user")

    @hybrid_property
    def name(self):
        return self.username

    @property
    def type(self):
        return "User"

    def __repr__(self):
        return "<%s: id=%s username=%s>" % (
            type(self).__name__, self.id, self.username)

    @staticmethod
    def get(session, pk=None, name=None):
        if pk is not None:
            return session.query(User).filter_by(id=pk).scalar()
        if name is not None:
            return session.query(User).filter_by(username=name).scalar()
        return None

    def just_created(self):
        for plugin in get_plugins():
            plugin.user_created(self)

    def can_manage(self, group):
        """Determine if this user can manage the given group

        This returns true if this user object is a manager, owner, or np-owner of the given group.

        Args:
            group (Group): Group to check permissions against.

        Returns:
            bool: True or False on whether or not they can manage.
        """
        # avoid circular dependency ; ideally this method exists at a higher level of abstraction
        from grouper.models.group import Group

        if not group:
            return False
        members = group.my_members()
        if self.my_role(members) in ("owner", "np-owner", "manager"):
            return True
        return False

    def enable(self, requester, preserve_membership):
        """Enable a disabled user.

        Args:
            preserve_membership(bool): whether to remove user from any groups it may be a member of
        Returns:
            None
        """
        # avoid circular dependency
        from grouper.group import get_groups_by_user
        from grouper.models.group import Group

        if not preserve_membership:
            for group, group_edge in get_groups_by_user(self.session, self):
                group_obj = self.session.query(Group).filter_by(
                    groupname=group.name
                ).scalar()
                if group_obj:
                    group_obj.revoke_member(
                        requester, self, "group membership stripped as part of re-enabling account."
                    )

        self.enabled = True
        Counter.incr(self.session, "updates")

    def disable(self):
        self.enabled = False
        Counter.incr(self.session, "updates")

    def add(self, session):
        super(User, self).add(session)
        Counter.incr(session, "updates")
        return self

    @property
    def user_admin(self):
        return self.has_permission(USER_ADMIN)

    @property
    def group_admin(self):
        return self.has_permission(GROUP_ADMIN)

    @property
    def permission_admin(self):
        return self.has_permission(PERMISSION_ADMIN)

    def is_member(self, members):
        return ("User", self.name) in members

    def my_role_index(self, members):
        if self.group_admin:
            return GROUP_EDGE_ROLES.index("owner")
        member = members.get(("User", self.name))
        if not member:
            return None
        return member.role

    def my_role(self, members):
        role_index = self.my_role_index(members)
        if not role_index:
            return None
        else:
            return GROUP_EDGE_ROLES[role_index]

    def set_metadata(self, key, value):
        if not re.match(PERMISSION_VALIDATION, key):
            raise ValueError('Metadata key does not match regex.')

        row = None
        for try_row in self.my_metadata():
            if try_row.data_key == key:
                row = try_row
                break

        if row:
            if value is None:
                row.delete(self.session)
            else:
                row.data_value = value
        else:
            if value is None:
                # Do nothing, a delete on a key that's not set
                return
            else:
                row = UserMetadata(user_id=self.id, data_key=key, data_value=value)
                row.add(self.session)

        Counter.incr(self.session, "updates")
        self.session.commit()

    def my_metadata(self):

        md_items = self.session.query(
            UserMetadata
        ).filter(
            UserMetadata.user_id == self.id
        )

        return md_items.all()

    def my_public_keys(self):

        keys = self.session.query(
            PublicKey.id,
            PublicKey.public_key,
            PublicKey.created_on,
            PublicKey.fingerprint,
            PublicKey.key_size,
            PublicKey.key_type,
        ).filter(
            PublicKey.user_id == self.id
        )

        return keys.all()

    def my_log_entries(self):
        # avoid circular dependency ; ideally this method exists at a higher level of abstraction
        from grouper.models.audit_log import AuditLog

        return AuditLog.get_entries(self.session, involve_user_id=self.id, limit=20)

    def has_permission(self, permission, argument=None):
        """See if this user has a given permission/argument

        This walks a user's permissions (local/direct only) and determines if they have the given
        permission. If an argument is specified, we validate if they have exactly that argument
        or if they have the wildcard ('*') argument.

        Args:
            permission (str): Name of permission to check for.
            argument (str, Optional): Name of argument to check for.

        Returns:
            bool: Whether or not this user fulfills the permission.
        """
        for perm in self.my_permissions():
            if perm.name != permission:
                continue
            if perm.argument == '*' or argument is None:
                return True
            if perm.argument == argument:
                return True
        return False

    def my_permissions(self):
        # avoid circular dependency ; ideally this method exists at a higher level of abstraction
        from grouper.models.group import Group


        # TODO: Make this walk the tree, so we can get a user's entire set of permissions.
        now = datetime.utcnow()
        permissions = self.session.query(
            Permission.name,
            PermissionMap.argument,
            PermissionMap.granted_on,
            Group,
        ).filter(
            PermissionMap.permission_id == Permission.id,
            PermissionMap.group_id == Group.id,
            grouper.models.group.GroupEdge.group_id == Group.id,
            grouper.models.group.GroupEdge.member_pk == self.id,
            grouper.models.group.GroupEdge.member_type == 0,
            grouper.models.group.GroupEdge.active == True,
            self.enabled == True,
            Group.enabled == True,
            or_(
                grouper.models.group.GroupEdge.expiration > now,
                grouper.models.group.GroupEdge.expiration == None
            )
        ).order_by(
            asc("name"), asc("argument"), asc("groupname")
        ).all()

        return permissions

    def my_creatable_permissions(self):
        '''
        Returns a list of permissions this user is allowed to create. Presently, this only counts
        permissions that a user has directly -- in other words, the 'create' permissions are not
        counted as inheritable.

        TODO: consider making these permissions inherited? This requires walking the graph, which
        is expensive.

        Returns a list of strings that are to be interpreted as glob strings. You should use the
        util function matches_glob.
        '''
        if self.permission_admin:
            return '*'

        # Someone can create a permission if they are a member of a group that has a permission
        # of PERMISSION_CREATE with an argument that matches the name of a permission.
        return [
            permission.argument
            for permission in self.my_permissions()
            if permission.name == PERMISSION_CREATE
        ]

    def my_grantable_permissions(self):
        '''
        Returns a list of permissions this user is allowed to grant. Presently, this only counts
        permissions that a user has directly -- in other words, the 'grant' permissions are not
        counted as inheritable.

        TODO: consider making these permissions inherited? This requires walking the graph, which
        is expensive.

        Returns a list of tuples (Permission, argument) that the user is allowed to grant.
        '''
        # avoid circular dependency
        from grouper.permissions import filter_grantable_permissions

        all_permissions = {permission.name: permission
                           for permission in Permission.get_all(self.session)}
        if self.permission_admin:
            result = [(perm, '*') for perm in all_permissions.values()]
            return sorted(result, key=lambda x: x[0].name + x[1])

        # Someone can grant a permission if they are a member of a group that has a permission
        # of PERMISSION_GRANT with an argument that matches the name of a permission.
        grants = [x for x in self.my_permissions() if x.name == PERMISSION_GRANT]
        return filter_grantable_permissions(self.session, grants)

    def my_requests_aggregate(self):
        """Returns all pending requests for this user to approve across groups."""
        # todo(cir_dep): avoid circular dependency ; ideally this method lives
        # at a higher level of abstraction
        from grouper.models.comment import Comment
        from grouper.models.group import Group
        from grouper.models.request import Request

        members = self.session.query(
            label("type", literal(1)),
            label("id", Group.id),
            label("name", Group.groupname),
        ).union(self.session.query(
            label("type", literal(0)),
            label("id", User.id),
            label("name", User.username),
        )).subquery()

        now = datetime.utcnow()
        groups = self.session.query(
            label("id", Group.id),
            label("name", Group.groupname),
        ).filter(
            grouper.models.group.GroupEdge.group_id == Group.id,
            grouper.models.group.GroupEdge.member_pk == self.id,
            grouper.models.group.GroupEdge.active == True,
            grouper.models.group.GroupEdge._role.in_(APPROVER_ROLE_INDICIES),
            self.enabled == True,
            Group.enabled == True,
            or_(
                grouper.models.group.GroupEdge.expiration > now,
                grouper.models.group.GroupEdge.expiration == None,
            )
        ).subquery()

        requests = self.session.query(
            Request.id,
            Request.requested_at,
            grouper.models.group.GroupEdge.expiration,
            label("role", grouper.models.group.GroupEdge._role),
            Request.status,
            label("requester", User.username),
            label("type", members.c.type),
            label("requesting", members.c.name),
            label("reason", Comment.comment),
            label("group_id", groups.c.id),
            label("groupname", groups.c.name),
        ).filter(
            Request.on_behalf_obj_pk == members.c.id,
            Request.on_behalf_obj_type == members.c.type,
            Request.requesting_id == groups.c.id,
            Request.requester_id == User.id,
            Request.status == "pending",
            Request.id == grouper.models.request.RequestStatusChange.request_id,
            grouper.models.request.RequestStatusChange.from_status == None,
            grouper.models.group.GroupEdge.id == Request.edge_id,
            Comment.obj_type == 3,
            Comment.obj_pk == grouper.models.request.RequestStatusChange.id,
        )

        return requests

    def my_open_audits(self):
        # avoid circular dependency ; ideally this method exists at a higher level of abstraction
        from grouper.models.group import Group

        self.session.query(Audit).filter(Audit.complete == False)
        now = datetime.utcnow()
        return self.session.query(
            label("groupname", Group.groupname),
            label("started_at", Audit.started_at),
            label("ends_at", Audit.ends_at),
        ).filter(
            Audit.group_id == Group.id,
            Audit.complete == False,
            grouper.models.group.GroupEdge.group_id == Group.id,
            grouper.models.group.GroupEdge.member_pk == self.id,
            grouper.models.group.GroupEdge.member_type == 0,
            grouper.models.group.GroupEdge.active == True,
            grouper.models.group.GroupEdge._role.in_(OWNER_ROLE_INDICES),
            self.enabled == True,
            Group.enabled == True,
            or_(
                grouper.models.group.GroupEdge.expiration > now,
                grouper.models.group.GroupEdge.expiration == None,
            )
        ).all()
