"""Scheduling is disabled unless production cutover is explicitly complete."""
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

def should_run(config, event, hour):
    if config.get('phase')!='production':return False
    if event=='workflow_dispatch':return True
    schedule=config['schedule']
    return event=='schedule' and schedule['enabled'] is True and hour==schedule['hourShanghai']

if __name__=='__main__':
    config=json.loads(Path('config/cloud-admin.json').read_text())
    enabled=should_run(config,os.environ['GITHUB_EVENT_NAME'],datetime.now(ZoneInfo('Asia/Shanghai')).hour)
    with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write(f'run={str(enabled).lower()}\n')
    print('Cloud refresh allowed' if enabled else 'Cloud refresh skipped: staging, schedule disabled, or outside selected hour')
