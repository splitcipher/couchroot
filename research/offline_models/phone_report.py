"""Static phone-sized projection of an exported redacted survey report.

No credentials, transport, pairing, live health claims, commands or installation.
"""
from datetime import date
from html import escape
from tvsetup.common import Refused
from tvsetup.device_report import MILESTONES, MODEL_RE, PLATFORM_RE


def render(document):
    if not isinstance(document,dict) or document.get('schema')!=1:raise Refused('Exported report schema 1 required')
    collected=document.get('date')
    try:
        if not isinstance(collected,str) or date.fromisoformat(collected).isoformat()!=collected:raise ValueError()
    except ValueError:raise Refused('Export date required') from None
    target=document.get('target');milestones=document.get('milestones')
    if not isinstance(target,dict) or not isinstance(milestones,dict):raise Refused('Invalid exported report')
    def safe(key,pattern):
        value=target.get(key)
        return value if isinstance(value,str) and pattern.fullmatch(value) else 'Not established'
    values=[('Export date',collected),('Model',safe('model',MODEL_RE)),('Platform',safe('platform',PLATFORM_RE))]
    # Arbitrary evidence, URLs, logs, credentials and even free-form firmware text
    # are deliberately excluded. This is not a redactor for raw private journals.
    for name in MILESTONES:
        row=milestones.get(name,{})
        result=row.get('result') if isinstance(row,dict) else None
        if result not in ('not tested','read-only observation','owner-authorized change'):result='not tested'
        values.append((name.replace('_',' ').capitalize(),result))
    rows=''.join('<dt>'+escape(key)+'</dt><dd>'+escape(value)+'</dd>' for key,value in values)
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Exported TV report</title><style>
body{font:18px/1.5 system-ui,sans-serif;background:#101722;color:#edf2fa;margin:0;padding:24px}
main{max-width:640px;margin:auto}h1{font-size:28px}dt{margin-top:18px;color:#b9c9df}dd{margin:0;overflow-wrap:anywhere}.notice{border-left:3px solid #90b9ec;padding-left:16px}
</style><main><h1>Exported TV report</h1><p class="notice">Offline snapshot. This page cannot contact a TV or show current health. It contains no controls or credentials.</p><dl>'''+rows+'''</dl><p>Recorded milestones describe the evidence category, not successful acceptance. Firmware support, playback and unattended boot require their own evidence. Use the original redacted report for context.</p></main></html>'''
