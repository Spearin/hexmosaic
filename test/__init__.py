"""Test package bootstrap helpers."""

# Import qgis so tests that rely on the bindings can set up the SIP API.  The
# dependency is optional for environments (like CI or local dev shells) that
# run a subset of tests without a full QGIS installation; simply ignore the
# import error in that case so modules can call ``pytest.importorskip("qgis")``
# and skip cleanly.
try:  # pragma: no cover - exercised indirectly in tests
    import qgis  # pylint: disable=unused-import  # type: ignore # NOQA
except ModuleNotFoundError:  # pragma: no cover - skip when QGIS absent
    qgis = None  # type: ignore