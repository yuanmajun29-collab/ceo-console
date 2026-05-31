<script setup lang="ts">
import { use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import {
  BarChart,
  LineChart,
  PieChart,
} from "echarts/charts";
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
} from "echarts/components";
import VChart from "vue-echarts";
import type { EChartsOption } from "echarts";

use([
  CanvasRenderer,
  BarChart,
  LineChart,
  PieChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
]);

defineProps<{
  option: EChartsOption;
  height?: string;
}>();
</script>

<template>
  <v-chart
    class="chart"
    :option="option"
    autoresize
    :style="{ height: height ?? '280px' }"
  />
</template>

<style scoped>
.chart {
  width: 100%;
}
</style>
