const API = '/api';
let pageCount = 0;
let pageHeight = 0;
let pageWidth = 0;
let currentPage = 0;
let isTranslating = false;
let promptVisible = false;

const leftCol = document.getElementById('left-column');
const rightCol = document.getElementById('right-column');
const pageIndicator = document.getElementById('page-indicator');
const translateBtn = document.getElementById('translate-btn');
const promptInput = document.getElementById('prompt-input');
const promptToggle = document.getElementById('prompt-toggle');
const progressBar = document.getElementById('progress-bar');
const progressFill = document.getElementById('progress-fill');
const fileArea = document.getElementById('file-input-area');
const appView = document.getElementById('app');
const toolbar = document.getElementById('toolbar');

document.getElementById('open-btn').addEventListener('click', openPdf);
document.getElementById('pdf-path').addEventListener('keydown', e => {
    if (e.key === 'Enter') openPdf();
});
promptToggle.addEventListener('click', () => {
    promptVisible = !promptVisible;
    promptInput.style.display = promptVisible ? 'inline-block' : 'none';
    promptToggle.textContent = promptVisible ? '- Prompt' : '+ Prompt';
});
translateBtn.addEventListener('click', translateCurrentPage);

function calculatePlaceholderHeight() {
    if (pageWidth && pageHeight) {
        const ratio = pageHeight / pageWidth;
        return Math.round(100 * ratio);
    }
    return 600;
}

async function openPdf() {
    const path = document.getElementById('pdf-path').value.trim();
    if (!path) return;

    try {
        const resp = await fetch(`${API}/open`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });

        if (!resp.ok) {
            const errText = await resp.text();
            let errMsg = 'Failed to open PDF';
            try {
                const errData = JSON.parse(errText);
                errMsg = errData.error || errMsg;
            } catch (e) {}
            fileArea.insertAdjacentHTML('beforeend', `<p style="color:#e55;margin-top:10px">${errMsg}</p>`);
            return;
        }

        const data = await resp.json();
        pageCount = data.page_count;
        pageHeight = data.page_height;
        pageWidth = data.page_width;

        leftCol.innerHTML = '';
        rightCol.innerHTML = '';

        for (let i = 0; i < pageCount; i++) {
            leftCol.appendChild(createPageEl(i, 'left'));
            rightCol.appendChild(createPageEl(i, 'right'));
        }

        fileArea.classList.add('hidden');
        appView.classList.remove('hidden');
        toolbar.classList.remove('hidden');

        setupIntersectionObserver();
        setupScrollSync();
        setupPageDetection();
        loadTranslatedState();
    } catch (e) {
        fileArea.insertAdjacentHTML('beforeend', `<p style="color:#e55;margin-top:10px">Network error: ${e.message}</p>`);
    }
}

async function loadTranslatedState() {
    try {
        const resp = await fetch(`${API}/translated-pages`);
        if (!resp.ok) return;
        const data = await resp.json();
        data.pages.forEach(p => {
            const el = rightCol.querySelector(`.page-container[data-page="${p}"]`);
            if (el) el.classList.add('translated');
        });
    } catch (e) {}
}

function createPageEl(pageNum, side) {
    const container = document.createElement('div');
    container.className = 'page-container';
    container.dataset.page = pageNum;
    container.dataset.side = side;

    const ph = calculatePlaceholderHeight();

    const placeholder = document.createElement('div');
    placeholder.className = 'page-placeholder';
    placeholder.style.paddingBottom = `${ph}%`;
    placeholder.textContent = `Page ${pageNum + 1}`;
    placeholder.dataset.loaded = 'false';
    container.appendChild(placeholder);

    return container;
}

function loadPageImage(container) {
    const page = parseInt(container.dataset.page);
    const side = container.dataset.side;
    const placeholder = container.querySelector('.page-placeholder');

    if (placeholder && placeholder.dataset.loaded === 'true') return;

    const img = document.createElement('img');
    img.src = `${API}/page/${side}/${page}?t=${Date.now()}`;
    img.onload = () => {
        if (placeholder) {
            placeholder.replaceWith(img);
        }
    };
    img.onerror = () => {
        if (placeholder) {
            placeholder.textContent = `Page ${page + 1} (error)`;
        }
    };

    if (placeholder) {
        placeholder.dataset.loaded = 'true';
        container.insertBefore(img, placeholder);
    }
}

function unloadPageImage(container) {
    const img = container.querySelector('img');
    if (!img) return;

    const placeholder = document.createElement('div');
    placeholder.className = 'page-placeholder';
    const ph = calculatePlaceholderHeight();
    placeholder.style.paddingBottom = `${ph}%`;
    placeholder.textContent = `Page ${parseInt(container.dataset.page) + 1}`;
    placeholder.dataset.loaded = 'false';

    img.replaceWith(placeholder);
}

function setupIntersectionObserver() {
    const BUFFER = 5;

    const observer = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            const container = entry.target;
            if (entry.isIntersecting) {
                loadPageImage(container);
            } else {
                unloadPageImage(container);
            }
        }
    }, {
        root: null,
        rootMargin: `${BUFFER * 100}% 0px`,
    });

    const allContainers = document.querySelectorAll('.page-container');
    allContainers.forEach(c => observer.observe(c));
}

function setupScrollSync() {
    let syncing = false;

    leftCol.addEventListener('scroll', () => {
        if (!syncing) {
            syncing = true;
            rightCol.scrollTop = leftCol.scrollTop;
            requestAnimationFrame(() => { syncing = false; });
        }
    });
}

function setupPageDetection() {
    const col = leftCol;
    col.addEventListener('scroll', () => {
        const containers = col.querySelectorAll('.page-container');
        let bestPage = 0;
        let bestCoverage = 0;
        const viewTop = col.scrollTop;
        const viewBottom = viewTop + col.clientHeight;

        containers.forEach(c => {
            const rect = c.getBoundingClientRect();
            const colRect = col.getBoundingClientRect();
            const top = rect.top - colRect.top + col.scrollTop;
            const bottom = top + rect.height;
            const overlap = Math.min(bottom, viewBottom) - Math.max(top, viewTop);
            const coverage = overlap / rect.height;
            if (coverage > bestCoverage) {
                bestCoverage = coverage;
                bestPage = parseInt(c.dataset.page);
            }
        });

        if (bestPage !== currentPage) {
            currentPage = bestPage;
            pageIndicator.textContent = `Page ${bestPage + 1}`;
        }
    });
}

async function translateCurrentPage() {
    if (isTranslating) return;
    isTranslating = true;
    translateBtn.disabled = true;
    translateBtn.textContent = 'Translating...';
    progressBar.classList.add('active');
    progressFill.style.width = '0%';

    const prompt = promptInput.value.trim() || null;

    try {
        const resp = await fetch(`${API}/translate/${currentPage}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt })
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Translation failed');
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const evt = JSON.parse(line.slice(6));
                        if (evt.type === 'progress') {
                            progressFill.style.width = `${evt.progress}%`;
                        } else if (evt.type === 'finish') {
                            progressFill.style.width = '100%';
                        } else if (evt.type === 'error') {
                            throw new Error(evt.error);
                        }
                    } catch (e) {
                        if (e instanceof SyntaxError) {
                            continue;
                        }
                        throw e;
                    }
                }
            }
        }

        const rightEl = rightCol.querySelector(`.page-container[data-page="${currentPage}"]`);
        if (rightEl) {
            unloadPageImage(rightEl);
            loadPageImage(rightEl);
            rightEl.classList.add('translated');
        }
        loadTranslatedState();

    } catch (e) {
        fileArea.classList.remove('hidden');
        fileArea.insertAdjacentHTML('beforeend', `<p style="color:#e55;margin-top:10px">Translation error: ${e.message}</p>`);
    } finally {
        isTranslating = false;
        translateBtn.disabled = false;
        translateBtn.textContent = 'Translate';
        progressBar.classList.remove('active');
    }
}
