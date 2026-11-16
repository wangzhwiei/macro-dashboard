"""Atomic generated-data commit; refuse concurrent source changes or secrets."""
import base64
import json
import os
import subprocess
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
def main():
    if json.loads((ROOT/'config/cloud-admin.json').read_text()).get('phase')!='production':
        raise RuntimeError('Production cutover gate is not open')
    session=requests.Session()
    session.headers.update({'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
    api='https://api.github.com/repos/wangzhwiei/macro-dashboard'
    def request(method,path,**kwargs):
        response=session.request(method,api+path,timeout=60,**kwargs)
        response.raise_for_status()
        return response.json()
    baseline=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    remote=request('GET','/git/ref/heads/main')['object']['sha']
    if baseline!=remote:raise RuntimeError('Production source changed during refresh; refusing to overwrite')
    paths=subprocess.check_output(['git','diff','--name-only'],cwd=ROOT,text=True).splitlines()
    entries=[]
    for name in paths:
        if not(name.startswith('data/') or name in ('public/data/dashboard.json','public/data/forecasts.json','outputs/data-quality-report.json','outputs/frequency-freshness-audit.csv')):continue
        path=ROOT/name
        if not path.is_file():raise RuntimeError('Generated file unexpectedly removed')
        raw=path.read_bytes()
        for secret in ('GH_TOKEN','IFIND_AUTH_TOKEN'):
            token=os.environ.get(secret,'')
            if token and token.encode() in raw:raise RuntimeError('Credential found in generated output')
        blob=request('POST','/git/blobs',json={'content':base64.b64encode(raw).decode(),'encoding':'base64'})
        entries.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
    if not entries:
        print('No generated changes to persist');return
    base=request('GET','/git/commits/'+baseline)
    tree=request('POST','/git/trees',json={'base_tree':base['tree']['sha'],'tree':entries})
    commit=request('POST','/git/commits',json={'message':'data: verified cloud incremental refresh','tree':tree['sha'],'parents':[baseline]})
    request('PATCH','/git/refs/heads/main',json={'sha':commit['sha'],'force':False})
    print('Persisted verified generated data: '+commit['sha'])
if __name__=='__main__':main()
