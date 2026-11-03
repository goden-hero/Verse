#!/usr/bin/env python3
"""Real Chromium layout checks with fixture APIs. This is not an Android device test."""
import json
import os
from pathlib import Path
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage")
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

WEB = Path(__file__).resolve().parents[3] / "app/web"
html = (WEB / "index.html").read_text()
html = re.sub(r'<link[^>]+(?:fonts\.googleapis|fonts\.gstatic)[^>]*>', '', html)
for name in ("index.css", "mobile-shell.css"):
    html = re.sub(r'<link rel="stylesheet" href="' + re.escape(name) + r'[^\"]*">',
                  lambda _, name=name: '<style>' + (WEB / name).read_text() + '</style>', html)
fixture = r'''
window.fixtureAuthenticated = false;
const answer=(data,status=200)=>({ok:status===200,status,json:async()=>data});
const person={id:1,username:'fixture',display_name:'Fixture'};
window.fetch=async (url,options={})=>{
  const path=String(url).split('?')[0];
  if(path.endsWith('/auth/me'))return answer(window.fixtureAuthenticated?person:{detail:'Login required'},window.fixtureAuthenticated?200:401);
  if(path.endsWith('/auth/first-run'))return answer({first_run:false});
  if(path.endsWith('/auth/login')){window.fixtureAuthenticated=true;return answer({user:person});}
  if(path.endsWith('/songs'))return answer({songs:[],total_count:0,page:1,page_size:100});
  return answer([]);
};
'''
for name in ("index.js", "catalogue.js"):
    content = (fixture if name == "index.js" else "") + (WEB / name).read_text()
    html = re.sub(r'<script src="' + re.escape(name) + r'[^\"]*"></script>',
                  lambda _, content=content: '<script>' + content + '</script>', html)

checks = r'''
(async()=>{
  const check=(condition,message)=>{if(!condition)throw Error(message);};
  const wait=async condition=>{for(let i=0;i<300;i++){if(condition())return;await new Promise(r=>setTimeout(r,10));}throw Error('UI timeout');};
  const el=id=>document.getElementById(id);
  const inViewport=node=>{const r=node.getBoundingClientRect();return r.top>=-1&&r.bottom<=innerHeight+1&&r.left>=-1&&r.right<=innerWidth+1;};
  await wait(()=>el('login-form').style.display!=='none');
  check(document.documentElement.scrollWidth<=innerWidth,'Login horizontal overflow');
  el('btn-show-register').click();
  const shell=el('auth-shell');
  shell.scrollTop=0;
  check(el('register-display-name').getBoundingClientRect().top>=0,'Top of registration form unreachable');
  el('btn-register').scrollIntoView({block:'nearest'});
  check(inViewport(el('btn-register')),'Registration button unreachable at keyboard height');
  el('btn-show-login').click();
  el('login-username').value='fixture';el('login-password').value='fixture-only';
  el('login-form').requestSubmit();
  await wait(()=>currentState.auth.authenticated);
  if(innerWidth<768){
    document.documentElement.style.setProperty('--safe-top','24px');
    document.documentElement.style.setProperty('--safe-bottom','24px');
    const nav=document.querySelector('.mobile-bottom-nav'),mini=el('mobile-mini-player');
    check(nav.getBoundingClientRect().height>=84,'Bottom safe area not included');
    check(mini.getBoundingClientRect().bottom<=nav.getBoundingClientRect().top+1,'Mini player overlaps bottom navigation');
    check(document.querySelector('.mobile-header').getBoundingClientRect().height>=80,'Header safe area not included');
    showSearchOverlay();
    await new Promise(r=>setTimeout(r,50));
    check(inViewport(el('catalogue-search-input')),'Search input outside keyboard-sized viewport');
    check(el('catalogue-search-overlay').getBoundingClientRect().height<=innerHeight+1,'Search overlay exceeds resized viewport');
    hideSearchOverlay();
  }
  window.mobileResult={passed:true,width:innerWidth,height:innerHeight,checks:['login/register reachability','fixture login','horizontal overflow','safe-area header/nav/player','search at resized viewport']};
})().catch(error=>window.mobileResult={passed:false,width:innerWidth,height:innerHeight,error:String(error)});
'''


class BlockNetwork(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        if info.requestUrl().scheme() in ("http", "https"):
            info.block(True)


application = QApplication([])
view = QWebEngineView()
blocker = BlockNetwork()
view.page().profile().setUrlRequestInterceptor(blocker)
sizes = [(390, 844), (390, 420), (844, 390), (320, 568)]
results = []


def load_next():
    if len(results) == len(sizes):
        application.quit()
        return
    view.resize(*sizes[len(results)])
    view.setHtml(html, QUrl.fromLocalFile(str(WEB) + "/"))


def received(value):
    if not value:
        QTimer.singleShot(50, poll)
        return
    result = json.loads(value)
    results.append(result)
    print(json.dumps(result), flush=True)
    if result.get("passed"):
        load_next()
    else:
        application.quit()


def poll():
    view.page().runJavaScript("window.mobileResult ? JSON.stringify(window.mobileResult) : null", received)


def loaded(ok):
    if not ok:
        application.quit()
        return
    view.page().runJavaScript(checks)
    QTimer.singleShot(50, poll)


view.loadFinished.connect(loaded)
QTimer.singleShot(30000, application.quit)
load_next()
view.show()
application.exec()
assert len(results) == len(sizes) and all(r.get("passed") for r in results), results
