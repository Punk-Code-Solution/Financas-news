/**
 * Ticker de cotações via AwesomeAPI (estilo Cointelegraph).
 * Componente isolado: preenche #market-ticker, atualiza valores in-place
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

    const POLL_INTERVAL_MS = 20000;
    const CACHE_KEY = 'tickerData_v3';
    const CACHE_TTL_MS = 15000;
    /** Cópias do grupo — garante faixa larga o bastante para loop sem buracos. */
    const GROUP_COPIES = 2;
    /** Repetições internas do conjunto de pares dentro de cada grupo. */
    const SET_REPEAT = 2;

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
        // Força reflow para reiniciar a animação CSS.
        void el.offsetWidth;
        el.classList.add('is-flash');
    }

    function makeItem(pair) {
        const item = document.createElement('span');
        item.className = 'fn-ticker__item';

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

    function render(tickerEl, data, animateChanges) {
        PAIRS.forEach(({ key }) => {
            const quote = data[key];
            if (!quote) return;
            const bidText = formatCurrency(quote.bid);
            const pctText = `(${formatPct(quote.pctChange)})`;
            const pctClass = getColorClass(quote.pctChange);

            tickerEl.querySelectorAll(`[data-ticker-bid="${key}"]`).forEach((el) => {
                const changed = animateChanges && el.textContent && el.textContent !== '—' && el.textContent !== bidText;
                el.textContent = bidText;
                if (changed) flash(el);
            });
            tickerEl.querySelectorAll(`[data-ticker-pct="${key}"]`).forEach((el) => {
                const changed =
                    animateChanges &&
                    el.textContent &&
                    el.textContent !== pctText;
                el.className = `fn-ticker__pct ${pctClass}`;
                el.textContent = pctText;
                if (changed) flash(el);
            });
        });
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
        } catch (e) {
            /* ignora */
        }

        // Estrutura imediata (sem texto de loading) — placeholders "—" até a API responder.
        buildSkeleton(tickerEl);

        let hasData = false;
        let fetching = false;

        async function update(forceNetwork) {
            if (fetching) return;
            fetching = true;
            try {
                const data = await fetchQuotes(Boolean(forceNetwork));
                render(tickerEl, data, hasData);
                hasData = true;
            } catch (error) {
                // Mantém placeholders / último valor — sem mensagem de erro na barra.
            } finally {
                fetching = false;
            }
        }

        const cached = readCache();
        if (cached) {
            render(tickerEl, cached, false);
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
