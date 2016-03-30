import logging

from grouper import public_key
from grouper.ctl.util import ensure_valid_username, make_session
from grouper.models.audit_log import AuditLog
from grouper.models.user import User


@ensure_valid_username
def user_command(args):
    session = make_session()

    if args.subcommand == "create":
        for username in args.username:
            user = User.get(session, name=username)
            if not user:
                logging.info("{}: No such user, creating...".format(username))
                user = User.get_or_create(session, username=username, role_user=args.role_user)
                session.commit()
            else:
                logging.info("{}: Already exists. Doing nothing.".format(username))

        return

    # "add_public_key" and "set_metadata"
    user = User.get(session, name=args.username)
    if not user:
        logging.error("{}: No such user. Doing nothing.".format(args.username))
        return

    # User must exist at this point.

    if args.subcommand == "set_metadata":
        print "Setting %s metadata: %s=%s" % (args.username, args.metadata_key, args.metadata_value)
        if args.metadata_value == "":
            args.metadata_value = None
        user.set_metadata(args.metadata_key, args.metadata_value)
        session.commit()
    elif args.subcommand == "add_public_key":
        print "Adding public key for user..."

        try:
            pubkey = public_key.add_public_key(session, user, args.public_key)
        except public_key.DuplicateKey:
            print "Key already in use."
            return
        except public_key.PublicKeyParseError:
            print "Public key appears to be invalid."
            return

        AuditLog.log(session, user.id, 'add_public_key',
                '(Administrative) Added public key: {}'.format(pubkey.fingerprint),
                on_user_id=user.id)


def add_parser(subparsers):
    user_parser = subparsers.add_parser(
        "user", help="Edit user")
    user_parser.set_defaults(func=user_command)
    user_subparser = user_parser.add_subparsers(dest="subcommand")

    user_create_parser = user_subparser.add_parser(
        "create", help="Create a new user account")
    user_create_parser.add_argument("username", nargs="+")
    user_create_parser.add_argument("--role-user", default=False, action="store_true",
                                    help="If given, identifies user as a role user.")

    user_key_parser = user_subparser.add_parser(
        "add_public_key", help="Add public key to user")
    user_key_parser.add_argument("username")
    user_key_parser.add_argument("public_key")

    user_set_metadata_parser = user_subparser.add_parser(
        "set_metadata", help="Set metadata on user")
    user_set_metadata_parser.add_argument("username")
    user_set_metadata_parser.add_argument("metadata_key")
    user_set_metadata_parser.add_argument("metadata_value")
