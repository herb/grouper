from sqlalchemy import Column, Integer, ForeignKey, Enum
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from grouper.models.model_base import Model


AUDIT_STATUS_CHOICES = {"pending", "approved", "remove"}

class AuditMember(Model):
    """An AuditMember is a single instantiation of a user in an audit

    Tracks the status of the member within the audit. I.e., have they been reviewed, should they
    be removed, etc.
    """

    __tablename__ = "audit_members"

    id = Column(Integer, primary_key=True)

    audit_id = Column(Integer, ForeignKey("audits.id"), nullable=False)
    audit = relationship("Audit", backref="members", foreign_keys=[audit_id])

    edge_id = Column(Integer, ForeignKey("group_edges.id"), nullable=False)
    edge = relationship("GroupEdge", backref="audits", foreign_keys=[edge_id])

    status = Column(Enum(*AUDIT_STATUS_CHOICES), default="pending", nullable=False)

    @hybrid_property
    def member(self):
        # prevent the circular dependency ; ideally this method exists at a
        # higher level of abstraction
        from grouper.models.group import Group
        from grouper.models.user import User

        if self.edge.member_type == 0:  # User
            return User.get(self.session, pk=self.edge.member_pk)
        elif self.edge.member_type == 1:  # Group
            return Group.get(self.session, pk=self.edge.member_pk)
        raise Exception("invalid member_type in AuditMember!")
