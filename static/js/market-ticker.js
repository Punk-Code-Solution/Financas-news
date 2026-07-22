/**
 * Ticker de cotações compartilhado (USD, EUR, BTC via AwesomeAPI).
 * Atualiza os valores in-place a cada 20s sem recarregar a página e sem
 * resetar a animação CSS (apenas nós de texto/classes são alterados).
 */
(function () {
    'use strict';

    const API_URL = 'https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL';
    const POLL_INTERVAL_MS = 20000;
    const CACHE_KEY = 'tickerData_v2';
    const CACHE_TTL_MS = 15000;

    const CURRENCIES = [
        { key: 'USDBRL', label: '🇺🇸 USD:' },
        { key: 'EURBRL', label: '🇪🇺 EUR:' },
        { key: 'BTCBRL', label: '₿ BTC:' },
    ];

    const resolveLocale = () => {
        const root = document.documentElement;
        const ticker = document.getElementById('market-ticker');
        return (ticker && ticker.getAttribute('data-locale'))
            || root.getAttribute('data-locale')
            || root.getAttribute('lang')
            || 'pt-BR';
    };

    const formatCurrency = (value) =>
        parseFloat(value).toLocaleString(resolveLocale(), { style: 'currency', currency: 'BRL' });
    const formatPct = (pct) => (parseFloat(pct) > 0 ? `+${pct}%` : `${pct}%`);
    const getColorClass = (pct) => (parseFloat(pct) >= 0 ? 'ticker-up' : 'ticker-down');

    function buildSkeleton(tickerEl, repeat) {
        const frag = document.createDocumentFragment();
        for (let i = 0; i < repeat; i++) {
            CURRENCIES.forEach(({ key, label }) => {
                const item = document.createElement('span');
                item.className = 'ticker-item';

                const labelEl = document.createElement('span');
                labelEl.className = 'text-slate-400';
                labelEl.textContent = label;

                const bidEl = document.createElement('span');
                bidEl.setAttribute('data-ticker-bid', key);

                const pctEl = document.createElement('span');
                pctEl.setAttribute('data-ticker-pct', key);

                item.append(labelEl, ' ', bidEl, ' ', pctEl);
                frag.appendChild(item);
            });
        }
        tickerEl.replaceChildren(frag);
    }

    function render(tickerEl, data) {
        CURRENCIES.forEach(({ key }) => {
            const quote = data[key];
            if (!quote) return;
            tickerEl.querySelectorAll(`[data-ticker-bid="${key}"]`).forEach((el) => {
                el.textContent = formatCurrency(quote.bid);
            });
            tickerEl.querySelectorAll(`[data-ticker-pct="${key}"]`).forEach((el) => {
                el.className = getColorClass(quote.pctChange);
                el.textContent = `(${formatPct(quote.pctChange)})`;
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
            sessionStorage.setItem(CACHE_KEY, JSON.stringify({ time: Date.now(), data }));
        } catch (e) { /* storage indisponível */ }
    }

    function isAnimated(tickerEl) {
        if (tickerEl.dataset.tickerAnimated === 'true') return true;
        const name = getComputedStyle(tickerEl).animationName || '';
        return name !== 'none' && name !== '';
    }

    async function fetchQuotes(forceNetwork) {
        if (!forceNetwork) {
            const cached = readCache();
            if (cached) return cached;
        }
        const res = await fetch(`${API_URL}?_=${Date.now()}`, { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        writeCache(data);
        return data;
    }

    function init() {
        const tickerEl = document.getElementById('market-ticker');
        if (!tickerEl) return;

        try {
            sessionStorage.removeItem('tickerHTML');
            sessionStorage.removeItem('tickerTime');
            sessionStorage.removeItem('tickerData');
        } catch (e) { /* ignora */ }

        const repeat = isAnimated(tickerEl) ? 4 : 1;
        let hasData = false;
        let fetching = false;

        async function update(forceNetwork) {
            if (fetching) return;
            fetching = true;
            try {
                const data = await fetchQuotes(Boolean(forceNetwork));
                if (!hasData) {
                    buildSkeleton(tickerEl, repeat);
                    hasData = true;
                }
                render(tickerEl, data);
            } catch (error) {
                if (!hasData) {
                    tickerEl.innerHTML = '<span class="ticker-item">Finanças News - Cotações em tempo real.</span>';
                }
            } finally {
                fetching = false;
            }
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
