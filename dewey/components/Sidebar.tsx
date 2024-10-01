import React, { useEffect, useRef, useState } from 'react';
import dynamic from 'next/dynamic';

const Chart = dynamic(() => import('chart.js/auto').then((mod) => mod.Chart), {
  ssr: false,
});

interface SidebarProps {
  socket: any;
}

const Sidebar: React.FC<SidebarProps> = ({ socket }) => {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const chartRefs = useRef<{ [key: string]: any }>({
    cpu: null,
    memory: null,
    disk: null,
    gpu: null,
    gpuMemory: null,
  });

  useEffect(() => {
    if (socket) {
      socket.on('system_resources', (data: any) => {
        updateCharts(data);
      });
    }

    return () => {
      if (socket) {
        socket.off('system_resources');
      }
    };
  }, [socket]);

  useEffect(() => {
    const initCharts = async () => {
      const ChartJS = await Chart;
      initializeCharts(ChartJS);
    };
    initCharts();

    return () => {
      Object.values(chartRefs.current).forEach(chart => chart?.destroy());
    };
  }, []);

  const initializeCharts = (ChartJS: any) => {
    const chartConfig = {
      type: 'line',
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            type: 'time',
            time: {
              unit: 'second',
            },
          },
          y: {
            beginAtZero: true,
            max: 100,
          },
        },
        animation: false,
      },
      data: {
        datasets: [{
          data: [],
          borderColor: 'rgb(75, 192, 192)',
          tension: 0.1,
        }],
      },
    };

    ['cpu', 'memory', 'disk', 'gpu', 'gpuMemory'].forEach(chartName => {
      const ctx = document.getElementById(`${chartName}Chart`) as HTMLCanvasElement;
      if (ctx) {
        chartRefs.current[chartName] = new ChartJS(ctx, chartConfig);
      }
    });
  };

  const updateCharts = (data: any) => {
    const now = new Date();
    Object.entries(data).forEach(([key, value]) => {
      const chartName = key.replace('_', '').toLowerCase();
      const chart = chartRefs.current[chartName];
      if (chart) {
        chart.data.datasets[0].data.push({x: now, y: value});
        chart.update('none');
      }
    });
  };

  return (
    <div className={`w-80 bg-gray-800 p-4 ${isCollapsed ? 'hidden' : ''}`}>
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="mb-4 px-4 py-2 bg-gray-700 text-white rounded-lg"
      >
        {isCollapsed ? 'Show Charts' : 'Hide Charts'}
      </button>
      <div className="mb-4">
        <h3 className="text-white mb-2">CPU Load</h3>
        <canvas id="cpuChart"></canvas>
      </div>
      <div className="mb-4">
        <h3 className="text-white mb-2">Memory Usage</h3>
        <canvas id="memoryChart"></canvas>
      </div>
      <div className="mb-4">
        <h3 className="text-white mb-2">Disk I/O</h3>
        <canvas id="diskChart"></canvas>
      </div>
      <div className="mb-4">
        <h3 className="text-white mb-2">GPU Load</h3>
        <canvas id="gpuChart"></canvas>
      </div>
      <div className="mb-4">
        <h3 className="text-white mb-2">GPU Memory</h3>
        <canvas id="gpuMemoryChart"></canvas>
      </div>
    </div>
  );
};

export default Sidebar;