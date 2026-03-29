// mockData.js

// Generate a plausible mock dataset for TSMC
const generateMockData = () => {
    let basePrice = 750;
    const data = [];
    let currentTime = new Date('2024-01-01').getTime();
    
    // Generate 100 data points
    for (let i = 0; i < 100; i++) {
        const dateStr = new Date(currentTime).toISOString().split('T')[0];
        
        // Random walk
        const open = basePrice;
        const volatility = basePrice * 0.02; // 2% volatility
        const high = open + Math.random() * volatility;
        const low = open - Math.random() * volatility;
        const close = low + Math.random() * (high - low);
        
        data.push({
            time: dateStr,
            open: parseFloat(open.toFixed(2)),
            high: parseFloat(high.toFixed(2)),
            low: parseFloat(low.toFixed(2)),
            close: parseFloat(close.toFixed(2)),
        });
        
        // Update base price for next iteration to create a trend
        basePrice = close + (Math.random() > 0.4 ? 1.5 : -1); 
        
        // Add 1 day
        currentTime += 24 * 60 * 60 * 1000;
    }
    
    // Ensure the last few days reflect the "breakout" B1 signal described in UI
    const lastIdx = data.length - 1;
    data[lastIdx - 2].close = 860;
    data[lastIdx - 1].open = 860;
    data[lastIdx - 1].close = 875;
    data[lastIdx].open = 875;
    data[lastIdx].close = 894;
    data[lastIdx].high = 896;
    
    return data;
};

// Simple MA calculator
const calcMA = (data, period) => {
    const ma = [];
    window.stockData = data;
    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
            continue;
        }
        let sum = 0;
        for (let j = 0; j < period; j++) {
            sum += data[i - j].close;
        }
        ma.push({ time: data[i].time, value: sum / period });
    }
    return ma;
};

// Basic mock for Indicators
const generateKD = (data) => {
    return data.map((d, i) => ({
        time: d.time,
        k: 50 + Math.sin(i / 5) * 40,
        d: 50 + Math.sin(i / 5 - 0.5) * 35
    }));
};

const mockData = generateMockData();
const mockMA20 = calcMA(mockData, 20);
const mockMA60 = calcMA(mockData, 60);

const mockIndicators = {
    kd: generateKD(mockData),
    rsi: mockData.map((d, i) => ({ time: d.time, value: 50 + Math.cos(i / 4) * 30 }))
};
