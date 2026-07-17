/**
 * Ticker de cotações compartilhado (USD, EUR, BTC via AwesomeAPI).
 * Atualiza os valores in-place a cada 30s sem recarregar a página e sem
 * resetar a animação CSS (apenas nós de texto/classes são alterados).
 */
(function () {
    'use strict';

    const API_URL = 'https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL';
    const POLL_INTERVAL_MS = 30000;
    const CACHE_KEY = 'tickerData';
    const CACHE_TTL_MS = 30000;

    const CURRENCIES = [
        { key: 'USDBRL', label: '🇺🇸 USD:' },
        { key: 'EURBRL', label: '🇪🇺 EUR:' },
        { key: 'BTCBRL', label: '₿ BTC:' },
    ];

    const formatCurrency = (value) =>
        parseFloat(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    const formatPct = (pct) => (parseFloat(pct) > 0 ? `+${pct}%` : `${pct}%`);
    const getColorClass = (pct) => (parseFloat(pct) >= 0 ? 'ticker-up' : 'ticker-down');

    // Monta a estrutura uma única vez; depois só os textos são atualizados.
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
            if (!cached || Date.now() - cached.time > CACHE_TTL_MS) return null;
            return cached.data;
        } catch (e) {
            return null;
        }
    }

    function writeCache(data) {
        try {
            sessionStorage.setItem(CACHE_KEY, JSON.stringify({ time: Date.now(), data }));
        } catch (e) { /* storage indisponível: segue sem cache */ }
    }

    function init() {
        const tickerEl = document.getElementById('market-ticker');
        if (!tickerEl) return;

        // Limpa o cache de HTML do formato antigo.
        try {
            sessionStorage.removeItem('tickerHTML');
            sessionStorage.removeItem('tickerTime');
        } catch (e) { /* ignora */ }

        // Ticker com animação de rolagem repete os itens para preencher a faixa.
        const animated = getComputedStyle(tickerEl).animationName !== 'none';
        const repeat = animated ? 4 : 1;

        let hasData = false;

        async function update() {
            let data = readCache();
            if (!data) {
                try {
                    const res = await fetch(API_URL);
                    data = await res.json();
                    writeCache(data);
                } catch (error) {
                    if (!hasData) {
                        tickerEl.innerHTML = '<span class="ticker-item">Finanças News - Cotações em tempo real.</span>';
                    }
                    return;
                }
            }
            if (!hasData) {
                buildSkeleton(tickerEl, repeat);
                hasData = true;
            }
            render(tickerEl, data);
        }

        update();
        setInterval(update, POLL_INTERVAL_MS);

        // Atualiza imediatamente ao voltar para a aba.
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') update();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
