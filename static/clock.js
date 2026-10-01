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
