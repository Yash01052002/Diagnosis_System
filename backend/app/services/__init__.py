"""Business-logic layer.

Deliberately empty of re-exports. Importing the submodules eagerly here would
make ``from app.services.crash_parser import FIELD_ALIASES`` pull in every
service — including ones that import from ``app.schemas`` — which creates an
import cycle the moment a schema needs anything from a service.

Import the submodule you need directly::

    from app.services.crash_parser import CrashParser
    from app.services.symbolication import SymbolicationService
"""
