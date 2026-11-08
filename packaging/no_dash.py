# Runs before the app starts in the packaged build. Open3D imports Dash for its
# browser viewer, which the app never uses, so Dash (and the web server it pulls in)
# is left out of the build and this small stand-in is put in its place.
import sys
import types


class _NotIncluded:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("Dash is not included in the packaged app")


dash = types.ModuleType("dash")
dash.Dash = _NotIncluded
for part in ("html", "dcc"):
    module = types.ModuleType(f"dash.{part}")
    setattr(dash, part, module)
    sys.modules[module.__name__] = module
sys.modules["dash"] = dash
