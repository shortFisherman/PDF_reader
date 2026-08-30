const FALLBACK_LABELS = {
    layout_analysis: '正在分析版面…',
    translating: '正在翻译…',
    generating_pdf: '正在生成译文…',
    generating_pdf_bilingual: '正在生成译文…',
    glossary_retry: '术语合规检查未通过，正在重试…',
    finish: '翻译完成',
};

let _cache = null;

export async function fetchStageLabels() {
    if (_cache) return _cache;

    try {
        const resp = await fetch('/api/stages');
        if (!resp.ok) throw new Error('fetch stages failed');
        _cache = await resp.json();
        return _cache;
    } catch (e) {
        console.warn('Failed to fetch /api/stages, using fallback labels:', e);
        _cache = FALLBACK_LABELS;
        return _cache;
    }
}

export function getStageLabel(stage) {
    const labels = _cache || FALLBACK_LABELS;
    return labels[stage] || stage;
}
