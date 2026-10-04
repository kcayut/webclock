// A null offset follows the device timezone, including daylight saving changes.
function renderClock(utcMs, timezoneOffset, weekDays, timeFormat, language) {
    var deviceTime = new Date(utcMs);
    var offset = timezoneOffset === null ? -deviceTime.getTimezoneOffset() / 60 : timezoneOffset;
    var targetTime = new Date(utcMs + offset * 3600000);
    var hour = targetTime.getUTCHours();
    var h = String(timeFormat === '12h' ? hour % 12 || 12 : hour).replace(/^(\d)$/, '0$1');
    var m = String(targetTime.getUTCMinutes()).replace(/^(\d)$/, '0$1');

    document.getElementById('time').textContent = h + ':' + m;
    var period = document.getElementById('time-period');
    if (period) {
        period.textContent = timeFormat === '12h' ? window.WebClockTime.period(hour, language) : '';
        period.style.display = timeFormat === '12h' ? 'inline-block' : 'none';
    }
    document.getElementById('date-part').textContent = (targetTime.getUTCMonth() + 1) + '/' + targetTime.getUTCDate();
    document.getElementById('day-part').textContent = weekDays[targetTime.getUTCDay()];
}

function clockDisplaySettings(settings, utcMs, timezoneOffset) {
    var date = new Date(utcMs);
    var offset = timezoneOffset === null ? -date.getTimezoneOffset() / 60 : timezoneOffset;
    var local = new Date(utcMs + offset * 3600000);
    var minutes = local.getUTCHours() * 60 + local.getUTCMinutes();
    var night = settings.night || {};
    var toMinutes = function (time) {
        var parts = String(time).split(':');
        return Number(parts[0]) * 60 + Number(parts[1]);
    };
    var start = toMinutes(night.start);
    var end = toMinutes(night.end);
    var active = night.enabled && start !== end &&
        (start < end ? minutes >= start && minutes < end : minutes >= start || minutes < end);
    return {
        mode: settings.mode === 'black' || (active && night.black) ? 'black' : 'normal',
        brightness: active ? night.brightness : (settings.brightness === undefined ? 100 : settings.brightness)
    };
}

/*
 * Start the essential clock before any optional page feature is parsed or run.
 * A richer page can replace the updater without creating a second timer.  If
 * that updater later fails, the device-time clock remains the last-resort path.
 */
(function (root) {
    var runtime = null;

    function start(options) {
        if (runtime) return runtime;
        options = options || {};
        runtime = {
            weekDays: options.weekDays || ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
            language: options.language || 'en',
            updater: null,
            timer: null
        };

        function renderBasicClock() {
            renderClock(new Date().getTime(), null, runtime.weekDays, '24h', runtime.language);
        }

        runtime.tick = function () {
            if (runtime.updater) {
                try {
                    runtime.updater();
                    return;
                } catch (e) {
                    /* Optional display work must not stop the basic clock. */
                }
            }
            renderBasicClock();
        };

        runtime.tick();
        runtime.timer = setInterval(runtime.tick, 1000);
        document.addEventListener('visibilitychange', runtime.tick);
        root.addEventListener('pageshow', runtime.tick);
        return runtime;
    }

    function useUpdater(updater) {
        if (!runtime || typeof updater !== 'function') return;
        runtime.updater = updater;
        runtime.tick();
    }

    root.WebClockCore = {
        start: start,
        useUpdater: useUpdater
    };
}(window));
