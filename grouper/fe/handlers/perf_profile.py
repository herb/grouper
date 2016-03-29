from tornado.web import RequestHandler
from grouper import perf_profile, session


# Don't use GraphHandler here as we don't want to count
# these as requests.
class PerfProfile(RequestHandler):
    def get(self, trace_uuid):
        from grouper.models_old import Session
        try:
            flamegraph_svg = perf_profile.get_flamegraph_svg(session.Session(), trace_uuid)
        except perf_profile.InvalidUUID:
            pass
        else:
            self.set_header("Content-Type", "image/svg+xml")
            self.write(flamegraph_svg)
