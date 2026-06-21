const BUFFER = 5;

export function setupIntersectionObserver({ load, unload }) {
    const observer = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            const container = entry.target;
            if (entry.isIntersecting) {
                load(container);
            } else {
                unload(container);
            }
        }
    }, {
        root: null,
        rootMargin: `${BUFFER * 100}% 0px`,
    });

    const allContainers = document.querySelectorAll('.page-container');
    allContainers.forEach(c => observer.observe(c));
}
