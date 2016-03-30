from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, asc
from grouper.models.counter import Counter
from grouper.models.model_base import Model


class Permission(Model):
    '''
    Represents permission types. See PermissionEdge for the mapping of which permissions
    exist on a given Group.
    '''

    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True)

    name = Column(String(length=64), unique=True, nullable=False)
    description = Column(Text, nullable=False)
    created_on = Column(DateTime, default=datetime.utcnow, nullable=False)
    _audited = Column('audited', Boolean, default=False, nullable=False)

    @staticmethod
    def get(session, name=None):
        if name is not None:
            return session.query(Permission).filter_by(name=name).scalar()
        return None

    @staticmethod
    def get_all(session):
        return session.query(Permission).order_by(asc("name")).all()

    @property
    def audited(self):
        return self._audited

    def enable_auditing(self):
        self._audited = True
        Counter.incr(self.session, "updates")

    def disable_auditing(self):
        self._audited = False
        Counter.incr(self.session, "updates")

    def get_mapped_groups(self):
        '''
        Return a list of tuples: (Group object, argument).
        '''
        # todo(cir_dep): avoid circular dependency ; ideally this method lives
        # at a higher level of abstraction
        from grouper.models.group import Group
        from grouper.models.permission_map import PermissionMap

        results = self.session.query(
            Group.groupname,
            PermissionMap.argument,
            PermissionMap.granted_on,
        ).filter(
            Group.id == PermissionMap.group_id,
            PermissionMap.permission_id == self.id,
            Group.enabled == True,
        )
        return results.all()

    def my_log_entries(self):
        # avoid circular dependency ; ideally this method exists at a higher level of abstraction
        from grouper.models.audit_log import AuditLog

        return AuditLog.get_entries(self.session, on_permission_id=self.id, limit=20)
