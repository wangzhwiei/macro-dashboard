"""Keep published forecasts immutable once an actual is available."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def preserve(previous, current):
    count = 0
    for key, rows in current.get('history', {}).items():
        old = {r['date']: r for r in previous.get('history', {}).get(key, [])}
        for row in rows:
            prior = old.get(row['date'], {})
            if row.get('actual') is None or prior.get('forecast') is None:
                continue
            count += row.get('forecast') != prior['forecast']
            row['forecast'] = prior['forecast']
            row['officialRounding'] = prior.get('officialRounding')
            if prior.get('actual') is not None or prior.get('forecastKind') == 'retrospective_reconstruction':
                row['forecastKind'] = prior.get('forecastKind')
            else:
                row['forecastKind'] = 'confirmed_nowcast'
    return count

def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--published', type=Path)
    group.add_argument('--published-revision')
    parser.add_argument('--output', type=Path, default=ROOT/'public/data/forecasts.json')
    args = parser.parse_args()
    previous = json.loads(args.published.read_text(encoding='utf-8-sig')) if args.published else json.loads(subprocess.check_output(['git','show',args.published_revision+':public/data/forecasts.json'],cwd=ROOT))
    current = json.loads(args.output.read_text(encoding='utf-8-sig'))
    count = preserve(previous, current)
    args.output.write_text(json.dumps(current, ensure_ascii=False, separators=(',',':')),encoding='utf8')
    print(f'Preserved previously published forecasts: {count} numeric changes prevented')

if __name__ == '__main__':
    main()
