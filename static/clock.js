// A null offset follows the device timezone, including daylight saving changes.
function renderClock(utcMs, timezoneOffset, weekDays) {
    var deviceTime = new Date(utcMs);
    var offset = timezoneOffset === null ? -deviceTime.getTimezoneOffset() / 60 : timezoneOffset;
    var targetTime = new Date(utcMs + offset * 3600000);
    var h = String(targetTime.getUTCHours()).replace(/^(\d)$/, '0$1');
    var m = String(targetTime.getUTCMinutes()).replace(/^(\d)$/, '0$1');

    document.getElementById('time').textContent = h + ':' + m;
    document.getElementById('date-part').textContent = (targetTime.getUTCMonth() + 1) + '/' + targetTime.getUTCDate();
    document.getElementById('day-part').textContent = weekDays[targetTime.getUTCDay()];
}
