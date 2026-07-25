/**
 * Chart component using TradingView Lightweight Charts
 * Renders candlesticks with optional indicators
 */

import React, { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type LineData,
  type HistogramData,
} from 'lightweight-charts';
import type { Candle, IndicatorSeries } from '../types/market';
import './Chart.css';

interface ChartProps {
  candles: Candle[];
  indicators?: IndicatorSeries[];
  symbol?: string;
  timeframe?: string;
}

export const Chart: React.FC<ChartProps> = ({
  candles,
  indicators = [],
  symbol = 'BTCUSDT',
  timeframe = '1m',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const indicatorSeriesRef = useRef<Map<string, ISeriesApi<any>>>(new Map());

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#1a1a1a' },
        textColor: '#d1d5db',
        fontSize: 12,
        fontFamily: "'Inter', system-ui, sans-serif",
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      timeScale: {
        timeVisible: true,
        secondsVisible: true,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      rightPriceScale: {
        autoScale: true,
        borderColor: '#444',
      },
      crosshair: {
        mode: 0, // CrosshairMode.Normal
        vertColor: '#666',
        horzColor: '#666',
      },
      grid: {
        vertLines: { color: '#1f1f1f', style: 1 }, // LightGray
        horzLines: { color: '#1f1f1f', style: 1 },
      },
    });

    chartRef.current = chart;

    // Create candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      borderVisible: false,
      openTickMark: false,
    });

    candleSeriesRef.current = candleSeries;

    // Add volume
    const volumeSeries = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: 'volume',
    });

    chart.priceScale('volume').applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    // Handle window resize
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
        chart.timeScale().fitContent();
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, []);

  // Update candlestick data
  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    const candleData: CandlestickData[] = candles.map((candle) => ({
      time: Math.floor(candle.time / 1000), // Convert to seconds for Lightweight Charts
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    }));

    const volumeData: HistogramData[] = candles.map((candle) => ({
      time: Math.floor(candle.time / 1000),
      value: candle.volume,
      color: candle.close >= candle.open ? '#26a69a' : '#ef5350',
    }));

    candleSeriesRef.current.setData(candleData);
    
    // Update volume series
    const chart = chartRef.current;
    if (chart) {
      const volumeSeries = chart.series()[1]; // Assuming volume is second series
      if (volumeSeries && volumeSeries.seriesType() === 'Histogram') {
        (volumeSeries as any).setData(volumeData);
      }
    }

    // Fit content to view
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent();
    }
  }, [candles]);

  // Update indicator data
  useEffect(() => {
    if (!chartRef.current) return;

    const chart = chartRef.current;
    const existingIndicators = new Set(indicatorSeriesRef.current.keys());

    // Add or update indicators
    indicators.forEach((indicator) => {
      if (!indicatorSeriesRef.current.has(indicator.name)) {
        // Create new indicator series
        let series: ISeriesApi<any>;

        if (indicator.type === 'line') {
          series = chart.addLineSeries({
            color: indicator.color,
            lineWidth: indicator.width || 2,
            title: indicator.name,
          });
        } else {
          series = chart.addHistogramSeries({
            color: indicator.color,
            title: indicator.name,
            priceScaleId: `indicator-${indicator.name}`,
          });
        }

        indicatorSeriesRef.current.set(indicator.name, series);
        existingIndicators.delete(indicator.name);
      }

      // Update data
      const series = indicatorSeriesRef.current.get(indicator.name)!;
      const data = indicator.data.map((point) => ({
        time: Math.floor(point.time / 1000),
        value: point.value,
      }));
      series.setData(data as any);
    });

    // Remove indicators that are no longer in the list
    existingIndicators.forEach((indicatorName) => {
      const series = indicatorSeriesRef.current.get(indicatorName);
      if (series) {
        chart.removeSeries(series);
        indicatorSeriesRef.current.delete(indicatorName);
      }
    });
  }, [indicators]);

  return (
    <div className="chart-container">
      <div className="chart-header">
        <span className="chart-title">
          {symbol} • {timeframe}
        </span>
      </div>
      <div ref={containerRef} className="chart-content" />
    </div>
  );
};
