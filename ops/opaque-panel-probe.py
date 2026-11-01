"""Real in-shell pixel guard. Run via browser_exec, not as a fake fixture.

Load with runpy.run_path; call probe(app_eval, cdp). The caller supplies the
real Project Chats iframe evaluator and browser CDP, then saves returned JSON.
The loud sibling is above ordinary content, below the native dialog top layer.
"""
import base64
import io
import time
from PIL import Image, ImageChops

def probe(evaluate, cdp):
    evaluate("(()=>{const old=d.getElementById('opaque-panel-qa');if(old)old.remove();const e=d.createElement('div');e.id='opaque-panel-qa';e.setAttribute('aria-hidden','true');e.style.cssText='position:fixed;inset:0;z-index:2147483647;pointer-events:none;background:#000;color:#fff;font:900 40px monospace;overflow:hidden';e.textContent='LOUD TEXT BEHIND THE ACTUAL PANEL '.repeat(200);d.body.append(e);d.querySelector('#options').showModal();return true})()")
    def snap():
        time.sleep(.25)
        data=cdp('Page.captureScreenshot',format='png')['data']
        return Image.open(io.BytesIO(base64.b64decode(data))).convert('RGB')
    a=snap()
    box=evaluate("(()=>{const r=d.querySelector('#options').getBoundingClientRect(),f=d.defaultView.frameElement.getBoundingClientRect();return [r.left+f.left+12,r.top+f.top+12,r.right+f.left-12,r.bottom+f.top-12]})()")
    evaluate("(()=>{const e=d.getElementById('opaque-panel-qa');e.style.background='#ff00ff';e.style.color='#00ff00';return true})()")
    b=snap();region=tuple(map(round,box));diff=ImageChops.difference(a.crop(region),b.crop(region))
    histogram=diff.convert('L').histogram();changed=sum(histogram[1:])
    result={'changed_interior_pixels':changed,'interior_pixels':diff.width*diff.height,'passed':changed==0,'bounds':region,'background':evaluate("w.getComputedStyle(d.querySelector('#options')).backgroundColor"),'hosted':evaluate('w.WizardApp.hosted')}
    evaluate("(()=>{d.getElementById('opaque-panel-qa').remove();d.querySelector('#options').close();return true})()")
    return result
