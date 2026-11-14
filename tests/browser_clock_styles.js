// Real Chrome acceptance for the four clock styles.  It measures the actual
// clock page and the preview under identical viewport/settings/message states.
// Run with: WEBCLOCK_BASE_URL=http://127.0.0.1:8898 node tests/browser_clock_styles.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');

const BASE = process.env.WEBCLOCK_BASE_URL || 'http://127.0.0.1:8898';
const CHROME = process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const OUT = process.env.WEBCLOCK_SCREENSHOT_DIR ||
    path.join(__dirname, '..', 'doc/development/screenshots/clock-styles');
const HISTORY = path.join(__dirname, '..', 'doc/development/screenshots/clock-styles-history/round2');
const METRICS_FILE = path.join(__dirname, '..', 'doc/development/clock-styles-metrics.json');
const SLEEP = ms => new Promise(resolve => setTimeout(resolve, ms));
const STYLES = ['classic', 'flip', 'segment', 'paper'];
const TIME_SELECTORS = {classic: '#time', flip: '.flip-digits', segment: '.segment-digit', paper: '.paper-time-main'};
const GROUP_SELECTORS = {classic: '#time', flip: '.flip-main', segment: '.segment-row', paper: '.paper-time'};

class CDP {
    constructor(webSocket) {
        this.ws = webSocket;
        this.nextId = 1;
        this.pending = new Map();
        this.events = new Map();
        this.persistent = new Map();
        webSocket.addEventListener('message', event => {
            const message = JSON.parse(event.data);
            if (message.id) {
                const request = this.pending.get(message.id);
                if (!request) return;
                this.pending.delete(message.id);
                if (message.error) request.reject(new Error(message.error.message));
                else request.resolve(message.result);
                return;
            }
            const listeners = this.events.get(message.method) || [];
            listeners.splice(0).forEach(listener => listener(message.params));
            (this.persistent.get(message.method) || []).forEach(listener => listener(message.params));
        });
    }
    on(method, listener) {
        if (!this.persistent.has(method)) this.persistent.set(method, []);
        this.persistent.get(method).push(listener);
    }
    off(method, listener) {
        const list = this.persistent.get(method) || [];
        const index = list.indexOf(listener);
        if (index >= 0) list.splice(index, 1);
    }
    send(method, params = {}, sessionId) {
        const id = this.nextId++;
        const payload = {id, method, params};
        if (sessionId) payload.sessionId = sessionId;
        return new Promise((resolve, reject) => {
            this.pending.set(id, {resolve, reject});
            this.ws.send(JSON.stringify(payload));
        });
    }
}

async function waitForFile(file, attempts = 100) {
    for (let index = 0; index < attempts; index++) {
        if (fs.existsSync(file)) return fs.readFileSync(file, 'utf8');
        await SLEEP(100);
    }
    throw new Error('Chrome did not expose a DevTools port');
}

async function waitFor(check, timeout = 6000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
        if (await check()) return;
        await SLEEP(100);
    }
    throw new Error('Timed out waiting for browser state');
}

async function main() {
    assert.ok(fs.existsSync(CHROME), 'Chrome not found: ' + CHROME);
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'webclock-chrome-'));
    const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
        '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], {stdio: 'ignore'});
    let session;
    let client;
    try {
        const active = await waitForFile(path.join(profile, 'DevToolsActivePort'));
        const port = active.split(/\r?\n/)[0];
        const version = await (await fetch('http://127.0.0.1:' + port + '/json/version')).json();
        const socket = new WebSocket(version.webSocketDebuggerUrl);
        await new Promise((resolve, reject) => {
            socket.addEventListener('open', resolve, {once: true});
            socket.addEventListener('error', reject, {once: true});
        });
        client = new CDP(socket);
        const target = await client.send('Target.createTarget', {url: 'about:blank'});
        session = (await client.send('Target.attachToTarget', {targetId: target.targetId, flatten: true})).sessionId;
        await client.send('Page.enable', {}, session);
        await client.send('Network.enable', {}, session);
        const frameTree = await client.send('Page.getFrameTree', {}, session);
        let mainFrameId = frameTree.frameTree.frame.id;
        let mainContextId = null;
        client.on('Page.frameNavigated', params => {
            if (!params.frame.parentId) {
                mainFrameId = params.frame.id;
                mainContextId = null;
            }
        });
        client.on('Runtime.executionContextCreated', params => {
            const context = params.context;
            if (context.auxData && context.auxData.isDefault && context.auxData.frameId === mainFrameId) {
                mainContextId = context.id;
            }
        });
        await client.send('Runtime.enable', {}, session);

        const exceptions = [];
        client.events.set('Runtime.exceptionThrown', [params => exceptions.push(params)]);

        async function evaluate(expression) {
            const request = {expression, awaitPromise: true, returnByValue: true, userGesture: true};
            if (mainContextId) request.contextId = mainContextId;
            const result = await client.send('Runtime.evaluate', request, session);
            if (result.exceptionDetails) {
                throw new Error(result.exceptionDetails.exception.description || result.exceptionDetails.text);
            }
            return result.result.value;
        }
        async function viewport(width, height) {
            await client.send('Emulation.setDeviceMetricsOverride', {
                width, height, deviceScaleFactor: 1, mobile: false
            }, session);
        }
        async function navigate(url) {
            mainContextId = null;
            await client.send('Page.navigate', {url}, session);
            await waitFor(async () => {
                if (!mainContextId) return false;
                try { return await evaluate('document.readyState === "complete"'); } catch (error) { return false; }
            });
            await SLEEP(600);
        }
        async function capture() {
            const result = await client.send('Page.captureScreenshot', {format: 'png'}, session);
            return Buffer.from(result.data, 'base64');
        }
        async function screenshot(name, buffer) {
            fs.writeFileSync(path.join(OUT, name + '.png'), buffer || await capture());
        }
        async function setShared(settings) {
            await navigate(BASE + '/admin');
            await waitFor(() => evaluate('typeof window.clockStyleDraft === "string"'));
            await evaluate('postSettings(' + JSON.stringify(settings) + ')');
        }
        async function thumbOpacity(style, theme) {
            return evaluate('(function () { var card = document.getElementById("clock_style_' + style + '").closest(".clock-style-card"); ' +
                'return getComputedStyle(card.querySelector(".clock-style-thumb-' + theme + '")).opacity; }())');
        }
        const nightOff = {enabled: false, start: '22:00', end: '07:00', brightness: 15, black: false};
        const baseSettings = {
            mode: 'normal', brightness: 100, time_format: '24h', language: 'zh-TW',
            show_seconds: false, show_date: true, date_format: 'm/d', show_weekday: true,
            message_duration: 5, message_transition: 'fade', clock_theme: 'auto', night: nightOff
        };
        function settings(extra) { return Object.assign({}, baseSettings, extra); }

        fs.mkdirSync(OUT, {recursive: true});
        await viewport(1024, 768);

        // 1. Optional style script must not delay the essential clock.
        await client.send('Network.setCacheDisabled', {cacheDisabled: true}, session);
        const intervalScript = await client.send('Page.addScriptToEvaluateOnNewDocument', {
            source: 'window.__clockIntervals = 0; (function () { var original = window.setInterval; ' +
                'window.setInterval = function (callback, delay) { if (delay === 1000) window.__clockIntervals++; ' +
                'return original.call(window, callback, delay); }; }());'
        }, session);
        const paused = [];
        const pausedListener = params => paused.push(params.requestId);
        client.on('Fetch.requestPaused', pausedListener);
        await client.send('Fetch.enable', {patterns: [{urlPattern: '*clock-styles.js*'}]}, session);
        mainContextId = null;
        await client.send('Page.navigate', {url: BASE + '/'}, session);
        await waitFor(async () => {
            if (!mainContextId) return false;
            try { return await evaluate('!!document.getElementById("time")'); } catch (error) { return false; }
        });
        assert.ok(await evaluate('window.__clockIntervals >= 1'), 'core timer starts before optional style JS');
        assert.equal(await evaluate('typeof window.localServerUrl'), 'undefined',
            'optional style JS is still blocking the settings script');
        assert.ok(paused.length >= 1, 'clock-styles.js was actually paused');
        for (const requestId of paused) await client.send('Fetch.continueRequest', {requestId}, session);
        await waitFor(async () => {
            try { return await evaluate('document.readyState === "complete"'); } catch (error) { return false; }
        });
        await client.send('Fetch.disable', {}, session);
        client.off('Fetch.requestPaused', pausedListener);
        await client.send('Page.removeScriptToEvaluateOnNewDocument', {identifier: intervalScript.identifier}, session);
        await client.send('Network.setCacheDisabled', {cacheDisabled: false}, session);

        // 2. Admin style tab: four choices, draft, save, conflict; no retired options.
        await setShared(settings({clock_style: 'classic'}));
        await navigate(BASE + '/admin');
        await waitFor(() => evaluate('typeof window.clockStyleDraft === "string"'));
        await evaluate('document.querySelector(\'[data-management-tab="styles"]\').click()');
        await SLEEP(500);
        assert.equal(await evaluate('document.querySelectorAll("[data-clock-style-choice]").length'), 4);
        assert.equal(await evaluate('!!document.getElementById("clock_style_glass")'), false);
        assert.equal(await evaluate('!!document.getElementById("clock_style_orbit")'), false);
        assert.equal(await evaluate('document.querySelectorAll("[data-clock-theme-choice]").length'), 3);
        assert.equal(await evaluate('document.getElementById("clock-style-options").getAttribute("data-theme-mode")'), 'auto');
        assert.equal(await thumbOpacity('flip', 'dark'), '1', 'auto shows the dark flip thumbnail');
        assert.equal(await thumbOpacity('flip', 'light'), '0');
        assert.equal(await thumbOpacity('paper', 'dark'), '0');
        assert.equal(await thumbOpacity('paper', 'light'), '1', 'auto shows the light paper thumbnail');
        await evaluate('(function () { var input = document.getElementById("clock_theme_dark"); ' +
            'input.checked = true; input.dispatchEvent(new Event("change", {bubbles: true})); }())');
        await SLEEP(250);
        assert.equal(await evaluate('document.getElementById("clock-style-options").getAttribute("data-theme-mode")'), 'dark');
        assert.equal(await thumbOpacity('paper', 'dark'), '1', 'dark mode switches paper to its dark thumbnail');
        assert.equal(await thumbOpacity('paper', 'light'), '0');
        await evaluate('(function () { var input = document.getElementById("clock_style_segment"); ' +
            'input.checked = true; input.dispatchEvent(new Event("change", {bubbles: true})); }())');
        const draft = await evaluate('({draft: clockStyleDraft, disabled: document.getElementById("clock-style-save").disabled, ' +
            'state: document.getElementById("clock-style-state").textContent, src: document.getElementById("clock-style-preview").src})');
        assert.equal(draft.draft, 'segment');
        assert.equal(draft.disabled, false);
        assert.match(draft.state, /尚未儲存|Not saved|未保存/);
        assert.match(draft.src, /style=segment/);
        await evaluate('(function () { var input = document.getElementById("clock_theme_light"); ' +
            'input.checked = true; input.dispatchEvent(new Event("change", {bubbles: true})); }())');
        const themeDraft = await evaluate('({draft: clockThemeDraft, disabled: document.getElementById("clock-style-save").disabled, ' +
            'src: document.getElementById("clock-style-preview").src})');
        assert.equal(themeDraft.draft, 'light');
        assert.equal(themeDraft.disabled, false);
        assert.match(themeDraft.src, /theme=light/);
        await SLEEP(250);
        assert.equal(await evaluate('document.getElementById("clock-style-options").getAttribute("data-theme-mode")'), 'light');
        assert.equal(await thumbOpacity('flip', 'light'), '1', 'light mode switches flip to its light thumbnail');
        assert.equal(await thumbOpacity('flip', 'dark'), '0');
        assert.equal(await thumbOpacity('paper', 'light'), '1');
        assert.equal(await thumbOpacity('paper', 'dark'), '0');
        await evaluate('document.querySelector(\'[data-management-tab="common"]\').click(); ' +
            'document.querySelector(\'[data-management-tab="styles"]\').click()');
        assert.equal(await evaluate('clockStyleDraft'), 'segment');
        await evaluate('document.getElementById("clock-style-restore").click()');
        await SLEEP(250);
        assert.equal(await evaluate('document.getElementById("clock-style-options").getAttribute("data-theme-mode")'), 'auto');
        assert.equal(await thumbOpacity('flip', 'dark'), '1');
        assert.equal(await thumbOpacity('paper', 'light'), '1');
        await evaluate('(function () { var input = document.getElementById("clock_style_segment"); ' +
            'input.checked = true; input.dispatchEvent(new Event("change", {bubbles: true})); ' +
            'var theme = document.getElementById("clock_theme_light"); theme.checked = true; ' +
            'theme.dispatchEvent(new Event("change", {bubbles: true})); }()); ' +
            'document.getElementById("clock-style-save").click()');
        await waitFor(() => evaluate('clockStyleSaved === "segment" && clockThemeSaved === "light"'));
        assert.match(await evaluate('document.getElementById("clock-style-status").textContent'),
            /樣式已儲存|Style saved|スタイルを保存/);
        await evaluate('clockStyleDraft = "classic"; settingsRevision = "stale"; ' +
            '(function () { var input = document.getElementById("clock_style_paper"); input.checked = true; ' +
            'input.dispatchEvent(new Event("change", {bubbles: true})); }()); ' +
            'document.getElementById("clock-style-save").click()');
        await waitFor(() => evaluate('document.getElementById("clock-style-status").textContent.length > 0'));
        const conflict = await evaluate('({draft: clockStyleDraft, status: document.getElementById("clock-style-status").textContent, ' +
            'disabled: document.getElementById("clock-style-save").disabled})');
        assert.equal(conflict.draft, 'paper');
        assert.match(conflict.status, /其他地方變更|changed elsewhere|別の場所/);
        assert.equal(conflict.disabled, true);

        await viewport(1440, 1500);
        await navigate(BASE + '/admin');
        await waitFor(() => evaluate('typeof window.clockStyleDraft === "string"'));
        await evaluate('document.querySelector(\'[data-management-tab="styles"]\').click()');
        await SLEEP(800);
        const layout = await client.send('Page.getLayoutMetrics', {}, session);
        const content = layout.cssContentSize || layout.contentSize;
        const adminShot = await client.send('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true,
            clip: {x: 0, y: 0, width: content.width, height: content.height, scale: 1}}, session);
        fs.writeFileSync(path.join(OUT, 'admin-clock-styles.png'), Buffer.from(adminShot.data, 'base64'));

        // 3. Baseline: actual classic at the same states used for comparisons.
        const stateKey = (orientation, seconds, message) =>
            orientation + (seconds ? '-seconds' : '-no-seconds') + (message ? '-message' : '-empty');
        const viewports = [
            ['landscape', 1024, 768], ['short', 1024, 650], ['portrait', 768, 1024]
        ];
        const baseline = {};
        for (const seconds of [false, true]) {
            await setShared(settings({clock_style: 'classic', show_seconds: seconds}));
            for (const [orientation, width, height] of viewports) {
                for (const message of [false, true]) {
                    await viewport(width, height);
                    await navigate(BASE + '/');
                    await waitFor(() => evaluate('document.body.classList.contains("shows-seconds") === ' +
                        (seconds ? 'true' : 'false')));
                    await waitFor(() => evaluate('document.body.className.indexOf("clock-style-enhanced") < 0'));
                    await setSampleClock();
                    await evaluate(message
                        ? 'renderList([{text: "團隊例會", time: "14:30"}])'
                        : 'renderList([])');
                    await SLEEP(600);
                    const measured = await measurePage('classic');
                    baseline[stateKey(orientation, seconds, message)] = {
                        measured: measured, image: await capture()
                    };
                }
            }
        }

        async function measurePage(style) {
            return evaluate('(function () { ' +
                'function rect(el) { if (!el) return null; var r = el.getBoundingClientRect(); var cs = getComputedStyle(el); ' +
                'var ink = 0; try { var canvas = document.createElement("canvas"); var ctx = canvas.getContext("2d"); ' +
                'ctx.font = cs.fontStyle + " " + cs.fontWeight + " " + cs.fontSize + " " + cs.fontFamily; ' +
                'var measured = ctx.measureText((el.textContent || "").trim()); ' +
                'ink = (measured.actualBoundingBoxAscent || 0) + (measured.actualBoundingBoxDescent || 0); } catch (error) {} ' +
                'if (' + JSON.stringify(style) + ' === "segment") ink = r.height; ' +
                'return {x:+r.x.toFixed(1), y:+r.y.toFixed(1), width:+r.width.toFixed(1), height:+r.height.toFixed(1), ' +
                'inkHeight:+ink.toFixed(1), fontSize:cs.fontSize}; } ' +
                'function overlap(a, b) { if (!a || !b) return false; return a.x < b.x + b.width && b.x < a.x + a.width && ' +
                'a.y < b.y + b.height && b.y < a.y + a.height; } ' +
                'var time = rect(document.querySelector(' + JSON.stringify(TIME_SELECTORS[style]) + ')); ' +
                'var group = rect(document.querySelector(' + JSON.stringify(GROUP_SELECTORS[style]) + ')); ' +
                'var date = rect(document.getElementById("date-info")); var list = rect(document.getElementById("list-container")); ' +
                'return {time:time, group:group, date:date, list:list, overlapDate:overlap(time, date), overlapList:overlap(time, list), ' +
                'bodyClass:document.body.className, hasEvents:document.body.classList.contains("has-events"), ' +
                'dayHoliday:!!(document.getElementById("day-part") && ' +
                'document.getElementById("day-part").classList.contains("holiday-highlight")), ' +
                'viewportWidth:innerWidth, viewportHeight:innerHeight, scrollWidth:document.documentElement.scrollWidth, ' +
                'scrollHeight:document.documentElement.scrollHeight}; }())');
        }

        async function themeState(style) {
            return evaluate('(function () { ' +
                'var backdrop = document.getElementById("clock-backdrop"); ' +
                'var time = document.querySelector(' + JSON.stringify(TIME_SELECTORS[style]) + '); ' +
                'var panel = document.querySelector(".flip-panel"); ' +
                'var segment = document.querySelector(".segment.on"); ' +
                'return {body: document.body.className, ' +
                'backdrop: getComputedStyle(backdrop).backgroundColor, ' +
                'color: getComputedStyle(time).color, ' +
                'panel: panel ? getComputedStyle(panel).backgroundColor : null, ' +
                'segment: segment ? getComputedStyle(segment).backgroundColor : null}; }())');
        }

        async function setSampleClock() {
            await evaluate('setClockBase(Date.UTC(2026, 10, 14, 2, 28, 36)); updateClock();');
            // The preview always uses the fixed 2026-11-14 sample (a Saturday
            // holiday).  Align the actual sample as well so this parity check
            // does not depend on the wall-clock day.
            await evaluate('document.getElementById("day-part").classList.add("holiday-highlight")');
        }

        async function waitForStyle(style) {
            await waitFor(() => evaluate('!!document.querySelector(' +
                JSON.stringify(TIME_SELECTORS[style]) + ')'));
        }

        async function composePair(left, right, leftLabel, rightLabel, name, width, height) {
            await viewport(width * 2, height + 38);
            const html = '<!DOCTYPE html><html><head><style>html,body{margin:0;background:#20242A;color:#fff;' +
                'font:600 18px -apple-system,Helvetica,Arial,sans-serif}header{height:38px;display:flex;' +
                'align-items:center}header span{display:block;width:50%;padding:0 18px;box-sizing:border-box}' +
                '.row{display:flex}img{display:block;width:' + width + 'px;height:' + height + 'px}</style></head><body>' +
                '<header><span>' + leftLabel + '</span><span>' + rightLabel + '</span></header><div class="row">' +
                '<img src="data:image/png;base64,' + left.toString('base64') + '">' +
                '<img src="data:image/png;base64,' + right.toString('base64') + '"></div></body></html>';
            await client.send('Page.setDocumentContent', {frameId: mainFrameId, html}, session);
            await SLEEP(150);
            await screenshot(name);
        }

        const metrics = {
            meta: {
                description: 'Actual / and /admin/preview measured with identical viewport, clock time, settings, theme and message state.',
                baseUrl: BASE,
                clockTime: '2026-11-14 10:28:36 (UTC+8)',
                inkHeight: 'Canvas actualBoundingBoxAscent + Descent; segment uses seven-segment geometry height.',
                styles: ['flip', 'segment', 'paper'],
                themes: ['auto', 'dark', 'light'],
                viewports: {landscape: [1024, 768], short: [1024, 650], portrait: [768, 1024]}
            },
            baseline: {}, actual: {}, preview: {}, themes: {}, comparisons: []
        };
        for (const [key, value] of Object.entries(baseline)) {
            metrics.baseline[key] = value.measured;
        }

        // 4. Actual vs preview for every main matrix state.
        for (const style of ['flip', 'segment', 'paper']) {
            metrics.actual[style] = {};
            metrics.preview[style] = {};
            for (const seconds of [false, true]) {
                await setShared(settings({clock_style: style, show_seconds: seconds}));
                for (const [orientation, width, height] of viewports) {
                    for (const message of [false, true]) {
                        const key = stateKey(orientation, seconds, message);
                        await viewport(width, height);
                        await navigate(BASE + '/');
                        await waitFor(() => evaluate('document.body.classList.contains("shows-seconds") === ' +
                            (seconds ? 'true' : 'false')));
                        await waitFor(() => evaluate('document.body.className.indexOf("clock-style-' + style + '") >= 0'));
                        await setSampleClock();
                        await evaluate(message
                            ? 'renderList([{text: "團隊例會", time: "14:30"}])'
                            : 'renderList([])');
                        await SLEEP(600);
                        await waitForStyle(style);
                        const actual = await measurePage(style);
                        const actualImage = await capture();
                        await navigate(BASE + '/admin/preview?style=' + style + '&sample=' + (message ? '1' : '0') +
                            '&show_seconds=' + (seconds ? '1' : '0'));
                        await waitForStyle(style);
                        const preview = await measurePage(style);
                        const previewImage = await capture();
                        if (orientation === 'landscape' && !seconds && message) {
                            fs.writeFileSync(path.join(OUT, 'preview-' + style + '-landscape-message.png'), previewImage);
                        }
                        metrics.actual[style][key] = actual;
                        metrics.preview[style][key] = preview;
                        assert.equal(actual.hasEvents, message, style + ' actual message state');
                        assert.equal(preview.hasEvents, message, style + ' preview message state');
                        assert.equal(preview.dayHoliday, actual.dayHoliday,
                            style + ' ' + key + ': preview holiday highlight differs from actual');
                        assert.ok(Math.abs(actual.time.fontSize.replace('px', '') - preview.time.fontSize.replace('px', '')) <= 1,
                            style + ' ' + key + ': preview and actual font size differ');
                        assert.ok(Math.abs(actual.time.height - preview.time.height) <= 1,
                            style + ' ' + key + ': preview and actual time height differ');
                        assert.ok(Math.abs(actual.time.width - preview.time.width) <= 1,
                            style + ' ' + key + ': preview and actual time width differ');
                        const classic = baseline[key].measured;
                        assert.ok(actual.time.inkHeight >= classic.time.inkHeight * 0.9,
                            style + ' ' + key + ': time is below 90% of classic (' +
                            actual.time.inkHeight + ' < ' + classic.time.inkHeight * 0.9 + ')');
                        for (const [label, measured] of [['actual', actual], ['preview', preview]]) {
                            assert.ok(measured.time.x >= -1 && measured.time.y >= -1 &&
                                measured.time.x + measured.time.width <= measured.viewportWidth + 1 &&
                                measured.time.y + measured.time.height <= measured.viewportHeight + 1,
                                style + ' ' + key + ' ' + label + ': time inside viewport');
                            assert.equal(measured.overlapDate, false, style + ' ' + key + ' ' + label + ': time/date overlap');
                            assert.equal(measured.overlapList, false, style + ' ' + key + ' ' + label + ': time/message overlap');
                            assert.ok(measured.scrollWidth <= measured.viewportWidth + 1, style + ' ' + key + ' ' + label + ': horizontal overflow');
                            assert.ok(measured.scrollHeight <= measured.viewportHeight + 1, style + ' ' + key + ' ' + label + ': vertical overflow');
                        }
                        const suffix = style + '-' + orientation + '-' + (seconds ? 'seconds' : 'no-seconds') +
                            '-' + (message ? 'message' : 'empty');
                        await composePair(actualImage, previewImage, 'Actual /', 'Preview',
                            'actual-vs-preview-' + suffix, width, height);
                        await composePair(baseline[key].image, actualImage, 'Classic actual', style + ' actual',
                            'actual-classic-vs-' + suffix, width, height);
                    }
                }
            }
        }

        // 4b. Every style has an explicit dark and light palette.  The same
        // palette must apply in the actual page and the preview.
        for (const style of STYLES) {
            metrics.themes[style] = {};
            const images = {};
            for (const theme of ['dark', 'light']) {
                await setShared(settings({clock_style: style, clock_theme: theme, show_seconds: false}));
                await viewport(1024, 768);
                await navigate(BASE + '/');
                if (style !== 'classic') {
                    await waitFor(() => evaluate('document.body.className.indexOf("clock-style-' + style + '") >= 0'));
                }
                await setSampleClock();
                await evaluate('renderList([{text: "團隊例會", time: "14:30"}])');
                await SLEEP(600);
                await waitForStyle(style);
                const actual = await measurePage(style);
                const actualState = await themeState(style);
                const actualImage = await capture();
                assert.match(actualState.body, new RegExp('clock-theme-' + theme),
                    style + ' actual has the ' + theme + ' theme class');
                assert.ok(actualState.body.indexOf('clock-theme-' + (theme === 'dark' ? 'light' : 'dark')) < 0,
                    style + ' actual must not carry both theme classes');
                await navigate(BASE + '/admin/preview?style=' + style + '&theme=' + theme +
                    '&sample=1&show_seconds=0');
                await waitForStyle(style);
                const preview = await measurePage(style);
                const previewState = await themeState(style);
                const previewImage = await capture();
                assert.match(previewState.body, new RegExp('clock-theme-' + theme),
                    style + ' preview has the ' + theme + ' theme class');
                assert.equal(previewState.body.indexOf('clock-theme-' + (theme === 'dark' ? 'light' : 'dark')) < 0,
                    true, style + ' preview must not carry both theme classes');
                assert.equal(previewState.backdrop, actualState.backdrop,
                    style + ' ' + theme + ': preview and actual backdrop differ');
                assert.equal(previewState.color, actualState.color,
                    style + ' ' + theme + ': preview and actual time color differ');
                assert.equal(previewState.panel, actualState.panel,
                    style + ' ' + theme + ': preview and actual panel color differ');
                assert.equal(previewState.segment, actualState.segment,
                    style + ' ' + theme + ': preview and actual segment color differ');
                assert.ok(Math.abs(actual.time.height - preview.time.height) <= 1,
                    style + ' ' + theme + ': preview and actual time height differ');
                assert.ok(Math.abs(actual.time.width - preview.time.width) <= 1,
                    style + ' ' + theme + ': preview and actual time width differ');
                assert.equal(actual.overlapDate, false, style + ' ' + theme + ': time/date overlap');
                assert.equal(actual.overlapList, false, style + ' ' + theme + ': time/message overlap');
                assert.ok(actual.scrollWidth <= actual.viewportWidth + 1);
                assert.ok(actual.scrollHeight <= actual.viewportHeight + 1);
                metrics.themes[style][theme] = {actual, preview, actualState, previewState};
                images[theme] = actualImage;
                fs.writeFileSync(path.join(OUT, 'theme-' + style + '-' + theme + '-actual.png'), actualImage);
                await composePair(actualImage, previewImage, 'Actual /', 'Preview',
                    'theme-actual-vs-preview-' + style + '-' + theme, 1024, 768);
            }
            const dark = metrics.themes[style].dark.actualState;
            const light = metrics.themes[style].light.actualState;
            assert.notEqual(dark.backdrop, light.backdrop, style + ': dark and light backdrop are identical');
            assert.notEqual(dark.color, light.color, style + ': dark and light time colors are identical');
            if (dark.panel !== null || light.panel !== null) {
                assert.notEqual(dark.panel, light.panel, style + ': dark and light flip panels are identical');
            }
            if (dark.segment !== null || light.segment !== null) {
                assert.notEqual(dark.segment, light.segment, style + ': dark and light segment colors are identical');
            }
            await composePair(images.dark, images.light, 'Dark', 'Light', 'theme-pair-' + style, 1024, 768);
        }

        // 5. 12-hour/long-date and no-date actual vs preview.
        for (const style of ['flip', 'segment', 'paper']) {
            for (const [label, extra] of [
                ['12h-long', {time_format: '12h', date_format: 'yyyy-mm-dd', show_seconds: true}],
                ['no-date', {time_format: '24h', date_format: 'm/d', show_date: false, show_weekday: false}]
            ]) {
                await setShared(settings(Object.assign({clock_style: style}, extra)));
                await viewport(1024, 768);
                await navigate(BASE + '/');
                await waitFor(() => evaluate('document.body.classList.contains("shows-seconds") === ' +
                    (extra.show_seconds ? 'true' : 'false')));
                await waitFor(() => evaluate('document.body.className.indexOf("clock-style-' + style + '") >= 0'));
                await setSampleClock();
                await evaluate('renderList([{text: "團隊例會", time: "14:30"}])');
                await SLEEP(600);
                await waitForStyle(style);
                const actual = await measurePage(style);
                const actualImage = await capture();
                const query = new URLSearchParams(Object.assign({style, sample: '1'}, extra));
                await navigate(BASE + '/admin/preview?' + query.toString());
                await waitForStyle(style);
                const preview = await measurePage(style);
                const previewImage = await capture();
                assert.ok(Math.abs(actual.time.height - preview.time.height) <= 1,
                    style + ' ' + label + ': preview and actual time height differ');
                assert.equal(actual.overlapDate, false);
                assert.equal(actual.overlapList, false);
                assert.ok(actual.scrollWidth <= actual.viewportWidth + 1);
                assert.ok(actual.scrollHeight <= actual.viewportHeight + 1);
                await composePair(actualImage, previewImage, 'Actual /', 'Preview',
                    'special-' + style + '-' + label, 1024, 768);
            }
        }

        // 6. Actual page responsiveness.
        for (const style of STYLES) {
            await setShared(settings({clock_style: style, show_seconds: false}));
            for (const [label, width, height] of [
                ['phone-portrait', 390, 844], ['phone-landscape', 844, 390], ['desktop', 1920, 1080]
            ]) {
                await viewport(width, height);
                await navigate(BASE + '/');
                if (style !== 'classic') {
                    await waitFor(() => evaluate('document.body.className.indexOf("clock-style-' + style + '") >= 0'));
                }
                await setSampleClock();
                await evaluate('renderList([{text: "團隊例會", time: "14:30"}])');
                await SLEEP(600);
                await waitForStyle(style);
                const measured = style === 'classic' ? await measurePage('classic') : await measurePage(style);
                assert.ok(measured.time.x >= -1 && measured.time.y >= -1 &&
                    measured.time.x + measured.time.width <= measured.viewportWidth + 1 &&
                    measured.time.y + measured.time.height <= measured.viewportHeight + 1,
                    style + ' ' + label + ': time inside viewport');
                assert.equal(measured.overlapDate, false, style + ' ' + label + ': time/date overlap');
                assert.equal(measured.overlapList, false, style + ' ' + label + ': time/message overlap');
                assert.ok(measured.scrollWidth <= measured.viewportWidth + 1, style + ' ' + label + ': horizontal overflow');
                assert.ok(measured.scrollHeight <= measured.viewportHeight + 1, style + ' ' + label + ': vertical overflow');
                await screenshot('actual-responsive-' + style + '-' + label);
            }
        }

        // 7. Brightness, night and black screen apply to the style backdrop.
        async function bodyState() {
            return evaluate('({backdrop: document.getElementById("clock-backdrop").style.opacity, ' +
                'backdropColor: getComputedStyle(document.getElementById("clock-backdrop")).backgroundColor, ' +
                'clock: document.getElementById("clock-container").style.opacity, ' +
                'clockComputed: getComputedStyle(document.getElementById("clock-container")).opacity, ' +
                'bodyBackground: getComputedStyle(document.body).backgroundColor, ' +
                'themeDark: document.body.classList.contains("clock-theme-dark"), ' +
                'themeLight: document.body.classList.contains("clock-theme-light"), ' +
                'night: document.body.classList.contains("night-active"), ' +
                'black: document.body.classList.contains("force-black")})');
        }
        const localNow = new Date(Date.now() + 8 * 3600000);
        const minutesNow = localNow.getUTCHours() * 60 + localNow.getUTCMinutes();
        const hhmm = value => String(Math.floor(value / 60)).padStart(2, '0') + ':' +
            String(value % 60).padStart(2, '0');
        const activeNight = {enabled: true, start: hhmm((minutesNow + 1380) % 1440),
            end: hhmm((minutesNow + 60) % 1440), brightness: 12, black: false};
        await setShared(settings({clock_style: 'paper', brightness: 0}));
        await navigate(BASE + '/');
        await waitFor(() => evaluate('document.getElementById("clock-backdrop").style.opacity === "0"'));
        let state = await bodyState();
        assert.equal(state.clock, '0');
        assert.equal(state.bodyBackground, 'rgb(0, 0, 0)');
        await screenshot('actual-paper-brightness-0');
        await setShared(settings({clock_style: 'paper', brightness: 20}));
        await navigate(BASE + '/');
        await waitFor(() => evaluate('document.getElementById("clock-backdrop").style.opacity === "0.2"'));
        state = await bodyState();
        assert.equal(state.clock, '0.2');
        assert.equal(state.backdropColor, 'rgb(242, 238, 229)');
        await screenshot('actual-paper-brightness-20');
        await setShared(settings({clock_style: 'paper', brightness: 100, clock_theme: 'light', night: activeNight}));
        await navigate(BASE + '/');
        await waitFor(() => evaluate('document.body.classList.contains("night-active")'));
        state = await bodyState();
        assert.equal(state.backdrop, '0.12');
        assert.equal(state.backdropColor, 'rgb(23, 26, 29)');
        assert.equal(state.themeDark, true, 'night forces the dark palette even when light was selected');
        assert.equal(state.themeLight, false);
        await screenshot('actual-paper-night');
        await setShared(settings({clock_style: 'paper', brightness: 100, mode: 'black'}));
        await navigate(BASE + '/');
        await waitFor(() => evaluate('document.body.classList.contains("force-black")'));
        state = await bodyState();
        assert.equal(state.black, true);
        assert.equal(state.backdropColor, 'rgb(0, 0, 0)');
        assert.equal(state.clockComputed, '0');
        await screenshot('actual-paper-black');
        await setShared(settings({clock_style: 'classic'}));

        // 8. Historical round-2 before/after for the four retained styles.
        for (const style of ['flip', 'segment', 'paper']) {
            const oldFile = path.join(HISTORY, 'preview-' + style + '-landscape-message.png');
            const newFile = path.join(OUT, 'preview-' + style + '-landscape-message.png');
            if (!fs.existsSync(oldFile) || !fs.existsSync(newFile)) continue;
            await composePair(fs.readFileSync(oldFile), fs.readFileSync(newFile),
                'Round 2 (historical)', 'Round 3', 'before-after-' + style + '-landscape-message', 1024, 768);
        }

        fs.writeFileSync(METRICS_FILE, JSON.stringify(metrics, null, 2) + '\n');
        assert.deepEqual(exceptions, [], 'clock pages must not throw uncaught exceptions');
        console.log('Browser checks passed: four styles with dark/light palettes, actual/preview parity, ' +
            'classic 90% scale, message/seconds/12h/long-date/no-date, responsiveness, ' +
            'brightness/night/black, delayed optional JS, and ' + OUT);
    } finally {
        try { if (client) client.ws.close(); } catch (error) {}
        chrome.kill('SIGTERM');
        await SLEEP(300);
        try { fs.rmSync(profile, {recursive: true, force: true}); } catch (error) {}
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
