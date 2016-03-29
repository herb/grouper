from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from grouper.models.counter import Counter
from grouper.models.model_base import Model
from grouper.models.user import User


class PublicKey(Model):

    __tablename__ = "public_keys"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship(User, foreign_keys=[user_id])

    key_type = Column(String(length=32))
    key_size = Column(Integer)
    public_key = Column(Text, nullable=False, unique=True)
    fingerprint = Column(String(length=64), nullable=False)
    created_on = Column(DateTime, default=datetime.utcnow, nullable=False)

    def add(self, session):
        super(PublicKey, self).add(session)
        Counter.incr(session, "updates")
        return self

    def delete(self, session):
        super(PublicKey, self).delete(session)
        Counter.incr(session, "updates")
        return self
