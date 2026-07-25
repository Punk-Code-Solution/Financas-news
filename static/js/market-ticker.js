/**
 * Ticker de cotações via AwesomeAPI (estilo Cointelegraph).
 * Componente isolado: atualiza cada item ao passar na viewport,
 * sem resetar a animação e sem mensagem de carregamento.
 */
(function () {
    'use strict';

    const PAIRS = [
        { key: 'USDBRL', code: 'US', symbol: 'USD' },
        { key: 'EURBRL', code: 'EU', symbol: 'EUR' },
        { key: 'GBPBRL', code: 'GB', symbol: 'GBP' },
        { key: 'BTCBRL', code: 'B', symbol: 'BTC' },
        { key: 'ETHBRL', code: 'E', symbol: 'ETH' },
        { key: 'SOLBRL', code: 'S', symbol: 'SOL' },
        { key: 'XRPBRL', code: 'X', symbol: 'XRP' },
        { key: 'DOGEBRL', code: 'D', symbol: 'DOGE' },
        { key: 'LTCBRL', code: 'L', symbol: 'LTC' },
        { key: 'CADBRL', code: 'CA', symbol: 'CAD' },
        { key: 'AUDBRL', code: 'AU', symbol: 'AUD' },
        { key: 'JPYBRL', code: 'JP', symbol: 'JPY' },
        { key: 'CHFBRL', code: 'CH', symbol: 'CHF' },
        { key: 'CNYBRL', code: 'CN', symbol: 'CNY' },
        { key: 'ARSBRL', code: 'AR', symbol: 'ARS' },
    ];

    const API_URL =
        'https://economia.awesomeapi.com.br/last/' +
        PAIRS.map((p) => p.key.replace(/BRL$/, '-BRL')).join(',');

    const POLL_INTERVAL_MS = 10000;
    const CACHE_KEY = 'tickerData_v4';
    const CACHE_TTL_MS = 8000;
    /** Cópias do grupo — garante faixa larga o bastante para loop sem buracos. */
    const GROUP_COPIES = 2;
    /** Repetições internas do conjunto de pares dentro de cada grupo. */
    const SET_REPEAT = 2;
    /** Evita piscar o mesmo item várias vezes seguidas. */
    const ITEM_UPDATE_COOLDOWN_MS = 1800;

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
        const raw = String(pct);
        return n > 0 ? `+${raw}%` : `${raw}%`;
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
        codeEl.textContent = `${pair.code} ${pair.symbol}:`;

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
        const prevBid = bidEl.textContent;
        const prevPct = pctEl.textContent;
        const changed =
            (prevBid && prevBid !== '—' && prevBid !== bidText) ||
            (prevPct && prevPct !== pctText);

        bidEl.textContent = bidText;
        pctEl.className = `fn-ticker__pct ${pctClass}`;
        pctEl.textContent = pctText;
        item.dataset.lastPaint = String(now);

        // Sempre anima ao passar na tela (efeito “ao vivo”); reforça se o valor mudou.
        if (animate) {
            flash(bidEl);
            flash(pctEl);
            item.classList.toggle('is-tick-up', pctClass === 'ticker-up');
            item.classList.toggle('is-tick-down', pctClass === 'ticker-down');
            item.classList.remove('is-passing');
            void item.offsetWidth;
            item.classList.add('is-passing');
            if (changed) item.classList.add('is-changed');
            else item.classList.remove('is-changed');
            window.clearTimeout(Number(item.dataset.passTimer || 0));
            item.dataset.passTimer = String(
                window.setTimeout(() => {
                    item.classList.remove('is-passing', 'is-changed', 'is-tick-up', 'is-tick-down');
                }, 900)
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
                    box.right > root.left + 8 &&
                    box.left < root.right - 8 &&
                    box.bottom > root.top &&
                    box.top < root.bottom;
                const prev = wasVisible.get(item) === true;
                if (visible && !prev) {
                    paintItem(item, true);
                }
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
        if (!tickerEl || tickerEl.dataset.tickerReady === '1') return;
        tickerEl.dataset.tickerReady = '1';

        try {
            sessionStorage.removeItem('tickerHTML');
            sessionStorage.removeItem('tickerTime');
            sessionStorage.removeItem('tickerData');
            sessionStorage.removeItem('tickerData_v2');
            sessionStorage.removeItem('tickerData_v3');
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
                // Primeira carga: pinta tudo quieto. Depois só o observer anima ao passar.
                if (!hasData) paintAll(tickerEl, false);
                hasData = true;
            } catch (error) {
                // Mantém placeholders / último valor — sem mensagem de erro na barra.
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
