from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import object_session


OBJ_TYPES_IDX = ("User", "Group", "Request", "RequestStatusChange", "PermissionRequestStatusChange")
OBJ_TYPES = {obj_type: idx for idx, obj_type in enumerate(OBJ_TYPES_IDX)}


class Model(object):
    """ Custom model mixin with helper methods. """

    @property
    def session(self):
        return object_session(self)

    @property
    def member_type(self):
        obj_name = type(self).__name__
        if obj_name not in OBJ_TYPES:
            raise ValueError()  # TODO(gary) fill out error
        return OBJ_TYPES[obj_name]

    @classmethod
    def get(cls, session, **kwargs):
        instance = session.query(cls).filter_by(**kwargs).scalar()
        if instance:
            return instance
        return None

    @classmethod
    def get_or_create(cls, session, **kwargs):
        instance = session.query(cls).filter_by(**kwargs).scalar()
        if instance:
            return instance, False

        instance = cls(**kwargs)
        instance.add(session)

        cls.just_created(instance)

        return instance, True

    def just_created(self):
        pass

    def add(self, session):
        session._add(self)
        return self

    def delete(self, session):
        session._delete(self)
        return self


Model = declarative_base(cls=Model)
