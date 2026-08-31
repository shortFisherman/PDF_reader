import { getElements, createPageEl, calculatePlaceholderHeight, showError } from './modules/dom.js';
import { setupIntersectionObserver } from './modules/lazy-loader.js';
import { createSettleGate, setupPageDetection } from './modules/scroll-sync.js';
import { createAlignmentController } from './modules/alignment-controller.js';
import { fetchStageLabels, getStageLabel } from './modules/stages.js';
import { translateCurrentPage, translateBatch } from './modules/translator.js';
import { setupZoom } from './modules/zoom.js';
import { TranslationUIController } from './modules/translation-ui-controller.js';
import { createReaderSession } from './modules/reader-session.js';
import { createReaderAppController } from './modules/app-controller.js';
import { createConfigPanel } from './modules/config-panel.js';
import { createGlossaryPanel } from './modules/glossary-panel.js';

const controller = createReaderAppController({
    getElements,
    createPageEl,
    calculatePlaceholderHeight,
    showError,
    setupIntersectionObserver,
    createSettleGate,
    setupPageDetection,
    createAlignmentController,
    fetchStageLabels,
    getStageLabel,
    translateCurrentPage,
    translateBatch,
    setupZoom,
    TranslationUIController,
    createReaderSession,
    createConfigPanel,
    createGlossaryPanel,
});

controller.init();
