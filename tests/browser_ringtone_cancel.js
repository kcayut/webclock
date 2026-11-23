// Run on /admin#sounds with at least one custom ringtone in disposable test data.
async page => {
    const assert = (value, message) => { if (!value) throw new Error(message); };
    const source = page.locator('[data-duplicate-ringtone]').first();
    const panel = page.locator('.ringtone-options').first();
    const trim = panel.locator('[data-copy-ringtone]');
    const duplicate = panel.locator('[data-duplicate-draft]');
    const writes = [];
    const record = request => {
        if (request.url().includes('/api/ringtones') && request.method() !== 'GET') writes.push(request.method());
    };
    page.on('request', record);
    try {
        const add = page.locator('#ringtone-add');
        const file = page.locator('#ringtone-file');
        const cancel = page.locator('#ringtone-cancel-edit');
        await add.click();
        await cancel.click();
        assert(await add.evaluate(node => document.activeElement === node), 'Cancel before choosing a file should return focus to Add');
        await add.click();
        const id = await trim.getAttribute('data-copy-ringtone');
        const url = await page.evaluate(key => window.webclockUrl('/api/ringtones/' + key), id);
        const audio = await page.request.get(new URL(url, page.url()).href);
        await file.setInputFiles({name: 'draft.wav', mimeType: 'audio/wav', buffer: await audio.body()});
        await page.locator('#ringtone-clip').waitFor();
        await page.locator('#ringtone-name').fill('Discard new ringtone');
        await page.locator('#ringtone-preview').click();
        await cancel.click();
        assert(await page.locator('#ringtone-preview').getAttribute('aria-pressed') === 'false', 'Cancel new ringtone should stop preview');
        await add.click();
        assert(await file.inputValue() === '' && await page.locator('#ringtone-clip').isHidden(), 'Reopening Add should start empty');
        await cancel.click();
        await page.locator('.ringtone-disclosure').first().click();
        await source.click();
        const suggested = await duplicate.locator('input').inputValue();
        await duplicate.locator('input').fill('Discard this copy name');
        await duplicate.locator('[data-cancel-duplicate]').click();
        assert(await source.evaluate(node => document.activeElement === node), 'Focus should return to Create copy');
        await source.click();
        assert(await duplicate.locator('input').inputValue() === suggested, 'Canceled name must be discarded');
        await duplicate.locator('[data-cancel-duplicate]').click();

        await trim.click();
        await cancel.waitFor();
        await page.locator('#ringtone-name').fill('Discard this edit');
        await page.locator('#ringtone-preview').click();
        await cancel.click();
        assert(await page.locator('#ringtone-editor').isHidden(), 'Canceled trim should close');
        assert(await page.locator('#ringtone-preview').getAttribute('aria-pressed') === 'false', 'Preview should stop');
        assert(await trim.evaluate(node => document.activeElement === node), 'Focus should return to Trim a copy');
        await trim.click();
        await cancel.waitFor();
        assert(await page.locator('#ringtone-name').inputValue() === suggested, 'Canceled trim name must be discarded');
        await cancel.click();
        assert(writes.length === 0, 'Cancel must not write to the ringtone library');
    } finally {
        page.removeListener('request', record);
    }
}
