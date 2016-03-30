# Note: the order of the GROUP_EDGE_ROLES tuple matters! New roles must be
# appended!  When adding a new role, be sure to update the regression test.
GROUP_EDGE_ROLES = (
    "member",    # Belongs to the group. Nothing more.
    "manager",   # Make changes to the group / Approve requests.
    "owner",     # Same as manager plus enable/disable group and make Users owner.
    "np-owner",  # Same as owner but don't inherit permissions.
)
OWNER_ROLE_INDICES = set([GROUP_EDGE_ROLES.index("owner"), GROUP_EDGE_ROLES.index("np-owner")])
APPROVER_ROLE_INDICIES = set([GROUP_EDGE_ROLES.index("owner"), GROUP_EDGE_ROLES.index("np-owner"),
        GROUP_EDGE_ROLES.index("manager")])
