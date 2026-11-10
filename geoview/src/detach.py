"Tabs in separate browser windows."
import time

from trame.widgets import client

from .config import state, ctrl

state.windows = {}
state.detachedTabs = []

DETACH_JS = r"""
window.gv = (() => {
  const me = (location.search.match(/[?&]win=(\w+)/) || [])[1] || 'main';
  const TYPE = 'application/x-geoview-tab';
  const ch = new BroadcastChannel('geoview-tabs');
  const send = m => ch.postMessage(m);
  const trigger = (...a) => window.trame.trigger(...a);
  const ours = e => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes(TYPE);
  const myTabs = () => ((window.trame.state.get('windows') || {})[me] || {}).tabs || [];

  const open = tab => {
    if (me !== 'main' && myTabs().length <= 1) return;
    const id = Math.random().toString(36).slice(2, 10);
    trigger('win_open', [id, tab]);
    window.open('?win=' + id, 'geoview_' + id, 'popup,width=1200,height=800');
  };

  let registered = false;
  if (me === 'main') {
    let alive = null;
    ch.onmessage = ({ data }) => {
      if (data.alive && alive) alive.push(data.alive);
      if (data.bye) trigger('win_close', [data.bye]);
    };
    const call = () => { alive = []; send({ who: 1 }); setTimeout(() => trigger('win_alive', [alive]), 700); };
    setTimeout(call, 1000);
    setInterval(call, 3000);
  } else {
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem('gvTabs')); } catch { /* storage blocked */ }
    if (saved) trigger('win_hello', [me, saved]);
    ch.onmessage = ({ data }) => { if (data.who) send({ alive: me }); };
    window.addEventListener('beforeunload', () => send({ bye: me }));
  }

  let drag = null;
  const css = document.createElement('style');
  css.textContent = 'body.gv-drop header.v-app-bar { outline: 3px dashed rgb(var(--v-theme-primary)); outline-offset: -3px; }';
  document.head.appendChild(css);
  const frame = on => document.body.classList.toggle('gv-drop', on);
  document.addEventListener('dragover', e => {
    if (!ours(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (drag) drag.y = e.clientY; else frame(true);
  });
  document.addEventListener('dragleave', e => { if (!e.relatedTarget && !drag) frame(false); });
  document.addEventListener('drop', e => {
    if (!ours(e)) return;
    e.preventDefault();
    frame(false);
    if (drag) { drag.here = true; return; }
    const tab = e.dataTransfer.getData(TYPE);
    if (tab) trigger('tab_move', [tab, me]);
  });
  document.addEventListener('mousemove', () => frame(false));

  const api = {
    open,
    dragStart(tab, e) {
      e.dataTransfer.setData(TYPE, tab);  // Firefox starts no drag without data
      e.dataTransfer.effectAllowed = 'move';
      drag = { y: e.clientY, here: false };
    },
    dragEnd(tab, e) {
      const d = drag;
      drag = null;
      if (!d) return;
      if (d.here) {
        const y = e.clientY || d.y;  // Firefox gives 0 on dragend
        if (y > document.querySelector('header.v-app-bar').getBoundingClientRect().bottom) open(tab);
      } else if (e.dataTransfer.dropEffect === 'none') {
        open(tab);
      }
    },
    onWindows(windows) {
      const w = (windows || {})[me];
      if (w) {
        registered = true;
        try { sessionStorage.setItem('gvTabs', JSON.stringify(w.tabs)); } catch { /* storage blocked */ }
      } else if (registered) {
        window.close();
      }
    },
    dock() { trigger('win_dock', [me]); },
  };
  api.onWindows(window.trame.state.get('windows'));
  return api;
})();
"""


def _commit(windows):
    "Publish windows without empty ones."
    windows = {k: w for k, w in windows.items() if w["tabs"]}
    state.windows = windows
    state.detachedTabs = sorted(t for w in windows.values() for t in w["tabs"])
    if state.activeTab in state.detachedTabs:
        state.activeTab = "home"


def _without(tab):
    "Windows with ``tab`` removed."
    out = {}
    for key, w in state.windows.items():
        tabs = [t for t in w["tabs"] if t != tab]
        active = w["active"] if w["active"] in tabs else (tabs[0] if tabs else None)
        out[key] = {**w, "tabs": tabs, "active": active}
    return out


@ctrl.trigger("win_open")
def win_open(win, tab):
    "New window with ``tab``."
    windows = _without(tab)
    windows[win] = {"tabs": [tab], "active": tab, "born": time.time()}
    _commit(windows)


@ctrl.trigger("win_hello")
def win_hello(win, tabs):
    "Reloaded window takes back its free tabs."
    if win in state.windows:
        return
    taken = set(state.detachedTabs)
    tabs = [t for t in tabs if t and t != "home" and t not in taken]
    if tabs:
        _commit({**state.windows,
                 win: {"tabs": tabs, "active": tabs[0], "born": time.time()}})


@ctrl.trigger("tab_move")
def tab_move(tab, dest):
    "Tab dropped onto window ``dest`` or ``main``."
    windows = _without(tab)
    if dest in windows:
        w = windows[dest]
        windows[dest] = {**w, "tabs": w["tabs"] + [tab], "active": tab}
    _commit(windows)
    if dest == "main":
        state.activeTab = tab


@ctrl.trigger("win_select")
def win_select(win, tab):
    "Tab clicked in a separate window."
    if win in state.windows:
        _commit({**state.windows, win: {**state.windows[win], "active": tab}})


@ctrl.trigger("win_close")
def win_close(win):
    "Window closed, tabs back to main."
    if win in state.windows:
        _commit({k: w for k, w in state.windows.items() if k != win})


@ctrl.trigger("win_dock")
def win_dock(win):
    "Dock button."
    w = state.windows.get(win)
    win_close(win)
    if w:
        state.activeTab = w["active"]


@ctrl.trigger("win_alive")
def win_alive(ids):
    "Drop windows that missed the roll call, unless still loading."
    now = time.time()
    _commit({k: w for k, w in state.windows.items()
             if k in ids or now - w["born"] < 5})


@state.change("activeTab")
def keep_detached_tab_out(**kwargs):
    "Main window never shows a detached tab."
    _ = kwargs
    if state.activeTab in state.detachedTabs:
        state.activeTab = "home"


def render_detach_support():
    "Window bookkeeping and drag and drop."
    client.Script(DETACH_JS)
    client.ClientStateChange(value="windows", trigger_on_create=True,
                             change="window.gv && window.gv.onWindows(windows)")


if __name__ == "__main__":
    state.activeTab = "2d"
    win_open("a", "2d")
    assert state.windows["a"]["tabs"] == ["2d"] and state.detachedTabs == ["2d"]
    assert state.activeTab == "home"
    tab_move("ts", "a")
    assert state.windows["a"] == {**state.windows["a"], "tabs": ["2d", "ts"], "active": "ts"}
    win_open("b", "2d")
    assert state.windows["a"]["tabs"] == ["ts"] and state.windows["b"]["tabs"] == ["2d"]
    tab_move("ts", "b")
    assert "a" not in state.windows and state.windows["b"]["tabs"] == ["2d", "ts"]
    tab_move("2d", "main")
    assert state.activeTab == "2d" and state.detachedTabs == ["ts"]
    win_hello("b", ["2d", "ts"])
    assert state.windows["b"]["tabs"] == ["ts"]
    win_close("b")
    win_hello("b", ["2d", "ts", "home"])
    assert state.windows["b"]["tabs"] == ["2d", "ts"] and state.activeTab == "home"
    state.windows["b"]["born"] = 0
    win_alive([])
    assert state.windows == {} and state.detachedTabs == []
    print("detach self-check ok")
