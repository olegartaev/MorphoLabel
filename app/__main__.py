from __future__ import annotations
import argparse
from .version import __version__
def main(argv=None):
    parser = argparse.ArgumentParser(prog="MorphoLabel", add_help=True)
    parser.add_argument("--version", action="store_true", help="print MorphoLabel version and exit")
    parser.add_argument("--self-test", action="store_true", help="verify installed core runtime and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.self_test:
        from .self_test import print_self_test
        print_self_test()
        return 0
    from .ui.shell import run
    run()
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
