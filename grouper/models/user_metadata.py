from datetime import datetime
from sqlalchemy import Column, Integer, String, UniqueConstraint, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from grouper.models.counter import Counter
from grouper.models.model_base import Model
from grouper.models.user import User


class UserMetadata(Model):

    __tablename__ = "user_metadata"
    __table_args__ = (
        UniqueConstraint('user_id', 'data_key', name='uidx1'),
    )

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship(User, foreign_keys=[user_id])

    data_key = Column(String(length=64), nullable=False)
    data_value = Column(String(length=64), nullable=False)
    last_modified = Column(DateTime, default=datetime.utcnow, nullable=False)

    def add(self, session):
        super(UserMetadata, self).add(session)
        Counter.incr(session, "updates")
        return self

    def delete(self, session):
        super(UserMetadata, self).delete(session)
        Counter.incr(session, "updates")
        return self
