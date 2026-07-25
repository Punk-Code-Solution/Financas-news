/**
 * Ticker de cotações via AwesomeAPI (estilo Cointelegraph).
 * Componente isolado: atualiza cada item ao passar na viewport,
 * sem resetar a animação e sem mensagem de carregamento.
 */
(function () {
    'use strict';

    const PAIRS = [
        { key: 'USDBRL', symbol: 'USD' },
        { key: 'EURBRL', symbol: 'EUR' },
        { key: 'GBPBRL', symbol: 'GBP' },
        { key: 'BTCBRL', symbol: 'BTC' },
        { key: 'ETHBRL', symbol: 'ETH' },
        { key: 'SOLBRL', symbol: 'SOL' },
        { key: 'XRPBRL', symbol: 'XRP' },
        { key: 'DOGEBRL', symbol: 'DOGE' },
        { key: 'LTCBRL', symbol: 'LTC' },
        { key: 'CADBRL', symbol: 'CAD' },
        { key: 'AUDBRL', symbol: 'AUD' },
        { key: 'JPYBRL', symbol: 'JPY' },
        { key: 'CHFBRL', symbol: 'CHF' },
        { key: 'CNYBRL', symbol: 'CNY' },
        { key: 'ARSBRL', symbol: 'ARS' },
    ];

    const API_URL =
        'https://economia.awesomeapi.com.br/last/' +
        PAIRS.map((p) => p.key.replace(/BRL$/, '-BRL')).join(',');

    const POLL_INTERVAL_MS = 10000;
    const CACHE_KEY = 'tickerData_v5';
    const CACHE_TTL_MS = 8000;
    const GROUP_COPIES = 2;
    const SET_REPEAT = 2;
    const ITEM_UPDATE_COOLDOWN_MS = 1600;

    let latestQuotes = null;

    const resolveLocale = () => {
        const root = document.documentElement;
        const ticker = document.getElementById('market-ticker');
        return (
            (ticker && ticker.getAttribute('data-locale')) ||
            root.getAttribute('data-locale') ||
            root.getAttribute('lang') ||
            'pt-BR'
        );
    };

    const formatCurrency = (value) => {
        const n = parseFloat(value);
        const digits = !Number.isFinite(n) || n >= 0.01 ? 2 : 4;
        return n.toLocaleString(resolveLocale(), {
            style: 'currency',
            currency: 'BRL',
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        });
    };

    const formatPct = (pct) => {
        const n = parseFloat(pct);
        if (Number.isNaN(n)) return '';
        const abs = Math.abs(n).toFixed(2);
        if (n > 0) return `+${abs}%`;
        if (n < 0) return `-${abs}%`;
        return `${abs}%`;
    };

    const getColorClass = (pct) =>
        parseFloat(pct) >= 0 ? 'ticker-up' : 'ticker-down';

    function flash(el) {
        if (!el) return;
        el.classList.remove('is-flash');
        void el.offsetWidth;
        el.classList.add('is-flash');
    }

    function makeItem(pair) {
        const item = document.createElement('span');
        item.className = 'fn-ticker__item';
        item.setAttribute('data-ticker-key', pair.key);
        item.dataset.lastPaint = '0';

        const codeEl = document.createElement('span');
        codeEl.className = 'fn-ticker__code';
        codeEl.textContent = `${pair.symbol}:`;

        const bidEl = document.createElement('span');
        bidEl.className = 'fn-ticker__bid';
        bidEl.setAttribute('data-ticker-bid', pair.key);
        bidEl.textContent = '—';

        const pctEl = document.createElement('span');
        pctEl.className = 'fn-ticker__pct';
        pctEl.setAttribute('data-ticker-pct', pair.key);
        pctEl.textContent = '';

        item.append(codeEl, bidEl, pctEl);
        return item;
    }

    function makeGroup() {
        const group = document.createElement('div');
        group.className = 'fn-ticker__group';
        for (let r = 0; r < SET_REPEAT; r++) {
            PAIRS.forEach((pair) => group.appendChild(makeItem(pair)));
        }
        return group;
    }

    function buildSkeleton(tickerEl) {
        const frag = document.createDocumentFragment();
        for (let i = 0; i < GROUP_COPIES; i++) {
            frag.appendChild(makeGroup());
        }
        tickerEl.replaceChildren(frag);
    }

    function paintItem(item, animate) {
        if (!latestQuotes || !(item instanceof HTMLElement)) return;
        const key = item.getAttribute('data-ticker-key');
        const quote = latestQuotes[key];
        if (!quote) return;

        const now = Date.now();
        const lastPaint = Number(item.dataset.lastPaint || 0);
        if (animate && now - lastPaint < ITEM_UPDATE_COOLDOWN_MS) return;

        const bidEl = item.querySelector('[data-ticker-bid]');
        const pctEl = item.querySelector('[data-ticker-pct]');
        if (!bidEl || !pctEl) return;

        const bidText = formatCurrency(quote.bid);
        const pctText = `(${formatPct(quote.pctChange)})`;
        const pctClass = getColorClass(quote.pctChange);

        bidEl.textContent = bidText;
        pctEl.className = `fn-ticker__pct ${pctClass}`;
        pctEl.textContent = pctText;
        item.dataset.lastPaint = String(now);

        if (animate) {
            flash(bidEl);
            flash(pctEl);
            item.classList.toggle('is-tick-up', pctClass === 'ticker-up');
            item.classList.toggle('is-tick-down', pctClass === 'ticker-down');
            item.classList.remove('is-passing');
            void item.offsetWidth;
            item.classList.add('is-passing');
            window.clearTimeout(Number(item.dataset.passTimer || 0));
            item.dataset.passTimer = String(
                window.setTimeout(() => {
                    item.classList.remove('is-passing', 'is-tick-up', 'is-tick-down');
                }, 850)
            );
        }
    }

    function paintAll(tickerEl, animate) {
        tickerEl.querySelectorAll('.fn-ticker__item').forEach((item) => {
            paintItem(item, animate);
        });
    }

    function watchPassingItems(tickerEl) {
        const viewport = tickerEl.closest('.fn-ticker__viewport');
        if (!viewport) return;
        const wasVisible = new WeakMap();

        function tick() {
            window.requestAnimationFrame(tick);
            if (document.visibilityState === 'hidden' || !latestQuotes) return;

            const root = viewport.getBoundingClientRect();
            tickerEl.querySelectorAll('.fn-ticker__item').forEach((item) => {
                const box = item.getBoundingClientRect();
                const visible =
                    box.right > root.left + 4 &&
                    box.left < root.right - 4 &&
                    box.bottom > root.top &&
                    box.top < root.bottom;
                const prev = wasVisible.get(item) === true;
                if (visible && !prev) paintItem(item, true);
                wasVisible.set(item, visible);
            });
        }

        window.requestAnimationFrame(tick);
    }

    function readCache() {
        try {
            const raw = sessionStorage.getItem(CACHE_KEY);
            if (!raw) return null;
            const cached = JSON.parse(raw);
            if (!cached || Date.now() - cached.time >= CACHE_TTL_MS) return null;
            return cached.data;
        } catch (e) {
            return null;
        }
    }

    function writeCache(data) {
        try {
            sessionStorage.setItem(
                CACHE_KEY,
                JSON.stringify({ time: Date.now(), data })
            );
        } catch (e) {
            /* storage indisponível */
        }
    }

    async function fetchQuotes(forceNetwork) {
        if (!forceNetwork) {
            const cached = readCache();
            if (cached) return cached;
        }
        const res = await fetch(`${API_URL}?_=${Date.now()}`, {
            cache: 'no-store',
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        writeCache(data);
        return data;
    }

    function init() {
        const tickerEl = document.getElementById('market-ticker');
        if (!tickerEl) return;

        // Permite reinicializar se um JS antigo em cache já tiver marcado ready.
        if (tickerEl.dataset.tickerReady === '1' && tickerEl.querySelector('.fn-ticker__item')) {
            return;
        }
        tickerEl.dataset.tickerReady = '1';

        try {
            sessionStorage.removeItem('tickerHTML');
            sessionStorage.removeItem('tickerTime');
            sessionStorage.removeItem('tickerData');
            sessionStorage.removeItem('tickerData_v2');
            sessionStorage.removeItem('tickerData_v3');
            sessionStorage.removeItem('tickerData_v4');
        } catch (e) {
            /* ignora */
        }

        buildSkeleton(tickerEl);
        watchPassingItems(tickerEl);

        let hasData = false;
        let fetching = false;

        async function update(forceNetwork) {
            if (fetching) return;
            fetching = true;
            try {
                const data = await fetchQuotes(Boolean(forceNetwork));
                latestQuotes = data;
                if (!hasData) paintAll(tickerEl, false);
                hasData = true;
            } catch (error) {
                // Mantém placeholders / último valor.
            } finally {
                fetching = false;
            }
        }

        const cached = readCache();
        if (cached) {
            latestQuotes = cached;
            paintAll(tickerEl, false);
            hasData = true;
        }

        update(true);
        setInterval(() => update(true), POLL_INTERVAL_MS);

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') update(true);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
