import { useEffect, useMemo, useRef } from 'react';
import {
  ColorType,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from 'lightweight-charts';
import type { Candle } from '../../types/market';

interface MarketChartProps {
  candles: Candle[];
  movingAverage: Array<{ time: number; value: number }>;
  showIndicators: boolean;
  showVolume: boolean;
}

export function MarketChart({
  candles,
  movingAverage,
  showIndicators,
  showVolume,
}: MarketChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const movingAverageSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);

  const candleData = useMemo<CandlestickData[]>(
    () =>
      candles.map((candle) => ({
        time: toChartTime(candle.time),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    [candles]
  );

  const volumeData = useMemo<HistogramData[]>(
    () =>
      candles.map((candle) => ({
        time: toChartTime(candle.time),
        value: candle.volume,
        color: candle.close >= candle.open ? 'rgba(30, 215, 160, 0.32)' : 'rgba(255, 107, 129, 0.28)',
      })),
    [candles]
  );

  const movingAverageData = useMemo<LineData[]>(
    () =>
      movingAverage.map((point) => ({
        time: toChartTime(point.time),
        value: point.value,
      })),
    [movingAverage]
  );

  function toChartTime(time: number): Time {
    return Math.floor(time / 1000) as Time;
  }

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const container = containerRef.current;
    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: 'rgba(143, 162, 191, 0.86)',
        fontSize: 11,
        fontFamily: "'SF Pro Display', 'Segoe UI', sans-serif",
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: {
          top: 0.08,
          bottom: showVolume ? 0.28 : 0.08,
        },
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        barSpacing: 10,
      },
      crosshair: {
        vertLine: {
          color: 'rgba(86, 231, 213, 0.12)',
          width: 1,
          labelVisible: false,
        },
        horzLine: {
          color: 'rgba(255, 255, 255, 0.08)',
          width: 1,
          labelBackgroundColor: '#0f1a2f',
        },
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
      },
      handleScroll: {
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: false,
        pinch: true,
      },
    });

    chartRef.current = chart;

    candleSeriesRef.current = chart.addCandlestickSeries({
      upColor: '#10d9b2',
      downColor: '#ff5d72',
      wickUpColor: '#19e3b7',
      wickDownColor: '#ff7286',
      borderVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    volumeSeriesRef.current = chart.addHistogramSeries({
      priceScaleId: 'volume',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chart.priceScale('volume').applyOptions({
      visible: showVolume,
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
      borderVisible: false,
    });

    movingAverageSeriesRef.current = chart.addLineSeries({
      color: '#ffad42',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      visible: showIndicators,
    });

    const resizeObserver = new ResizeObserver(() => {
      chart.timeScale().fitContent();
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      movingAverageSeriesRef.current = null;
    };
  }, [showIndicators, showVolume]);

  useEffect(() => {
    chartRef.current?.priceScale('volume').applyOptions({
      visible: showVolume,
    });
    movingAverageSeriesRef.current?.applyOptions({
      visible: showIndicators,
    });
  }, [showIndicators, showVolume]);

  useEffect(() => {
    if (!candleSeriesRef.current || candleData.length === 0) {
      return;
    }

    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current?.setData(volumeData);
    movingAverageSeriesRef.current?.setData(movingAverageData);
    chartRef.current?.timeScale().fitContent();
  }, [candleData, volumeData, movingAverageData]);

  return <div className="market-chart__surface" ref={containerRef} />;
}
