"""Headless check of Loop One with a mocked WebXR runtime.

Run: python3 test/run_test.py   (needs ffmpeg and playwright's chromium)
"""
import http.server, math, os, subprocess, sys, tempfile, threading, functools
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'site')
VIDS = tempfile.mkdtemp()

def make(name, w, h):
    path = os.path.join(VIDS, name)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc2=s={w}x{h}:r=30:d=2',
                    '-f', 'lavfi', '-i', 'sine=d=2', '-shortest', '-c:v', 'libvpx-vp9', '-b:v', '200k',
                    '-c:a', 'libopus', path], check=True)
    return path

files = [make('10 concert.webm', 320, 180), make('02 city_360_TB.webm', 320, 320),
         make('01 beach_180_LR.webm', 640, 320), make('03 unlabeled.webm', 640, 320)]
bad = os.path.join(VIDS, '04 broken.webm'); open(bad, 'wb').write(os.urandom(4096))

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
handler.log_message = lambda *a: None
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 8123), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

MOCK = r"""
(() => {
  const X = window.__xr = { layers: [], states: [], session: null, violations: [], noEmpty: false,
    gp: { axes: [0, 0, 0, 0], buttons: Array.from({ length: 7 }, () => ({ pressed: false, value: 0 })) } };
  const ident = () => new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]);
  const persp = () => { const f = 1, n = .1, fa = 1000; return new Float32Array([f,0,0,0, 0,f,0,0, 0,0,(fa+n)/(n-fa),-1, 0,0,2*fa*n/(n-fa),0]); };
  const view = eye => ({ eye, projectionMatrix: persp(), transform: { inverse: { matrix: ident() } } });
  const live = v => X.layers.some(l => l.video === v && !l.destroyed);
  const flag = msg => { X.violations.push(msg); console.warn('VIOLATION ' + msg); };
  // A player bound to a live layer must never get a new file or be emptied.
  const srcDesc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src');
  Object.defineProperty(HTMLMediaElement.prototype, 'src', { configurable: true, get: srcDesc.get,
    set(v) { if (live(this)) flag('src changed on a player bound to a live layer'); srcDesc.set.call(this, v); } });
  const rmAttr = Element.prototype.removeAttribute;
  Element.prototype.removeAttribute = function (n) {
    if (n === 'src' && this instanceof HTMLMediaElement && live(this)) flag('src removed from a player bound to a live layer');
    return rmAttr.call(this, n); };
  const mkLayer = (type, v, o, extra) => {
    if (live(v)) flag('second live layer on one player');
    const l = { type, ...o, space: undefined, ...extra, destroy() {
      const s = X.session, shown = s && !s.ended && (s.pending?.layers ?? s.renderState.layers).includes(l);
      if (shown) flag('layer destroyed while still in the scene');
      l.destroyed = true; } };
    Object.defineProperty(l, 'video', { value: v });
    X.layers.push(l); return l; };
  class Session extends EventTarget {
    constructor(o) { super(); this.enabledFeatures = ['local', ...(o.optionalFeatures || [])];
      this.renderState = { baseLayer: null, layers: [] }; this.inputSources = [{ handedness: 'right', gamepad: X.gp }]; this.cbs = [];
      this.supportedFrameRates = new Float32Array([72, 80, 90, 120]); this.frameRate = 72; }
    updateTargetFrameRate(r) { this.frameRate = r; return Promise.resolve(); }
    requestReferenceSpace() { return Promise.resolve({ kind: 'local' }); }
    // Like a real runtime: changes apply at the next frame, and no frame callbacks run with nothing to show.
    updateRenderState(s) {
      if (X.noEmpty && s.layers && !s.layers.length) throw new TypeError('empty layers');
      this.pending = { ...this.pending, ...s }; X.states.push(s); }
    requestAnimationFrame(cb) { this.cbs.push(cb); return this.cbs.length; }
    end() { this.ended = true; this.dispatchEvent(new Event('end')); return Promise.resolve(); }
    tick() { if (this.pending) { Object.assign(this.renderState, this.pending); this.pending = null; }
      const cbs = this.cbs; this.cbs = [];
      const ok = this.renderState.baseLayer || this.renderState.layers.length;
      if (!ok) { this.cbs = cbs; return; }
      const frame = { session: this, getViewerPose: () => ({ views: [view('left'), view('right')] }) };
      cbs.forEach(cb => cb(performance.now(), frame)); }
  }
  Object.defineProperty(navigator, 'xr', { configurable: true, value: {
    isSessionSupported: async () => true,
    requestSession: async (mode, o) => (X.session = new Session(o)) } });
  window.XRWebGLLayer = class { constructor(s, gl) { this.framebuffer = null; }
    getViewport(v) { return v.eye === 'left' ? { x: 0, y: 0, width: 150, height: 150 } : { x: 150, y: 0, width: 150, height: 150 }; } };
  window.XRRigidTransform = class { constructor(p) { this.position = p; } };
  window.XRMediaBinding = class { constructor(s) {}
    createEquirectLayer(v, o) { return mkLayer('equirect', v, o, {}); }
    createQuadLayer(v, o) { return mkLayer('quad', v, o, { transform: o.transform.position }); } };
})();
"""

fails = []
def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond: fails.append(msg)

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context()
    ctx.add_init_script(MOCK)
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
    page.goto('http://127.0.0.1:8123/')
    page.wait_for_function('window.LoopOne')
    J = page.evaluate
    tick = lambda n=1: [J('__xr.session && __xr.session.tick()') for _ in range(n)]
    def settle():                                  # until the new video's layer is in the scene
        for _ in range(100):
            tick()
            if J('LoopOne.ready'): return True
            page.wait_for_timeout(30)
        return False
    def stick(x):
        J(f'__xr.gp.axes[2] = {x}'); tick(); J('__xr.gp.axes[2] = 0'); tick(); settle()
    def button(i):
        J(f'__xr.gp.buttons[{i}].pressed = true'); tick(); J(f'__xr.gp.buttons[{i}].pressed = false'); tick(); settle()
    vid = lambda prop: J(f'LoopOne.video && LoopOne.video.{prop}')
    def wait_layers(n):
        for _ in range(100):
            tick()
            if J('__xr.layers.length') >= n: return True
            page.wait_for_timeout(50)
        return False
    cur = lambda: J('LoopOne.current && LoopOne.current.name')
    last = lambda: J('__xr.layers.at(-1)')

    check(J("document.getElementById('enter').disabled"), 'Enter VR disabled with empty playlist')
    page.set_input_files('#pick', files)
    page.wait_for_function('LoopOne.items.length === 4 && LoopOne.items.every(i => i.w > 0)')
    names = J('LoopOne.items.map(i => i.name)')
    check(names == ['01 beach_180_LR.webm', '02 city_360_TB.webm', '03 unlabeled.webm', '10 concert.webm'], f'natural filename order {names}')
    fm = J('LoopOne.items.map(i => i.format)')
    check(fm == ['180-sbs', '360-tb', '180-sbs', 'flat-mono'], f'detected formats {fm}')
    page.set_input_files('#pick', files[:1])
    check(J('LoopOne.items.length') == 4, 'duplicate add ignored')

    # Native-layer path. Hold trigger while entering: must not pause on first sighting.
    J('__xr.gp.buttons[0].pressed = true')
    page.click('#enter')
    check(wait_layers(1), 'equirect layer created')
    tick(3); J('__xr.gp.buttons[0].pressed = false'); tick()
    check(not vid('paused'), 'held trigger on entry does not pause')
    l = last(); check(l['type'] == 'equirect' and l['layout'] == 'stereo-left-right' and abs(l['centralHorizontalAngle'] - math.pi) < 1e-6, '180 SBS layer params')
    check(vid('loop'), 'video loops')
    check(J('document.querySelectorAll("video").length') == 0, 'player kept out of the page')
    try:
        page.wait_for_function('__xr.session.frameRate === 90', timeout=10000); ok = True
    except Exception: ok = False
    check(ok, f'refresh rate matched to 30 fps video ({J("__xr.session.frameRate")} Hz)')

    stick(1); check(wait_layers(2), 'stick right switches layer')
    check(cur() == '02 city_360_TB.webm', f'stick right -> next ({cur()})')
    l = last(); check(l['layout'] == 'stereo-top-bottom' and abs(l['centralHorizontalAngle'] - 2 * math.pi) < 1e-6, '360 TB layer params')
    check(J('__xr.layers[0].destroyed') is True, 'old layer destroyed')

    check(J('LoopOne.video.src.startsWith("blob:")') and J('__xr.layers.filter(l => !l.destroyed).length') == 1, 'one live layer after switch')
    J('__xr.gp.axes[2] = 1'); tick(5); J('__xr.gp.axes[2] = 0.5'); tick(3); J('__xr.gp.axes[2] = 0'); tick(); settle()
    check(cur() == '03 unlabeled.webm', 'held stick advances exactly once')
    stick(-1); check(cur() == '02 city_360_TB.webm', 'stick left -> previous')
    button(4); check(cur() == '03 unlabeled.webm', 'A -> next')
    stick(-1); stick(-1); stick(-1)
    check(cur() == '10 concert.webm', 'stick left wraps to last')
    wait_layers(len(J('__xr.layers')) + 1)
    l = last(); check(l['type'] == 'quad' and abs(l['width'] - 3.2) < 1e-6 and abs(l['height'] - 1.8) < 1e-3 and l['transform']['z'] == -2.5, f'flat quad layer {l.get("width")}x{l.get("height")}')

    button(0); check(vid('paused'), 'trigger pauses')
    button(0); page.wait_for_timeout(200); check(not vid('paused'), 'trigger resumes')

    n = J('__xr.layers.length')
    page.select_option('#list li:nth-child(4) select', 'flat-sbs')
    wait_layers(n + 1); check(J('__xr.layers.length') == n + 1 and last()['layout'] == 'stereo-left-right', 'format change rebuilds live layer')
    page.select_option('#list li:nth-child(4) select', 'flat-mono'); wait_layers(n + 2)

    # Broken file: auto-skips in the direction of travel.
    page.set_input_files('#pick', [bad])
    J("while (LoopOne.current.name !== '03 unlabeled.webm') LoopOne.step(1)")
    J("LoopOne.step(1)")                          # onto 04 broken
    for _ in range(60):
        tick(); page.wait_for_timeout(50)
        if cur() != '04 broken.webm': break
    check(cur() == '10 concert.webm', f'broken file skipped ({cur()})')
    st = J("document.getElementById('status').textContent"); check('won’t play' in st, f'broken file reported ({st})')
    errors[:] = [e for e in errors if 'MEDIA' not in e.upper() and 'DEMUXER' not in e.upper()]

    settle()
    button(5)
    check(J('__xr.session.ended') is True and J('LoopOne.session') is None and vid('paused'), 'B leaves VR and pauses')
    check(J('localStorage.getItem("fmt:10 concert.webm")') == 'flat-mono', 'manual format persisted')

    # Runtime that refuses an empty layer list: old layer stays up until the new one replaces it.
    J('__xr.noEmpty = true')
    page.click('#enter'); settle()
    n = J('__xr.layers.length'); stick(1)
    check(J('__xr.layers.length') == n + 1 and J('__xr.layers.filter(l => !l.destroyed).length') <= 2, 'switch works without an empty scene')
    page.wait_for_timeout(300)
    check(J('__xr.layers.filter(l => !l.destroyed).length') == 1, 'old layer cleaned up after replacement')
    button(5); J('__xr.noEmpty = false')
    check(J('__xr.violations') == [], f'no unsafe layer or player handling {J("__xr.violations")}')

    # WebGL fallback path.
    page.select_option('#renderer', 'gl')
    page.click('#list li:nth-child(1) .name')
    page.click('#enter')
    for _ in range(60):
        tick(); page.wait_for_timeout(50)
        if J('LoopOne.session && LoopOne.session.gl && LoopOne.session.gl.count > 0 && LoopOne.video.readyState >= 2'): break
    tick(3)
    check(J('!!__xr.session.renderState.baseLayer') and J('LoopOne.session.mode') == 'gl', 'GL mode uses baseLayer')
    px = J("""(() => { const g = LoopOne.session.gl.gl; __xr.session.tick();
              const b = new Uint8Array(4); g.readPixels(75, 75, 1, 1, g.RGBA, g.UNSIGNED_BYTE, b); return [...b]; })()""")
    check(sum(px[:3]) > 30, f'GL draws video pixels {px}')
    stick(1)
    for _ in range(60):
        tick(); page.wait_for_timeout(30)
        if J('LoopOne.session.gl.lay') == 'tb': break
    check(J('LoopOne.session.gl.lay') == 'tb' and J('LoopOne.session.gl.count') == 6 * 96 * 48, 'GL mesh rebuilt for 360 TB')
    button(5); check(J('LoopOne.session') is None, 'B leaves VR in GL mode')
    check(J("localStorage.getItem('renderer')") == 'gl', 'renderer choice persisted')

    # Offline reload served by the service worker.
    page.wait_for_function('navigator.serviceWorker.controller !== null || navigator.serviceWorker.ready.then(() => true)')
    page.reload(); page.wait_for_function('navigator.serviceWorker.controller')
    ctx.set_offline(True)
    page.reload()
    check(page.inner_text('h1') == 'Loop One', 'page loads offline from cache')
    check(J("document.fonts.check('19px \"Atkinson Hyperlegible Next\"')"), 'self-hosted font available offline')
    page.screenshot(path=os.path.join(VIDS, 'shot.png'), full_page=True)

    check(not errors, f'no page errors {errors}')
    browser.close()

srv.shutdown()
print('\n' + ('ALL PASSED' if not fails else f'{len(fails)} FAILED'))
sys.exit(1 if fails else 0)
