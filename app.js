document.addEventListener('DOMContentLoaded', () => {
    console.log('[InvestPro] War Room initializing...');

    // ── Tab Switching ──
    const tabs = document.querySelectorAll('.tab');
    const tabContents = document.querySelectorAll('.tab-content');

    const updateChartSizes = () => {
        setTimeout(() => {
            const mainEl = document.getElementById('mainChart');
            const w = mainEl ? mainEl.clientWidth : 400;
            if (mainChartObj) mainChartObj.applyOptions({ width: w });
            if (kdChartObj) kdChartObj.applyOptions({ width: w });
            if (rsiChartObj) rsiChartObj.applyOptions({ width: w });
        }, 50);
    };

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(tab.getAttribute('data-tab')).classList.add('active');
            updateChartSizes();
        });
    });

    // ── Chart Setup ──
    const chartOpts = {
        layout: { background: { type: 'solid', color: '#161b22' }, textColor: '#8b949e' },
        grid: { vertLines: { color: '#30363d' }, horzLines: { color: '#30363d' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#30363d' },
        timeScale: { borderColor: '#30363d', timeVisible: false, rightOffset: 12 },
    };

    let mainChartObj = LightweightCharts.createChart(document.getElementById('mainChart'), chartOpts);
    let candleSeries = mainChartObj.addCandlestickSeries({ upColor: '#ff3366', downColor: '#00ff88', borderVisible: false, wickUpColor: '#ff3366', wickDownColor: '#00ff88' });
    let ma20Series = mainChartObj.addLineSeries({ color: '#f6c343', lineWidth: 2, title: '20MA' });
    let ma60Series = mainChartObj.addLineSeries({ color: '#58a6ff', lineWidth: 2, title: '60MA' });

    let kdChartObj = LightweightCharts.createChart(document.getElementById('kdChart'), { ...chartOpts, rightPriceScale: { ...chartOpts.rightPriceScale, scaleMargins: { top: 0.1, bottom: 0.1 } } });
    let kSeries = kdChartObj.addLineSeries({ color: '#ff9900', lineWidth: 2, title: '%K' });
    let dSeries = kdChartObj.addLineSeries({ color: '#58a6ff', lineWidth: 2, title: '%D' });

    let rsiChartObj = LightweightCharts.createChart(document.getElementById('rsiChart'), { ...chartOpts, rightPriceScale: { ...chartOpts.rightPriceScale, scaleMargins: { top: 0.1, bottom: 0.1 } } });
    let rsiSeries = rsiChartObj.addLineSeries({ color: '#cc66ff', lineWidth: 2, title: 'RSI(14)' });

    window.addEventListener('resize', updateChartSizes);
    console.log('[InvestPro] Charts initialized.');

    // ── DOM references ──
    const API_STOCK = '/api/stock/';
    const API_SUGGEST = '/api/search?q=';
    const $ = id => document.getElementById(id);
    const suggestionsEl = $('searchSuggestions');
    const searchInput = $('searchInput');

    // ── Indicator Grid Builder ──
    function buildIndicatorGrid(grid) {
        const container = $('ui-indicator-grid');
        const items = [
            { label: '5MA', value: grid.ma5 },
            { label: '20MA', value: grid.ma20 },
            { label: '60MA', value: grid.ma60 },
            { label: 'RSI', value: grid.rsi },
            { label: 'K值', value: grid.k },
            { label: 'D值', value: grid.d },
            { label: '成交量', value: formatVolume(grid.volume) },
            { label: '20日均量', value: formatVolume(grid.vol_ma20) },
            { label: '支撐位', value: grid.support, cls: 'buy' },
            { label: '壓力位', value: grid.resistance, cls: 'sell' },
        ];
        container.innerHTML = items.map(i => `
            <div class="ind-cell">
                <span class="ind-cell-label">${i.label}</span>
                <span class="ind-cell-value" style="${i.cls === 'buy' ? 'color:var(--buy-color)' : i.cls === 'sell' ? 'color:var(--sell-color)' : ''}">${i.value}</span>
            </div>
        `).join('');
    }

    function formatVolume(v) {
        if (v >= 1e8) return (v / 1e8).toFixed(1) + '億';
        if (v >= 1e4) return (v / 1e4).toFixed(0) + '萬';
        return v.toLocaleString();
    }

    // ── Main Data Loader ──
    async function loadStock(ticker) {
        console.log('[InvestPro] Loading ticker:', ticker);
        suggestionsEl.style.display = 'none';
        $('ui-ticker').innerText = '載入中...';
        $('searchBtn').disabled = true;
        $('searchBtn').innerText = '⏳';

        try {
            const res = await fetch(API_STOCK + encodeURIComponent(ticker));
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            console.log('[InvestPro] Got', data.candles.length, 'candles');

            // ── PRICE HEADER ──
            const name = data.stock_name;
            window.currentStockData = { ticker: data.ticker, stock_name: name };
            if (window.checkFavoriteStatus) window.checkFavoriteStatus(data.ticker);

            $('ui-ticker').innerText = name
                ? `${name} (${data.ticker.toUpperCase()})`
                : data.ticker.toUpperCase();
            $('ui-currency').innerText = data.currency || '';
            $('ui-price').innerText = data.latest_price;
            const isPos = data.change >= 0;
            const sign = isPos ? '+' : '';
            $('ui-change').innerText = `${sign}${data.change} (${sign}${data.change_pct}%)`;
            $('ui-change').className = `change ${isPos ? 'positive' : 'negative'}`;

            // ── COMPOSITE SCORE ──
            const cs = data.strategy.composite_score;
            $('ui-composite-score').innerText = (cs > 0 ? '+' : '') + cs;
            const scoreBox = $('ui-score-box');
            if (cs >= 2) {
                scoreBox.style.borderColor = 'var(--buy-color)';
                $('ui-composite-score').style.color = 'var(--buy-color)';
            } else if (cs <= -2) {
                scoreBox.style.borderColor = 'var(--sell-color)';
                $('ui-composite-score').style.color = 'var(--sell-color)';
            } else {
                scoreBox.style.borderColor = 'var(--warn-color)';
                $('ui-composite-score').style.color = 'var(--warn-color)';
            }

            // ── GRANVILLE BANNER ──
            const isBuy = data.signal.type === 'buy';
            const banner = $('ui-granville-banner');
            banner.className = `granville-banner ${isBuy ? 'buy' : 'sell'}`;
            $('ui-granville-code').innerText = data.signal.granville_code;
            $('ui-granville-label').innerText = data.signal.granville_label;
            $('ui-overall-state').innerText = data.strategy.overall_state;
            $('ui-overall-state').style.color = isBuy ? 'var(--buy-color)' : 'var(--sell-color)';

            // ── STRATEGY CARDS ──
            $('ui-action').innerText = data.strategy.action;
            $('ui-timing').innerText = data.strategy.timing;
            $('ui-holder').innerText = data.strategy.holder_advice;

            // Color the action cards based on signal type
            const cardColor = isBuy ? 'var(--buy-color)' : 'var(--sell-color)';
            document.querySelectorAll('.strategy-card-body').forEach(el => {
                el.style.color = cardColor;
            });

            // ── SUPPORT / RESISTANCE ──
            $('ui-support').innerText = data.strategy.support;
            $('ui-resistance').innerText = data.strategy.resistance;
            $('ui-sr-price').innerText = data.latest_price;
            $('ui-support-dist').innerText = `距離 ${data.strategy.dist_to_support_pct}%`;
            $('ui-resistance-dist').innerText = `距離 ${data.strategy.dist_to_resistance_pct}%`;

            // ── RISK WARNINGS ──
            const riskSection = $('ui-risk-section');
            const riskList = $('ui-risks');
            const isNoRisk = data.strategy.risks.length === 1 && data.strategy.risks[0].includes('無重大');
            riskSection.classList.toggle('risk-safe', isNoRisk);
            riskList.innerHTML = data.strategy.risks.map(r => `<li>${r}</li>`).join('');

            // ── JUDGMENT BASIS ──
            $('ui-reasons').innerHTML = data.strategy.reasons.map(r => `<li>${r}</li>`).join('');

            // ── INDICATOR GRID ──
            buildIndicatorGrid(data.grid);

            // ── CHARTS ──
            candleSeries.setData(data.candles);
            ma20Series.setData(data.ma20);
            ma60Series.setData(data.ma60);
            kSeries.setData(data.indicators.kd.map(d => ({ time: d.time, value: d.k })));
            dSeries.setData(data.indicators.kd.map(d => ({ time: d.time, value: d.d })));
            rsiSeries.setData(data.indicators.rsi);
            mainChartObj.timeScale().fitContent();
            kdChartObj.timeScale().fitContent();
            rsiChartObj.timeScale().fitContent();
            console.log('[InvestPro] Render complete!');

        } catch (error) {
            console.error('[InvestPro] Error:', error);
            $('ui-ticker').innerText = '❌ 載入失敗';
            $('ui-action').innerText = '載入失敗。請確認代碼是否正確。';
        } finally {
            $('searchBtn').disabled = false;
            $('searchBtn').innerText = '查詢';
        }
    }

    // ── Autocomplete Logic ──
    function debounce(func, timeout = 300) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => { func.apply(this, args); }, timeout);
        };
    }

    const fetchSuggestions = debounce(async (query) => {
        if (query.length < 1) {
            suggestionsEl.style.display = 'none';
            return;
        }

        try {
            const res = await fetch(API_SUGGEST + encodeURIComponent(query));
            const data = await res.json();
            const quotes = data.quotes || [];

            if (quotes.length === 0) {
                suggestionsEl.style.display = 'none';
                return;
            }

            suggestionsEl.innerHTML = quotes.map(q => `
                <div class="suggestion-item" data-symbol="${q.symbol}">
                    <div class="suggestion-header">
                        <span class="suggestion-symbol">${q.symbol}</span>
                        <span class="suggestion-exch">${q.exchDisp}</span>
                    </div>
                    <div class="suggestion-name">${q.name}</div>
                </div>
            `).join('');

            suggestionsEl.style.display = 'block';

            // Click listener for items
            document.querySelectorAll('.suggestion-item').forEach(item => {
                item.addEventListener('click', () => {
                    const symbol = item.getAttribute('data-symbol');
                    searchInput.value = symbol;
                    loadStock(symbol);
                });
            });
        } catch (err) {
            console.error('[InvestPro] Suggestion error:', err);
        }
    });

    searchInput.addEventListener('input', e => fetchSuggestions(e.target.value.trim()));

    // Close suggestions on outside click
    document.addEventListener('click', (e) => {
        if (!suggestionsEl.contains(e.target) && e.target !== searchInput) {
            suggestionsEl.style.display = 'none';
        }
    });

    // ── Event Bindings ──
    $('searchBtn').addEventListener('click', () => {
        const val = searchInput.value.trim();
        if (val) loadStock(val);
    });
    searchInput.addEventListener('keypress', e => {
        if (e.key === 'Enter') { 
            const val = e.target.value.trim(); 
            if (val) loadStock(val);
            suggestionsEl.style.display = 'none';
        }
    });
    document.querySelectorAll('.chip').forEach(chip => {
        chip.addEventListener('click', e => {
            document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
            e.target.classList.add('active');
            const ticker = e.target.getAttribute('data-ticker');
            $('searchInput').value = ticker;
            loadStock(ticker);
        });
    });
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', e => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));

            e.target.classList.add('active');
            const tabId = e.target.getAttribute('data-tab');
            $(tabId).classList.add('active');

            // Force resize and fit content on newly visible charts
            if (tabId === 'tab-indicators') {
                const kdParent = $('kdChart');
                const rsiParent = $('rsiChart');
                kdChartObj.resize(kdParent.clientWidth, kdParent.clientHeight);
                rsiChartObj.resize(rsiParent.clientWidth, rsiParent.clientHeight);
                kdChartObj.timeScale().fitContent();
                rsiChartObj.timeScale().fitContent();
            } else if (tabId === 'tab-main') {
                const mainParent = $('mainChart');
                mainChartObj.resize(mainParent.clientWidth, mainParent.clientHeight);
                mainChartObj.timeScale().fitContent();
            }
        });
    });

    // ── FAVORITES SYSTEM ──
    let favorites = JSON.parse(localStorage.getItem('investpro_favorites')) || [];

    window.checkFavoriteStatus = function(ticker) {
        const btn = $('btn-favorite');
        btn.style.display = 'inline-flex';
        const isFav = favorites.some(f => f.ticker.toUpperCase() === ticker.toUpperCase());
        if (isFav) {
            btn.classList.add('active');
            btn.innerHTML = '★';
        } else {
            btn.classList.remove('active');
            btn.innerHTML = '☆';
        }
    };

    function renderFavorites() {
        const favContainer = $('ui-favorites-list');
        if (favorites.length === 0) {
            favContainer.style.display = 'none';
            return;
        }
        favContainer.style.display = 'flex';
        let html = `<span class="link-label">⭐ 最愛：</span>`;
        // Show newest favorites first
        [...favorites].reverse().forEach(f => {
            html += `<button class="chip" data-ticker="${f.ticker}">${f.name}</button>`;
        });
        favContainer.innerHTML = html;
        
        // Rebind click events to new chips
        favContainer.querySelectorAll('.chip').forEach(chip => {
            chip.addEventListener('click', e => {
                document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
                e.target.classList.add('active');
                const ticker = e.target.getAttribute('data-ticker');
                $('searchInput').value = ticker;
                loadStock(ticker);
            });
        });
    }

    $('btn-favorite').addEventListener('click', () => {
        const cur = window.currentStockData;
        if (!cur) return;
        const index = favorites.findIndex(f => f.ticker.toUpperCase() === cur.ticker.toUpperCase());
        if (index > -1) {
            favorites.splice(index, 1);
        } else {
            const shortName = (cur.stock_name && cur.stock_name !== 'null') ? cur.stock_name.split(' (')[0] : cur.ticker;
            favorites.push({ ticker: cur.ticker, name: shortName });
        }
        localStorage.setItem('investpro_favorites', JSON.stringify(favorites));
        window.checkFavoriteStatus(cur.ticker);
        renderFavorites();
    });

    renderFavorites();

    // ── Initial Load ──
    updateChartSizes();
    loadStock('2330.TW');
});
