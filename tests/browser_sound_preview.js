// Run on /admin#sounds with playwright-cli run-code --filename tests/browser_sound_preview.js
async page => {
    const assert = (value, message) => { if (!value) throw new Error(message); };
    const button = sound => page.locator('[data-preview-tone="' + sound + '"]');
    const stop = page.locator('#stop-tone');
    await page.evaluate(() => {
        window.previewNotes = 0;
        const start = OscillatorNode.prototype.start;
        OscillatorNode.prototype.start = function (...args) {
            window.previewNotes++;
            return start.apply(this, args);
        };
    });
    try {
        await button('beep').click();
        await page.waitForFunction(() => window.previewNotes >= 3, null, {timeout: 7000});
        assert(await button('beep').getAttribute('aria-pressed') === 'true', 'Beep should repeat');
        await button('chime').click();
        assert(await button('beep').getAttribute('aria-pressed') === 'false', 'Only one tone may be active');
        await stop.click();
        const stoppedCount = await page.evaluate(() => window.previewNotes);
        await page.waitForTimeout(2200);
        assert(await page.evaluate(() => window.previewNotes) === stoppedCount, 'Stop must cancel future notes');
        assert(await stop.isDisabled(), 'Stop should be disabled while idle');
        await button('digital').click();
        await button('silent').click();
        assert(await stop.isDisabled(), 'Silent should stop playback');
        await button('bell').click();
        await button('bell').click();
        assert(await stop.isDisabled(), 'An active tone should toggle off');
        await button('sonar').click();
        await page.locator('#preview-volume').fill('0');
        assert(await stop.isDisabled(), 'Muting should stop playback');
        await page.locator('#preview-volume').fill('70');
        await button('pulse').click();
        const effectsLink = page.locator('[data-management-link="effects"]');
        if (!await effectsLink.isVisible()) await page.locator('#management-menu-toggle').click();
        await effectsLink.click();
        await page.locator('#alarm-effects').waitFor({state: 'visible'});
        assert(await button('pulse').isHidden(), 'Sound library belongs on its own page');
        await page.locator('#preview-effects').click();
        await page.locator('#effects-sample').waitFor({state: 'visible'});
        await page.waitForFunction(() => document.getElementById('stop-tone').disabled);
    } finally {
        await page.reload();
    }
}
