from sqlalchemy.orm import sessionmaker, Session as _Session


class Session(_Session):
    """ Custom session meant to utilize add on the model.

        This Session overrides the add/add_all methods to prevent them
        from being used. This is to for using the add methods on the
        models themselves where overriding is available.
    """

    _add = _Session.add
    _add_all = _Session.add_all
    _delete = _Session.delete

    def add(self, *args, **kwargs):
        raise NotImplementedError("Use add method on models instead.")

    def add_all(self, *args, **kwargs):
        raise NotImplementedError("Use add method on models instead.")

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Use delete method on models instead.")


Session = sessionmaker(class_=Session)
