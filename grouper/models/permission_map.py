from datetime import datetime
from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from grouper.models.counter import Counter
from grouper.models.group import Group
from grouper.models.model_base import Model
from grouper.models.permission import Permission


MappedPermission = namedtuple('MappedPermission',
                              ['permission', 'audited', 'argument', 'groupname', 'granted_on'])


class PermissionMap(Model):
    '''
    Maps a relationship between a Permission and a Group. Note that a single permission can be
    mapped into a given group multiple times, as long as the argument is unique.

    These include the optional arguments, which can either be a string, an asterisks ("*"), or
    Null to indicate no argument.
    '''

    __tablename__ = "permissions_map"
    __table_args__ = (
        UniqueConstraint('permission_id', 'group_id', 'argument', name='uidx1'),
    )

    id = Column(Integer, primary_key=True)

    permission_id = Column(Integer, ForeignKey("permissions.id"), nullable=False)
    permission = relationship(Permission, foreign_keys=[permission_id])

    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    group = relationship(Group, foreign_keys=[group_id])

    argument = Column(String(length=64), nullable=True)
    granted_on = Column(DateTime, default=datetime.utcnow, nullable=False)

    @staticmethod
    def get(session, id=None):
        if id is not None:
            return session.query(PermissionMap).filter_by(id=id).scalar()
        return None

    def add(self, session):
        super(PermissionMap, self).add(session)
        Counter.incr(session, "updates")
        return self

    def delete(self, session):
        super(PermissionMap, self).delete(session)
        Counter.incr(session, "updates")
        return self
