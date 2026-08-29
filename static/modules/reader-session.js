/**
 * 文档级资源 session 边界（P2-02）。
 *
 * 一个 session 持有打开一份 PDF 后创建的 zoom/alignment/intersection
 * observer/settle gate/page 生命周期清理函数；dispose 只执行一次且幂等。
 * app.js 只在新文档 open 成功、准备替换 DOM 时才 dispose 旧 session，
 * 因此失败打开不会销毁仍在使用的旧文档资源。
 */

export function createReaderSession({ zoom, alignment, io, settle, progressCleanup }) {
    let disposed = false;
    return {
        get disposed() {
            return disposed;
        },
        dispose() {
            if (disposed) {
                return;
            }
            disposed = true;
            if (zoom && typeof zoom.dispose === 'function') {
                zoom.dispose();
            }
            if (alignment && typeof alignment.dispose === 'function') {
                alignment.dispose();
            }
            if (io && io.observer && typeof io.observer.disconnect === 'function') {
                io.observer.disconnect();
            }
            if (settle && typeof settle.dispose === 'function') {
                settle.dispose();
            }
            if (progressCleanup) {
                progressCleanup();
            }
        },
    };
}
