"""Summarize local API attempts and cache savings, not provider billing credits."""
import argparse
import json
from collections import Counter, defaultdict
from ifind_request_cache import root, today

parser=argparse.ArgumentParser()
parser.add_argument('--date',default=today())
args=parser.parse_args()
totals=Counter();consumers=defaultdict(Counter)
path=root()/'usage.jsonl'
if path.exists():
    for line in path.read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['time'].startswith(args.date):
            totals[row['event']]+=1
            consumers[row['consumer']][row['event']]+=1
print(json.dumps({'date':args.date,'counts':totals,'consumers':consumers,
                  'note':'本地网络请求及缓存事件，不代表供应商实际扣费点数'},ensure_ascii=False,indent=2))
