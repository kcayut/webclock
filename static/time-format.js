/* Shared display-only formatting. Stored times remain 24-hour HH:MM. ES5 for old clocks. */
(function (root) {
    'use strict';
    function labels(language) {
        if (language === 'en') return {am: 'AM', pm: 'PM', hour: 'Hour', minute: 'Minute', date: 'Date', period: 'AM / PM'};
        if (language === 'ja') return {am: '午前', pm: '午後', hour: '時', minute: '分', date: '日付', period: '午前 / 午後'};
        return {am: '上午', pm: '下午', hour: '小時', minute: '分鐘', date: '日期', period: '上午 / 下午'};
    }
    function period(hour, language) { return labels(language)[hour < 12 ? 'am' : 'pm']; }
    function pad(value) { return ('0' + value).slice(-2); }
    function format(value, style, language) {
        var match = /^(?:(\d{4}-\d{2}-\d{2})[T ])?([01]\d|2[0-3]):([0-5]\d)(:[0-5]\d)?$/.exec(value);
        if (!match) return value;
        var hour = Number(match[2]);
        var time = (style === '12h' ? pad(hour % 12 || 12) : match[2]) + ':' + match[3] + (match[4] || '');
        if (style === '12h') time = language === 'en' ? time + ' ' + period(hour, language) : period(hour, language) + ' ' + time;
        return (match[1] ? match[1] + ' ' : '') + time;
    }
    root.WebClockTime = {format: format, period: period, labels: labels, pad: pad};
}(window));
