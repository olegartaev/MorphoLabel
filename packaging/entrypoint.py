from app.__main__ import main
import sys

try:
    exit_code = main()
except Exception:
    # The diagnostic command writes its failure JSON before raising. In a
    # windowed build an uncaught exception opens PyInstaller's modal error
    # window, leaving automated checks waiting for a person to close it.
    # Keep normal GUI exception reporting and the source CLI contract intact.
    if "--ai-self-test" in sys.argv and any(
        arg == "--diagnostic-report" or arg.startswith("--diagnostic-report=")
        for arg in sys.argv
    ):
        raise SystemExit(1)
    raise
raise SystemExit(exit_code)
