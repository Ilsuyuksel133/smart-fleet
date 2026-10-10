"""Run one investigation from the command line, e.g. for manual testing:

    python -m agent.cli HighAlertRate
    python -m agent.cli VehicleOverheating --label vehicle_id=2

Prints the RCA report as JSON. Logs (one JSON line per step) go to stderr.
"""

import argparse
import sys

from agent.config import get_settings
from agent.logging_config import setup_logging
from agent.loop import create_investigator
from agent.report import Alert


def parse_labels(pairs: list[str]) -> dict[str, str]:
    labels = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        labels[key] = value
    return labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Investigate one alert and print the report.")
    parser.add_argument("alert_name")
    parser.add_argument("--label", action="append", default=[], help="key=value, repeatable")
    args = parser.parse_args(argv)

    setup_logging()
    alert = Alert(name=args.alert_name, labels=parse_labels(args.label))
    report = create_investigator(get_settings()).investigate(alert)
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
