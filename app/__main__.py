from __future__ import annotations

import argparse
import json
from pathlib import Path

from .version import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(prog="MorphoLabel", add_help=True)
    parser.add_argument("--version", action="store_true", help="print MorphoLabel version and exit")
    parser.add_argument("--self-test", action="store_true", help="verify installed core runtime and exit")
    parser.add_argument("--install-ai", action="store_true", help="download, verify and install the published managed AI component")
    parser.add_argument("--ai-self-test", action="store_true", help="verify the managed AI runtime and run one RTMPose prediction")
    parser.add_argument("--require-cuda", action="store_true", help="require CUDA during --ai-self-test")
    parser.add_argument("--include-training", action="store_true", help="also run a disposable one-epoch RTMPose training smoke")
    parser.add_argument("--diagnostic-report", help="write AI self-test PASS/FAIL JSON to this file")
    args = parser.parse_args(argv)
    if args.require_cuda and not args.ai_self_test:
        parser.error("--require-cuda is only valid with --ai-self-test")
    if args.include_training and not args.ai_self_test:
        parser.error("--include-training is only valid with --ai-self-test")
    if args.diagnostic_report and not args.ai_self_test:
        parser.error("--diagnostic-report is only valid with --ai-self-test")
    if args.version:
        print(__version__)
        return 0
    if args.self_test:
        from .self_test import print_self_test
        print_self_test()
        return 0
    if args.install_ai:
        from .ai_delivery import install_published_ai_component
        runtime = install_published_ai_component(progress=lambda stage, detail: print(f"{stage}: {detail}"))
        print(runtime)
        return 0
    if args.ai_self_test:
        from .self_test import run_ai_self_test
        report_path = Path(args.diagnostic_report).expanduser() if args.diagnostic_report else None
        try:
            result = run_ai_self_test(
                require_cuda=args.require_cuda,
                include_training=args.include_training,
                progress=lambda stage, detail: print(f"{stage}: {detail}"),
            )
            if report_path:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            else:
                print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        except Exception as exc:
            if report_path:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps({
                    "status": "FAIL",
                    "version": __version__,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }, indent=2, sort_keys=True), encoding="utf-8")
            raise
    from .ui.shell import run
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
