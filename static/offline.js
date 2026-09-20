(function () {
    var status = document.getElementById('offline-status');
    function show(state) {
        if (status) {
            status.setAttribute('data-state', state);
            status.textContent = status.getAttribute('data-' + state);
        }
    }
    if (!window.isSecureContext || !('serviceWorker' in navigator)) {
        show('unavailable');
        return;
    }
    navigator.serviceWorker.register('sw.js', {updateViaCache: 'none'}).then(function () {
        return navigator.serviceWorker.ready;
    }).then(function () {
        show('ready');
    }).catch(function () {
        show('failed');
    });
}());
