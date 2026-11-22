"""Fail closed on structural, freshness, or published-vintage regressions."""
import json
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def previous(path):
    return json.loads(subprocess.check_output(['git','show','HEAD:'+path],cwd=ROOT))

def validate(old_dashboard, dashboard, old_forecasts, forecasts, quality):
    errors=[]
    old={r['id']:r for r in old_dashboard['indicators']}
    new={r['id']:r for r in dashboard['indicators']}
    if old.keys()!=new.keys():errors.append('Indicator coverage changed')
    for key, row in old.items():
        current=new.get(key,{})
        if current.get('updatedAt','')<row['updatedAt']:errors.append(f'Observation date regressed: {key}')
        if current.get('unit')!=row['unit']:errors.append(f'Unit changed: {key}')
        old_warnings={x['code'] for x in row.get('dataQuality',[]) if x.get('status')=='warning'}
        warnings={x['code'] for x in current.get('dataQuality',[]) if x.get('status')=='warning'}
        if warnings-old_warnings:errors.append(f'New source validation warning: {key}')
    if quality.get('errors') or quality['summary'].get('provider_code_collisions'):
        errors.append('Source structural validation failed')
    for key, rows in old_forecasts['history'].items():
        new_rows={r['date']:r for r in forecasts['history'].get(key,[])}
        for prior in rows:
            current=new_rows.get(prior['date'])
            if current is None:
                errors.append(f'Historical row lost: {key} {prior["date"]}')
            elif current.get('actual') is not None and prior.get('forecast') is not None and current.get('forecast')!=prior['forecast']:
                errors.append(f'Published forecast changed: {key} {prior["date"]}')
    return errors

def main():
    read=lambda p:json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
    errors=validate(previous('public/data/dashboard.json'),read('public/data/dashboard.json'),previous('public/data/forecasts.json'),read('public/data/forecasts.json'),read('outputs/data-quality-report.json'))
    cache=Path(os.environ.get('MACRO_DATA_CACHE_DIR','data_cache'))
    budget_path=cache/'cloud-run-budget.json'
    budget=json.loads(budget_path.read_text()) if budget_path.exists() else {}
    run_id=os.environ.get('GITHUB_RUN_ID','')+':'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
    if budget.get('runId')==run_id and budget.get('blocked'):
        errors.append('Request budget interrupted refresh; resume using the saved cache before publishing')
    exclusions={}
    for path in (cache/'requests'/'exact').glob('*.json'):
        try:
            entry=json.loads(path.read_text())
            data=json.loads(entry['response']['data']['result']['content'][0]['text'])['data']
            excluded=data.get('excludedObservations')
            if excluded: exclusions[json.dumps(excluded,sort_keys=True)]=excluded
        except (ValueError,KeyError,TypeError,IndexError): continue
    report={'passed':not errors,'errors':errors,'productionWrites':False,
            'providerDateExclusions':list(exclusions.values())}
    (ROOT/'outputs/cloud-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    if errors:raise SystemExit(1)
if __name__=='__main__':main()
