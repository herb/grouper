import code
from pprint import pprint

from grouper import models_old
from grouper.ctl.util import make_session
from grouper.graph import GroupGraph


def shell_command(args):
    session = make_session()
    graph = GroupGraph.from_db(session)
    m = models_old
    pp = pprint

    try:
        from IPython import embed
    except ImportError:
        code.interact(local={
            "session": session,
            "graph": graph,
            "m": m,
            "models_old": models_old,
            "pp": pp,
        })
    else:
        embed()


def add_parser(subparsers):
    shell_parser = subparsers.add_parser(
        "shell", help="Launch a shell with models_old imported.")
    shell_parser.set_defaults(func=shell_command)
