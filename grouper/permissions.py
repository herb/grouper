from collections import defaultdict, namedtuple
from datetime import datetime
from fnmatch import fnmatch

from grouper.audit import assert_controllers_are_auditors
from grouper.constants import PERMISSION_ADMIN, PERMISSION_GRANT
from grouper.email_util import send_email
from grouper.fe.settings import settings
from grouper.group import get_groups_by_user
from grouper.models.audit_log import AuditLog
from grouper.models.request_status_change import OBJ_TYPES_IDX
from grouper.plugin import get_plugins
from grouper.util import matches_glob
from grouper.models.group import Group
from grouper.models.counter import Counter
from grouper.models.comment import Comment
from grouper.models.permission import Permission
from grouper.models.permission_request import PermissionRequest
from grouper.models.permission_request_status_change import PermissionRequestStatusChange
from grouper.models.permission_map import PermissionMap


# represents all information we care about for a list of permission requests
Requests = namedtuple('Requests', ['requests', 'status_change_by_request_id',
        'comment_by_status_change_id'])


# represents a permission grant, essentially what come back from User.my_permissions()
# TODO: consider replacing that output with this namedtuple
Grant = namedtuple('Grant', 'name, argument')


def filter_grantable_permissions(session, grants, all_permissions=None):
    """For a given set of PERMISSION_GRANT permissions, return all permissions
    that are grantable.

    Args:
        session (sqlalchemy.orm.session.Session); database session
        grants ([Permission, ...]): PERMISSION_GRANT permissions
        all_permissions ({name: Permission}): all permissions to check against

    Returns:
        list of (Permission, argument) that is grantable by list of grants
        sorted by permission name and argument.
    """

    if all_permissions is None:
        all_permissions = {permission.name: permission for permission in
                Permission.get_all(session)}

    result = []
    for grant in grants:
        assert grant.name == PERMISSION_GRANT

        grantable = grant.argument.split('/', 1)
        if not grantable:
            continue
        for name, permission_obj in all_permissions.iteritems():
            if matches_glob(grantable[0], name):
                result.append((permission_obj,
                               grantable[1] if len(grantable) > 1 else '*', ))

    return sorted(result, key=lambda x: x[0].name + x[1])


def get_owners_by_grantable_permission(session):
    """
    Returns all known permission arguments with owners. This consolidates
    permission grants supported by grouper itself as well as any grants
    governed by plugins.

    Args:
        session(sqlalchemy.orm.session.Session): database session

    Returns:
        A map of permission to argument to owners of the form {permission:
        {argument: [owner1, ...], }, } where 'owners' are models.Group objects.
        And 'argument' can be '*' which means 'anything'.
    """
    all_permissions = {permission.name: permission for permission in Permission.get_all(session)}
    all_groups = session.query(Group).filter(Group.enabled == True).all()

    owners_by_arg_by_perm = defaultdict(lambda: defaultdict(list))
    for group in all_groups:
        group_permissions = session.query(
                Permission.name,
                PermissionMap.argument,
                PermissionMap.granted_on,
                Group,
        ).filter(
                PermissionMap.group_id == Group.id,
                Group.id == group.id,
                Permission.id == PermissionMap.permission_id,
        ).all()

        # special case permission admins
        if any(filter(lambda g: g.name == PERMISSION_ADMIN, group_permissions)):
            for perm_name in all_permissions:
                owners_by_arg_by_perm[perm_name]["*"].append(group)
            continue

        grants = [gp for gp in group_permissions if gp.name == PERMISSION_GRANT]

        for perm, arg in filter_grantable_permissions(session, grants,
                all_permissions=all_permissions):
            owners_by_arg_by_perm[perm.name][arg].append(group)

    # merge in plugin results
    for plugin in get_plugins():
        res = plugin.get_owner_by_arg_by_perm(session) or {}
        for perm, owners_by_arg in res.items():
            for arg, owners in owners_by_arg.items():
                owners_by_arg_by_perm[perm][arg] += owners

    return owners_by_arg_by_perm


def get_grantable_permissions(session, restricted_ownership_permissions):
    """Returns all grantable permissions and their possible arguments. This
    function attempts to reduce a permission's arguments to the least
    permissive possible.

    Args:
        session(sqlalchemy.orm.session.Session): database session
        restricted_ownership_permissions(List[str]): list of permissions for which
            we exclude wildcard ownership from the result if any non-wildcard
            owners exist

    Returns:
        A map of models.Permission object to a list of possible arguments, i.e.
        {models.Permission: [arg1, arg2, ...], ...}
    """
    owners_by_arg_by_perm = get_owners_by_grantable_permission(session)
    args_by_perm = defaultdict(list)
    for permission, owners_by_arg in owners_by_arg_by_perm.items():
        for argument in owners_by_arg:
            args_by_perm[permission].append(argument)

    def _reduce_args(perm_name, args):
        non_wildcard_args = map(lambda a: a != "*", args)
        if (restricted_ownership_permissions and perm_name in restricted_ownership_permissions and
                any(non_wildcard_args)):
            # at least one none wildcard arg so we only return those and we care
            return sorted({a for a in args if a != "*"})
        elif all(non_wildcard_args):
            return sorted(set(args))
        else:
            # it's all wildcard so return that one
            return ["*"]
    return {p: _reduce_args(p, a) for p, a in args_by_perm.items()}


def get_owner_arg_list(session, permission, argument, owners_by_arg_by_perm=None):
    """Return the grouper group(s) responsible for approving a request for the
    given permission + argument along with the actual argument they were
    granted.

    Args:
        session(sqlalchemy.orm.session.Session): database session
        permission(models.Permission): permission in question
        argument(str): argument for the permission
    Returns:
        list of 2-tuple of (group, argument) where group is the models.Group
        grouper groups responsibile for permimssion+argument and argument is
        the argument actually granted to that group. can be empty.
    """
    if owners_by_arg_by_perm is None:
        owners_by_arg_by_perm = get_owners_by_grantable_permission(session)

    all_owner_arg_list = []
    owners_by_arg = owners_by_arg_by_perm[permission.name]
    for arg, owners in owners_by_arg.items():
        if fnmatch(argument, arg):
            all_owner_arg_list += [(owner, arg) for owner in owners]

    return all_owner_arg_list


class PermissionRequestException(Exception):
    pass


class RequestAlreadyExists(PermissionRequestException):
    """Trying to create a request for a permission + argument + group which
    already exists in "pending" state."""


class NoOwnersAvailable(PermissionRequestException):
    """No owner was found for the permission + argument combination."""


class InvalidRequestID(PermissionRequestException):
    """Submitted request ID is invalid (doesn't exist or group doesn't match."""


class RequestAlreadyGranted(PermissionRequestException):
    """Group already has requested permission + argument pair."""


def create_request(session, user, group, permission, argument, reason):
    """
    Creates an permission request and sends notification to the responsible approvers.

    Args:
        session(sqlalchemy.orm.session.Session): database session
        user(models.User): user requesting permission
        group(models.Group): group requested permission would be applied to
        permission(models.Permission): permission in question to request
        argument(str): argument for the given permission
        reason(str): reason the permission should be granted

    Raises:
        RequestAlreadyExists if trying to create a request that is already pending
        NoOwnersAvailable if no owner is available for the requested perm + arg.
    """
    # check if group already has perm + arg pair
    for _, existing_perm_name, _, existing_perm_argument, _ in group.my_permissions():
        if permission.name == existing_perm_name and argument == existing_perm_argument:
            raise RequestAlreadyGranted()

    # check if request already pending for this perm + arg pair
    existing_count = session.query(PermissionRequest).filter(
            PermissionRequest.group_id == group.id,
            PermissionRequest.permission_id == permission.id,
            PermissionRequest.argument == argument,
            PermissionRequest.status == "pending",
            ).count()

    if existing_count > 0:
        raise RequestAlreadyExists()

    # determine owner(s)
    owner_arg_list = get_owner_arg_list(session, permission, argument)

    if not owner_arg_list:
        raise NoOwnersAvailable()

    pending_status = "pending"
    now = datetime.utcnow()

    # multiple steps to create the request
    request = PermissionRequest(
            requester_id=user.id,
            group_id=group.id,
            permission_id=permission.id,
            argument=argument,
            status=pending_status,
            requested_at=now,
            ).add(session)
    session.flush()

    request_status_change = PermissionRequestStatusChange(
            request=request,
            user=user,
            to_status=pending_status,
            change_at=now,
            ).add(session)
    session.flush()

    Comment(
            obj_type=OBJ_TYPES_IDX.index("PermissionRequestStatusChange"),
            obj_pk=request_status_change.id,
            user_id=user.id,
            comment=reason,
            created_on=now,
            ).add(session)

    # send notification
    email_context = {
            "user_name": user.name,
            "group_name": group.name,
            "permission_name": permission.name,
            "argument": argument,
            "reason": reason,
            "request_id": request.id,
            }

    # TODO: would be nicer if it told you which group you're an approver of
    # that's causing this notification

    mail_to = []
    non_wildcard_owners = [(owner, arg) for owner, arg in owner_arg_list if arg != "*"]
    if any(non_wildcard_owners):
        # non-wildcard owners should get all the notifications
        mailto_owner_arg_list = non_wildcard_owners
    else:
        # only the wildcards so they get the notifications
        mailto_owner_arg_list = owner_arg_list

    for owner, arg in mailto_owner_arg_list:
        mail_to += [u for t, u in owner.my_members() if t == 'User']
    send_email(session, set(mail_to), "Request for permission: {}".format(permission.name),
            "pending_permission_request", settings, email_context)


def get_pending_request_by_group(session, group):
    """Load pending request for a particular group.

    Args:
        session(sqlalchemy.orm.session.Session): database session
        group(models.Group): group in question

    Returns:
        list of models.PermissionRequest correspodning to open/pending requests
        for this group.
    """
    return session.query(PermissionRequest).filter(
            PermissionRequest.status == "pending",
            PermissionRequest.group_id == group.id,
            ).all()


def get_requests_by_owner(session, owner, status, limit, offset):
    """Load pending requests for a particular owner.

    Args:
        session(sqlalchemy.orm.session.Session): database session
        owner(models.User): model of user in question
        status(REQUEST_STATUS_CHOICES): if not None, filter by particular status
        limit(int): how many results to return
        offset(int): the offset into the result set that should be applied

    Returns:
        2-tuple of (Requests, total) where total is total result size and
        Requests is the namedtuple with requests and associated
        comments/changes.
    """
    # get owners groups
    group_ids = {g.id for g, _ in get_groups_by_user(session, owner)}

    # get all requests
    all_requests = session.query(PermissionRequest)
    if status:
        all_requests = all_requests.filter(PermissionRequest.status == status)

    all_requests = all_requests.order_by(PermissionRequest.requested_at.desc()).all()

    owners_by_arg_by_perm = get_owners_by_grantable_permission(session)

    requests = []
    for request in all_requests:
        owner_arg_list = get_owner_arg_list(session, request.permission, request.argument,
                owners_by_arg_by_perm)
        if group_ids.intersection([o.id for o, arg in owner_arg_list]):
            requests.append(request)

    total = len(requests)
    requests = requests[offset:limit]

    status_change_by_request_id = defaultdict(list)
    if not requests:
        comment_by_status_change_id = {}
    else:
        status_changes = session.query(PermissionRequestStatusChange).filter(
                    PermissionRequestStatusChange.request_id.in_([r.id for r in requests]),
                    ).all()
        for sc in status_changes:
            status_change_by_request_id[sc.request_id].append(sc)

        comments = session.query(Comment).filter(
                Comment.obj_type == OBJ_TYPES_IDX.index("PermissionRequestStatusChange"),
                Comment.obj_pk.in_([s.id for s in status_changes]),
                ).all()
        comment_by_status_change_id = {c.obj_pk: c for c in comments}

    return Requests(requests, status_change_by_request_id, comment_by_status_change_id), total


def get_request_by_id(session, request_id):
    """Get a single request by the request ID.

    Args:
        session(sqlalchemy.orm.session.Session): database session
        request_id(int): id of request in question

    Returns:
        model.PermissionRequest object or None if no request by that ID.
    """
    return session.query(PermissionRequest).filter(PermissionRequest.id == request_id).one()


def update_request(session, request, user, new_status, comment):
    """Update a request.

    Args:
        session(sqlalchemy.orm.session.Session): database session
        request(models.PermissionRequest): request to update
        user(models.User): user making update
        new_status(REQUEST_STATUS_CHOICES): new status
        comment(str): comment to include with status change

    Raises:
        grouper.audit.UserNotAuditor in case we're trying to add an audited
            permission to a group without auditors
    """
    if request.status == new_status:
        # nothing to do
        return

    # make sure the grant can happen
    if new_status == "actioned":
        if request.permission.audited:
            # will raise UserNotAuditor if no auditors are owners of the group
            assert_controllers_are_auditors(request.group)

    # all rows we add have the same timestamp
    now = datetime.utcnow()

    # new status change row
    permission_status_change = PermissionRequestStatusChange(
            request=request,
            user_id=user.id,
            from_status=request.status,
            to_status=new_status,
            change_at=now,
            ).add(session)
    session.flush()

    # new comment
    Comment(
            obj_type=OBJ_TYPES_IDX.index("PermissionRequestStatusChange"),
            obj_pk=permission_status_change.id,
            user_id=user.id,
            comment=comment,
            created_on=now,
            ).add(session)

    # update permissionRequest status
    request.status = new_status
    session.flush()

    if new_status == "actioned":
        # actually grant permission
        request.group.grant_permission(request.permission, request.argument)
        Counter.incr(session, "updates")

    # audit log
    AuditLog.log(session, user.id, "update_perm_request",
            "updated permission request to status: {}".format(new_status),
            on_group_id=request.group_id, on_user_id=request.requester_id)

    # send notification
    if new_status == "actioned":
        subject = "Request for Permission Actioned"
        email_template = "permission_request_actioned"
    else:
        subject = "Request for Permission Cancelled"
        email_template = "permission_request_cancelled"

    email_context = {
            'group_name': request.group.name,
            'action_taken_by': user.name,
            'reason': comment,
            'permission_name': request.permission.name,
            'argument': request.argument,
            }

    send_email(session, [request.requester.name], subject, email_template,
            settings, email_context)
