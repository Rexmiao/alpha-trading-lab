"""CLI: python run.py collect | experiment | all. Only market-data requests."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='Local daily-equity alpha research; no real orders.')
    parser.add_argument('command', choices=['collect', 'experiment', 'all', 'rank'])
    args = parser.parse_args()
    if args.command == 'rank':
        from research.rank_experiment import main as rank_main
        return rank_main([])
    if args.command in ('collect', 'all'):
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'collect-moomoo.mjs')], cwd=ROOT)
        if result.returncode and args.command == 'collect':
            from research.pipeline import write_unavailable
            write_unavailable(ROOT, 'moomoo history collection unavailable; open the desktop client and enable its local API.')
            return result.returncode
    if args.command in ('experiment', 'all'):
        from research.pipeline import run_experiment
        return run_experiment(ROOT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
